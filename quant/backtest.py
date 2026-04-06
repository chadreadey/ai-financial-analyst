"""
Quant-only backtest engine.

Runs the 6 technical signals from quant/signals.py on historical price data
without any LLM calls. Supports walk-forward validation with rolling
train/test windows.

Design:
  1. Fetch 10-year daily OHLCV for a universe via Tiingo
  2. At each rebalance date, compute SignalVector for every stock
  3. Rank by composite score → long top decile, short bottom decile
  4. Track daily portfolio returns with realistic frictions
  5. Compute risk-adjusted metrics and compare to SPY buy-and-hold
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from quant.signals import compute_signal_vector, SignalVector
from quant.universe import BENCHMARK

logger = logging.getLogger(__name__)


# ── Configuration ──────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    """All tunable knobs for a quant backtest run."""
    tickers: list[str]
    start_date: str = "2016-01-01"          # 10 years back from ~2026
    end_date: str = ""                       # defaults to today
    rebalance_freq: str = "monthly"          # "weekly" or "monthly"
    lookback_days: int = 252                 # signal computation lookback
    long_threshold: float = 0.20             # composite score to go long
    short_threshold: float = -0.40           # composite score to go short (tightened from -0.20)
    # Regime filter: require more signals to confirm shorts
    short_min_bearish_signals: int = 3       # N of 5 signals must be negative to short
    enable_regime_filter: bool = True        # SPY 200d SMA gates long-only vs allow-shorts
    enable_ic_calibration: bool = True       # adaptive signal weights from trailing IC
    ic_trailing_periods: int = 12            # trailing rebalance periods for IC computation
    ic_shrinkage: float = 0.90              # shrinkage toward equal weights (0=pure IC, 1=equal)
    max_long_positions: int = 10
    max_short_positions: int = 10
    transaction_cost_bps: float = 10.0       # 10bps round-trip
    execution_delay_days: int = 1            # no same-day fills
    stop_loss_atr_mult: float = 2.0          # stop at 2x ATR
    initial_capital: float = 100_000.0
    # Walk-forward
    train_months: int = 24                   # rolling train window
    test_months: int = 6                     # out-of-sample test window
    # Enhanced regime detection
    vix_caution_threshold: float = 20.0       # VIX above this = cautious (reduce sizing)
    vix_risk_off_threshold: float = 28.0      # VIX above this = risk-off (no new longs, allow shorts)
    enable_death_golden_cross: bool = True     # SPY 50/200 SMA cross detection
    golden_cross_boost: float = 0.10           # lower long threshold by this during golden cross
    # TimesFM overlay (DEPRECATED — prefer LSTM)
    enable_timesfm: bool = False
    timesfm_weight: float = 0.15             # weight for 7th signal
    timesfm_horizon: int = 10                # forecast horizon in days
    timesfm_lookback: int = 512              # input context length
    # News sentiment overlay (Finnhub)
    enable_news_sentiment: bool = False
    news_sentiment_weight: float = 0.10      # weight for sentiment in composite
    news_sentiment_window_days: int = 30     # days of news before rebalance date
    news_sentiment_min_articles: int = 3     # suppress signal if fewer articles
    # LSTM overlay
    enable_lstm: bool = False
    lstm_weight: float = 0.15                # weight for ML signal in composite
    lstm_lookback_days: int = 60             # LSTM sequence length
    lstm_forecast_horizon: int = 20          # predict N-day forward return
    lstm_hidden_size: int = 64
    lstm_num_layers: int = 2
    lstm_dropout: float = 0.3
    lstm_max_epochs: int = 100
    lstm_patience: int = 10

    def __post_init__(self):
        if not self.end_date:
            self.end_date = datetime.now().strftime("%Y-%m-%d")


# ── Data loading ───────────────────────────────────────────────────────

_PRICE_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", ".price_cache")


def _load_cached(ticker: str, start_date: str) -> Optional[pd.DataFrame]:
    """Load from local CSV cache if available and recent."""
    cache_file = os.path.join(_PRICE_CACHE_DIR, f"{ticker}.csv")
    if not os.path.exists(cache_file):
        return None
    try:
        df = pd.read_csv(cache_file, parse_dates=["date"], index_col="date")
        # Check if cache covers the requested start date (allow 7-day slack for weekends)
        cache_start = pd.Timestamp(df.index[0])
        request_start = pd.Timestamp(start_date)
        if (cache_start - request_start).days <= 7 and len(df) >= 60:
            return df
    except Exception:
        pass
    return None


def _save_cache(ticker: str, df: pd.DataFrame) -> None:
    """Save OHLCV to local CSV cache."""
    os.makedirs(_PRICE_CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(_PRICE_CACHE_DIR, f"{ticker}.csv")
    df.to_csv(cache_file)


def _fetch_ohlcv(ticker: str, start_date: str, provider=None) -> Optional[pd.DataFrame]:
    """Fetch daily OHLCV via price provider (with local CSV cache), return DataFrame."""
    # Try local cache first
    cached = _load_cached(ticker, start_date)
    if cached is not None:
        logger.info("Using cached data for %s (%d rows)", ticker, len(cached))
        return cached

    try:
        if provider is None:
            from price_provider import get_price_provider
            provider = get_price_provider()

        data = provider.get_eod_history(ticker, start_date)
        if not data or len(data) < 60:
            logger.warning("Insufficient data for %s (%d rows)", ticker, len(data) if data else 0)
            return None

        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(None)
        df = df.sort_values("date").set_index("date")

        # Prefer adjusted prices (split/dividend corrected) for backtesting
        out = pd.DataFrame(index=df.index)
        out["close"] = df["adjClose"] if "adjClose" in df.columns else df["close"]
        out["high"] = df["adjHigh"] if "adjHigh" in df.columns else df.get("high", out["close"])
        out["low"] = df["adjLow"] if "adjLow" in df.columns else df.get("low", out["close"])
        out["open"] = df["adjOpen"] if "adjOpen" in df.columns else df.get("open", out["close"])
        out["volume"] = df["adjVolume"] if "adjVolume" in df.columns else df.get("volume", 0)

        _save_cache(ticker, out)
        return out

    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", ticker, exc)
        return None


def load_universe_data(
    tickers: list[str], start_date: str, api_key: str = "",
    progress_cb=None, provider=None,
) -> dict[str, pd.DataFrame]:
    """Load OHLCV for all tickers. Returns {ticker: DataFrame}.

    Args:
        api_key: Deprecated — kept for backward compat. Use provider or PRICE_PROVIDER env var.
        provider: A PriceProvider instance. If None, built from env vars.
    """
    if provider is None:
        from price_provider import get_price_provider
        try:
            provider = get_price_provider()
        except EnvironmentError:
            # Fallback: try legacy api_key param with Tiingo
            if api_key:
                from tiingo_client import TiingoClient, TiingoCache
                provider = TiingoCache(TiingoClient(api_key))
            else:
                raise

    data = {}
    for i, ticker in enumerate(tickers):
        if progress_cb:
            progress_cb(f"Fetching {ticker} ({i+1}/{len(tickers)})")
        df = _fetch_ohlcv(ticker, start_date, provider)
        if df is not None:
            data[ticker] = df
            logger.info("Loaded %s: %d rows (%s to %s)",
                        ticker, len(df), df.index[0].date(), df.index[-1].date())
        else:
            logger.warning("Skipping %s — no data", ticker)
    return data


# ── Signal computation at a point in time ──────────────────────────────

def compute_signals_at_date(
    universe_data: dict[str, pd.DataFrame],
    as_of_date: pd.Timestamp,
    lookback_days: int = 252,
) -> dict[str, SignalVector]:
    """Compute SignalVector for each stock using only data up to as_of_date."""
    results = {}
    for ticker, df in universe_data.items():
        # Slice to data available on as_of_date
        available = df[df.index <= as_of_date]
        if len(available) < 60:
            continue

        # Use last `lookback_days` rows for signal computation
        window = available.tail(lookback_days)
        try:
            sv = compute_signal_vector(
                close=window["close"],
                volume=window["volume"],
                high=window["high"],
                low=window["low"],
            )
            results[ticker] = sv
        except Exception as exc:
            logger.debug("Signal computation failed for %s at %s: %s",
                         ticker, as_of_date.date(), exc)
    return results


# ── IC Weight Calibration ──────────────────────────────────────────────

SIGNAL_NAMES = ["sma_trend", "mean_reversion_z", "bollinger_pctb", "rsi", "obv_trend"]
DEFAULT_WEIGHTS = {
    "sma_trend": 0.25, "mean_reversion_z": 0.20,
    "bollinger_pctb": 0.20, "rsi": 0.15, "obv_trend": 0.20,
}


def compute_signal_ic(
    universe_data: dict[str, pd.DataFrame],
    rebalance_dates: list[pd.Timestamp],
    lookback_days: int = 252,
    forward_days: int = 21,
) -> dict[str, list[float]]:
    """
    Compute rank IC (Spearman) for each signal across historical rebalance dates.

    At each date: score all stocks on each signal, then measure rank correlation
    with their forward N-day returns. Returns {signal_name: [ic_at_date1, ic_at_date2, ...]}.
    """
    from scipy.stats import spearmanr

    ic_history = {name: [] for name in SIGNAL_NAMES}

    for reb_date in rebalance_dates:
        signals = compute_signals_at_date(universe_data, reb_date, lookback_days)
        if len(signals) < 5:
            continue

        # Compute forward returns for each stock
        forward_returns = {}
        for ticker, df in universe_data.items():
            future = df[(df.index > reb_date)]
            if len(future) < forward_days:
                continue
            entry_price = float(future.iloc[0]["close"])
            exit_price = float(future.iloc[min(forward_days - 1, len(future) - 1)]["close"])
            if entry_price > 0:
                forward_returns[ticker] = (exit_price - entry_price) / entry_price

        # Need overlap between signals and forward returns
        common = set(signals.keys()) & set(forward_returns.keys())
        if len(common) < 5:
            continue

        tickers = sorted(common)
        fwd = [forward_returns[t] for t in tickers]

        for sig_name in SIGNAL_NAMES:
            scores = []
            for t in tickers:
                sv = signals[t]
                scores.append(getattr(sv, sig_name).score)

            if len(set(scores)) < 2:  # all same score = undefined correlation
                continue

            ic, _ = spearmanr(scores, fwd)
            if not np.isnan(ic):
                ic_history[sig_name].append(ic)

    return ic_history


def calibrate_weights_from_ic(
    ic_history: dict[str, list[float]],
    trailing_periods: int = 12,
    shrinkage: float = 0.3,
) -> dict[str, float]:
    """
    Derive signal weights from trailing IC values.

    Uses mean IC over trailing periods, applies shrinkage toward equal weights,
    and normalizes. Signals with negative IC get zero weight (don't bet against them).
    """
    raw_ics = {}
    for name, ics in ic_history.items():
        recent = ics[-trailing_periods:] if len(ics) >= trailing_periods else ics
        if recent:
            raw_ics[name] = float(np.mean(recent))
        else:
            raw_ics[name] = 0.0

    # Zero out negative ICs — don't use signals that predict backwards
    for name in raw_ics:
        if raw_ics[name] < 0:
            raw_ics[name] = 0.0

    total_ic = sum(raw_ics.values())
    if total_ic <= 0:
        return dict(DEFAULT_WEIGHTS)

    # IC-proportional weights
    ic_weights = {name: ic / total_ic for name, ic in raw_ics.items()}

    # Shrink toward equal weights for stability
    equal_weight = 1.0 / len(SIGNAL_NAMES)
    blended = {}
    for name in SIGNAL_NAMES:
        blended[name] = (1 - shrinkage) * ic_weights.get(name, 0) + shrinkage * equal_weight

    # Normalize
    total = sum(blended.values())
    return {name: round(w / total, 4) for name, w in blended.items()}


def apply_calibrated_weights(
    signals: dict[str, SignalVector],
    weights: dict[str, float],
) -> dict[str, SignalVector]:
    """Recompute composite scores using calibrated weights instead of defaults."""
    for ticker, sv in signals.items():
        score = (
            sv.sma_trend.score * weights.get("sma_trend", 0.2) +
            sv.mean_reversion_z.score * weights.get("mean_reversion_z", 0.2) +
            sv.bollinger_pctb.score * weights.get("bollinger_pctb", 0.2) +
            sv.rsi.score * weights.get("rsi", 0.2) +
            sv.obv_trend.score * weights.get("obv_trend", 0.2)
        )
        sv.composite_score = float(np.clip(score, -1.0, 1.0))

        if sv.composite_score >= 0.30:
            sv.composite_direction = "BUY"
        elif sv.composite_score <= -0.30:
            sv.composite_direction = "SELL"
        else:
            sv.composite_direction = "HOLD"
        sv.actionable = abs(sv.composite_score) >= 0.40

    return signals


# ── VIX data loading ──────────────────────────────────────────────────

_VIX_CACHE: Optional[pd.DataFrame] = None


def load_vix_data(start_date: str) -> Optional[pd.DataFrame]:
    """Load VIX data from yfinance with local CSV cache."""
    global _VIX_CACHE
    if _VIX_CACHE is not None and len(_VIX_CACHE) > 0:
        request_start = pd.Timestamp(start_date)
        cache_start = _VIX_CACHE.index[0]
        if (cache_start - request_start).days <= 7:
            return _VIX_CACHE
        # In-memory cache doesn't cover needed range — refetch
        _VIX_CACHE = None

    cache_file = os.path.join(_PRICE_CACHE_DIR, "VIX.csv")

    # Try local cache — must cover the requested start date
    if os.path.exists(cache_file):
        try:
            df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            cache_start = df.index[0]
            cache_end = df.index[-1]
            request_start = pd.Timestamp(start_date)
            # Cache valid if it covers start date (within 7 days) and is recent
            if ((cache_start - request_start).days <= 7 and
                    (pd.Timestamp.now() - cache_end).days <= 3):
                logger.info("Using cached VIX data (%d rows)", len(df))
                _VIX_CACHE = df
                return df
            else:
                logger.info("VIX cache stale (starts %s, need %s) — refetching",
                            cache_start.date(), start_date)
        except Exception:
            pass

    # Fetch from yfinance
    try:
        import yfinance as yf
        vix = yf.download("^VIX", start=start_date, progress=False)
        if vix is None or len(vix) < 60:
            logger.warning("Insufficient VIX data")
            return None

        # Flatten multi-level columns if present
        if hasattr(vix.columns, 'levels'):
            vix.columns = vix.columns.get_level_values(0)

        df = pd.DataFrame(index=vix.index)
        df["close"] = vix["Close"]
        df.index = df.index.tz_localize(None) if df.index.tz else df.index

        # Cache it
        os.makedirs(_PRICE_CACHE_DIR, exist_ok=True)
        df.to_csv(cache_file)
        logger.info("Fetched and cached VIX data (%d rows)", len(df))
        _VIX_CACHE = df
        return df
    except Exception as exc:
        logger.warning("Failed to fetch VIX: %s", exc)
        return None


# ── Regime detection ───────────────────────────────────────────────────

@dataclass
class RegimeState:
    """Rich regime information for portfolio construction."""
    level: str          # "risk_off", "bearish", "cautious", "bullish", "strong_bull"
    vix: Optional[float] = None
    sma_cross: Optional[str] = None  # "death_cross", "golden_cross", or None
    spy_vs_sma200: Optional[str] = None  # "above" or "below"
    sizing_scalar: float = 1.0  # position sizing multiplier


def detect_regime(
    benchmark_df: Optional[pd.DataFrame],
    as_of_date: pd.Timestamp,
    vix_df: Optional[pd.DataFrame] = None,
    config: Optional[BacktestConfig] = None,
) -> RegimeState:
    """
    Multi-factor regime detection: VIX level + SPY SMA trend + death/golden cross.

    Regime hierarchy (strongest signal wins):
      risk_off   — VIX > risk_off_threshold OR death cross active + bearish SMA
      bearish    — SPY below 200d SMA (or death cross active)
      cautious   — VIX > caution_threshold (elevated but not crisis)
      bullish    — SPY above 200d SMA
      strong_bull — golden cross active + SPY above 200d SMA + low VIX
    """
    state = RegimeState(level="unknown")

    if benchmark_df is None:
        return state

    available = benchmark_df[benchmark_df.index <= as_of_date]
    if len(available) < 200:
        return state

    price = float(available.iloc[-1]["close"])
    sma200 = float(available["close"].tail(200).mean())
    sma50 = float(available["close"].tail(50).mean()) if len(available) >= 50 else None

    state.spy_vs_sma200 = "above" if price > sma200 else "below"

    # Death cross / Golden cross detection (50d SMA vs 200d SMA)
    if sma50 is not None and config and config.enable_death_golden_cross:
        if sma50 < sma200:
            state.sma_cross = "death_cross"
        elif sma50 > sma200:
            # Confirm golden cross: 50d must have crossed from below recently
            # (just being above isn't enough — check it was below within last 20 days)
            if len(available) >= 220:
                sma50_20ago = float(available["close"].iloc[-70:-20].tail(50).mean())
                sma200_20ago = float(available["close"].iloc[-220:-20].tail(200).mean())
                if sma50_20ago <= sma200_20ago:
                    state.sma_cross = "golden_cross"  # recent crossover
                else:
                    state.sma_cross = "golden_cross"  # sustained golden cross still counts

    # VIX level
    if vix_df is not None:
        vix_available = vix_df[vix_df.index <= as_of_date]
        if len(vix_available) > 0:
            state.vix = float(vix_available.iloc[-1]["close"])

    # Determine regime level (hierarchy: risk_off > bearish > cautious > bullish > strong_bull)
    vix_threshold_caution = config.vix_caution_threshold if config else 20.0
    vix_threshold_risk_off = config.vix_risk_off_threshold if config else 28.0

    if state.vix is not None and state.vix >= vix_threshold_risk_off:
        state.level = "risk_off"
        state.sizing_scalar = 0.25  # minimal positions
    elif state.sma_cross == "death_cross" and state.spy_vs_sma200 == "below":
        state.level = "risk_off"
        state.sizing_scalar = 0.25
    elif state.spy_vs_sma200 == "below":
        state.level = "bearish"
        state.sizing_scalar = 0.50  # half-size longs
    elif state.vix is not None and state.vix >= vix_threshold_caution:
        state.level = "cautious"
        state.sizing_scalar = 0.70  # reduced sizing
    elif state.sma_cross == "golden_cross":
        state.level = "strong_bull"
        state.sizing_scalar = 1.0
    elif state.spy_vs_sma200 == "above":
        state.level = "bullish"
        state.sizing_scalar = 1.0
    else:
        state.level = "unknown"

    return state


def count_bearish_signals(sv: SignalVector) -> int:
    """Count how many of the 5 directional signals are negative."""
    count = 0
    if sv.sma_trend.score < 0:
        count += 1
    if sv.mean_reversion_z.score < 0:
        count += 1
    if sv.bollinger_pctb.score < 0:
        count += 1
    if sv.rsi.score < 0:
        count += 1
    if sv.obv_trend.score < 0:
        count += 1
    return count


# ── TimesFM forecast at a point in time ────────────────────────────────

_timesfm_model = None
_lstm_forecaster = None  # Set externally by run_ml_backtest.py before each window
_finnhub_client = None   # Set externally or auto-initialized from FINNHUB_API_KEY
_sentiment_cache = None  # SentimentDiskCache — set externally or auto-initialized


def _get_timesfm_model():
    """Lazy-load TimesFM model (singleton)."""
    global _timesfm_model
    if _timesfm_model is not None:
        return _timesfm_model
    try:
        from quant.timesfm.model import TimesFMModel
        _timesfm_model = TimesFMModel.get()
        return _timesfm_model
    except Exception as exc:
        logger.error("Failed to load TimesFM model: %s", exc)
        return None


def compute_timesfm_scores(
    universe_data: dict[str, pd.DataFrame],
    as_of_date: pd.Timestamp,
    horizon: int = 10,
    lookback: int = 512,
) -> dict[str, float]:
    """
    Run TimesFM forecast for each stock as of a date.
    Returns {ticker: momentum_score} where score is in [-1, +1].
    """
    model = _get_timesfm_model()
    if model is None:
        return {}

    from quant.timesfm.signals import extract_signals

    scores = {}
    for ticker, df in universe_data.items():
        available = df[df.index <= as_of_date]
        if len(available) < 64:
            continue

        prices = available["close"].tail(lookback).tolist()
        try:
            point, quantiles = model.forecast(prices, horizon=horizon, freq=0)
            signals = extract_signals(
                current_value=prices[-1],
                point_forecast=point,
                quantiles=quantiles,
            )
            scores[ticker] = float(signals["momentum_score"])
        except Exception as exc:
            logger.debug("TimesFM forecast failed for %s at %s: %s",
                         ticker, as_of_date.date(), exc)

    return scores


def blend_timesfm_into_signals(
    signals: dict[str, SignalVector],
    timesfm_scores: dict[str, float],
    timesfm_weight: float = 0.15,
) -> dict[str, SignalVector]:
    """
    Blend TimesFM momentum score into each stock's composite.

    The 6 quant signals keep their relative weights but are scaled down
    so that quant_total + timesfm_weight = 1.0.
    """
    if not timesfm_scores:
        return signals

    quant_scale = 1.0 - timesfm_weight

    for ticker, sv in signals.items():
        tfm_score = timesfm_scores.get(ticker)
        if tfm_score is None:
            continue

        # Scale down the existing quant composite and add TimesFM
        blended = sv.composite_score * quant_scale + tfm_score * timesfm_weight
        sv.composite_score = float(np.clip(blended, -1.0, 1.0))

        # Re-derive direction from blended score
        if sv.composite_score >= 0.30:
            sv.composite_direction = "BUY"
        elif sv.composite_score <= -0.30:
            sv.composite_direction = "SELL"
        else:
            sv.composite_direction = "HOLD"
        sv.actionable = abs(sv.composite_score) >= 0.40

    return signals


# ── LSTM scoring at a point in time ──────────────────────────────────

def compute_lstm_scores(
    universe_data: dict[str, pd.DataFrame],
    as_of_date: pd.Timestamp,
    forecaster: "quant.lstm.model.ReturnForecaster",
) -> dict[str, float]:
    """
    Run LSTM predictions for each stock as of a date.
    Returns {ticker: momentum_score} where score is in [-1, +1].

    The forecaster must already be fitted on training data.
    """
    from quant.lstm.model import build_features

    scores = {}
    for ticker, df in universe_data.items():
        available = df[df.index <= as_of_date]
        if len(available) < 252:  # need enough history for features
            continue

        try:
            feats = build_features(available)
            score_series = forecaster.predict_momentum_score(feats)
            last_valid = score_series.dropna()
            if not last_valid.empty:
                scores[ticker] = float(last_valid.iloc[-1])
        except Exception as exc:
            logger.debug("LSTM prediction failed for %s at %s: %s",
                         ticker, as_of_date.date(), exc)

    return scores


def blend_lstm_into_signals(
    signals: dict[str, SignalVector],
    lstm_scores: dict[str, float],
    lstm_weight: float = 0.15,
) -> dict[str, SignalVector]:
    """
    Blend LSTM momentum score into each stock's composite.

    Same mechanics as blend_timesfm_into_signals — scales down quant
    signals and adds the ML signal.
    """
    if not lstm_scores:
        return signals

    quant_scale = 1.0 - lstm_weight

    for ticker, sv in signals.items():
        score = lstm_scores.get(ticker)
        if score is None:
            continue

        blended = sv.composite_score * quant_scale + score * lstm_weight
        sv.composite_score = float(np.clip(blended, -1.0, 1.0))

        if sv.composite_score >= 0.30:
            sv.composite_direction = "BUY"
        elif sv.composite_score <= -0.30:
            sv.composite_direction = "SELL"
        else:
            sv.composite_direction = "HOLD"
        sv.actionable = abs(sv.composite_score) >= 0.40

    return signals


# ── News sentiment scoring at a point in time ────────────────────────

def compute_sentiment_scores(
    universe_data: dict[str, pd.DataFrame],
    as_of_date: pd.Timestamp,
    config: BacktestConfig,
    client=None,
    disk_cache=None,
) -> dict[str, tuple[float, int]]:
    """
    Compute news sentiment score for each stock as of a date.
    Returns {ticker: (score, n_articles)} where score is in [-1, +1].

    n_articles is the raw news article count — used by blend_sentiment_into_signals
    to scale effective weight by coverage density. Insider MSPR always counts as
    full coverage (it's a clean signal, not sparse text).

    Blends news sentiment (VADER on headlines) with insider MSPR if available.
    """
    from quant.sentiment import compute_news_sentiment_score, compute_insider_sentiment_score

    scores = {}
    for ticker in universe_data:
        # News sentiment
        news_result = compute_news_sentiment_score(
            ticker, as_of_date,
            news_window_days=config.news_sentiment_window_days,
            client=client,
            disk_cache=disk_cache,
            min_articles=config.news_sentiment_min_articles,
        )
        n_articles: int = news_result.metadata.get("n_articles", 0)

        # Insider sentiment (bonus signal — free and has 10yr history)
        insider_result = compute_insider_sentiment_score(
            ticker, as_of_date,
            lookback_months=3,
            client=client,
            disk_cache=disk_cache,
        )

        # Combine: 70% news, 30% insider (if both available)
        if news_result.score != 0.0 and insider_result.score != 0.0:
            combined = news_result.score * 0.7 + insider_result.score * 0.3
        elif news_result.score != 0.0:
            combined = news_result.score
        elif insider_result.score != 0.0:
            # Insider-only: treat as sparse coverage (n_articles stays 0)
            combined = insider_result.score
        else:
            continue  # no signal

        scores[ticker] = (float(np.clip(combined, -1.0, 1.0)), n_articles)

    return scores


_SENTIMENT_COVERAGE_FULL = 20   # articles/month for full weight
_SENTIMENT_HIGH_VOL_SCALE = 0.5  # halve weight during high-vol regime


def blend_sentiment_into_signals(
    signals: dict[str, SignalVector],
    sentiment_scores: dict[str, tuple[float, int]],
    sentiment_weight: float = 0.10,
) -> dict[str, SignalVector]:
    """
    Blend news sentiment into each stock's composite with adaptive weighting.

    Effective weight = base_weight
                       × coverage_scale(n_articles)
                       × regime_scale(atr_regime)

    coverage_scale  = min(1.0, n_articles / COVERAGE_FULL)
                      → full weight at 20+ articles, proportionally less below.
                      → 0 articles (insider-only) → 0× news scale, but insider
                         MSPR is still carried in the score itself.

    regime_scale    = 0.5 if atr_regime == "high_vol" else 1.0
                      → during high-vol periods news sentiment lags the move;
                         halving weight prevents chasing panicked headlines.

    Raw (score, n_articles) pairs are preserved in metadata so downstream
    systems (e.g. GraphRAG, geopolitical NLP layer) can consume them directly
    without re-running sentiment.

    Order: IC weights → LSTM blend → sentiment blend (always last).
    """
    if not sentiment_scores:
        return signals

    for ticker, sv in signals.items():
        entry = sentiment_scores.get(ticker)
        if entry is None:
            continue

        score, n_articles = entry

        # Coverage scaling: sparse news → reduced weight
        coverage_scale = min(1.0, n_articles / _SENTIMENT_COVERAGE_FULL)

        # Regime scaling: noisy in high-vol environments
        vol_regime = sv.atr_regime.metadata.get("volatility_regime", "normal")
        regime_scale = _SENTIMENT_HIGH_VOL_SCALE if vol_regime == "high_vol" else 1.0

        effective_weight = sentiment_weight * coverage_scale * regime_scale

        if effective_weight < 1e-6:
            # No meaningful weight — skip blend but still log the raw signal
            sv.flags.append(
                f"sentiment_suppressed(articles={n_articles},regime={vol_regime})"
            )
            continue

        quant_scale = 1.0 - effective_weight
        blended = sv.composite_score * quant_scale + score * effective_weight
        sv.composite_score = float(np.clip(blended, -1.0, 1.0))

        if sv.composite_score >= 0.30:
            sv.composite_direction = "BUY"
        elif sv.composite_score <= -0.30:
            sv.composite_direction = "SELL"
        else:
            sv.composite_direction = "HOLD"
        sv.actionable = abs(sv.composite_score) >= 0.40

        # Flag: log effective weight and extreme raw sentiment for audit trail
        sv.flags.append(
            f"sentiment_w={effective_weight:.3f}"
            f"(cov={coverage_scale:.2f},regime={vol_regime})"
        )
        if abs(score) >= 0.7:
            sv.flags.append(f"sentiment={'bullish' if score > 0 else 'bearish'}({score:.2f})")

    return signals


# ── Portfolio construction ─────────────────────────────────────────────

@dataclass
class Position:
    ticker: str
    direction: str          # "LONG" or "SHORT"
    entry_date: pd.Timestamp
    entry_price: float
    shares: float
    stop_price: float
    composite_score: float
    flags: list = field(default_factory=list)

    @property
    def notional(self) -> float:
        return abs(self.shares * self.entry_price)


def build_target_portfolio(
    signals: dict[str, SignalVector],
    universe_data: dict[str, pd.DataFrame],
    as_of_date: pd.Timestamp,
    config: BacktestConfig,
    capital: float,
    regime: RegimeState = None,
) -> list[Position]:
    """Rank stocks by composite score and build long/short positions."""
    if regime is None:
        regime = RegimeState(level="unknown")

    # Sort by composite score
    scored = [(ticker, sv.composite_score, sv) for ticker, sv in signals.items()]
    scored.sort(key=lambda x: x[1], reverse=True)

    positions = []
    n_stocks = len(scored)
    if n_stocks == 0:
        return positions

    # Risk-off: no new longs (close existing at next rebalance)
    if regime.level == "risk_off":
        # Only allow shorts in risk-off — longs are too dangerous
        longs = []
    else:
        # Golden cross / strong_bull: lower the long threshold to catch more entries
        effective_long_threshold = config.long_threshold
        if regime.level == "strong_bull" and config.enable_death_golden_cross:
            effective_long_threshold = config.long_threshold - config.golden_cross_boost
            logger.debug("Golden cross active: long threshold lowered to %.2f", effective_long_threshold)

        longs = [(t, sc, sv) for t, sc, sv in scored if sc >= effective_long_threshold]
        longs = longs[:config.max_long_positions]

    # Short: bottom scorers below threshold, with regime + signal confirmation filters
    shorts_raw = [(t, sc, sv) for t, sc, sv in scored if sc <= config.short_threshold]
    shorts = []

    # Risk-off with HIGH VIX = reduce ALL exposure (V-shaped crash risk)
    # Risk-off from death cross (no VIX spike) = shorts OK
    vix_driven_risk_off = (regime.level == "risk_off" and
                           regime.vix is not None and
                           regime.vix >= (config.vix_risk_off_threshold if config else 28.0))

    for t, sc, sv in shorts_raw:
        # High-VIX risk-off: no new shorts either (go to cash)
        if vix_driven_risk_off:
            logger.debug("Skipping short %s in VIX risk-off (VIX=%.1f)", t, regime.vix)
            continue
        # In bullish/strong_bull regime, require extra confirmation to short
        if config.enable_regime_filter and regime.level in ("bullish", "strong_bull"):
            bearish_count = count_bearish_signals(sv)
            if bearish_count < config.short_min_bearish_signals + 1:  # stricter in bull market
                logger.debug("Skipping short %s in %s regime: only %d/5 bearish signals",
                             t, regime.level, bearish_count)
                continue
        # In cautious regime, require extra confirmation too (VIX elevated = risky for shorts)
        elif config.enable_regime_filter and regime.level == "cautious":
            bearish_count = count_bearish_signals(sv)
            if bearish_count < config.short_min_bearish_signals + 1:
                continue
        # In bearish regime (SMA-confirmed downtrend, low VIX), shorts more freely
        elif config.enable_regime_filter and regime.level == "bearish":
            bearish_count = count_bearish_signals(sv)
            if bearish_count < min(config.short_min_bearish_signals, 2):
                continue
        # Death-cross risk-off (no VIX spike): shorts allowed with standard confirmation
        elif config.enable_regime_filter and regime.level == "risk_off":
            bearish_count = count_bearish_signals(sv)
            if bearish_count < config.short_min_bearish_signals:
                continue
        # Fallback: standard check
        elif config.short_min_bearish_signals > 0:
            bearish_count = count_bearish_signals(sv)
            if bearish_count < config.short_min_bearish_signals:
                continue
        shorts.append((t, sc, sv))
    shorts = shorts[-config.max_short_positions:]  # worst scores

    # Equal-weight allocation within each leg
    n_positions = len(longs) + len(shorts)
    if n_positions == 0:
        return positions

    per_position_capital = capital / max(n_positions, 1)

    # Apply regime-based sizing scalar
    regime_scalar = regime.sizing_scalar

    for ticker, score, sv in longs:
        df = universe_data[ticker]
        # Execution delay: use price 1 day after signal
        future = df[df.index > as_of_date]
        if len(future) < config.execution_delay_days:
            continue
        entry_row = future.iloc[config.execution_delay_days - 1]
        entry_price = float(entry_row["close"])
        if entry_price <= 0:
            continue

        # ATR-based position sizing: reduce size in high-vol regimes
        atr_pct = sv.atr_regime.metadata.get("atr_pct", 1.5)
        vol_scalar = min(2.0 / max(atr_pct, 0.5), 2.0)  # scale down if vol > 2%
        adjusted_capital = per_position_capital * vol_scalar * regime_scalar
        shares = adjusted_capital / entry_price

        # Stop loss at 2x ATR below entry
        atr_val = sv.atr_regime.metadata.get("atr_value", entry_price * 0.02)
        stop_price = entry_price - config.stop_loss_atr_mult * atr_val

        positions.append(Position(
            ticker=ticker, direction="LONG",
            entry_date=future.index[config.execution_delay_days - 1],
            entry_price=entry_price, shares=shares,
            stop_price=stop_price, composite_score=score,
            flags=list(sv.flags),
        ))

    for ticker, score, sv in shorts:
        df = universe_data[ticker]
        future = df[df.index > as_of_date]
        if len(future) < config.execution_delay_days:
            continue
        entry_row = future.iloc[config.execution_delay_days - 1]
        entry_price = float(entry_row["close"])
        if entry_price <= 0:
            continue

        atr_pct = sv.atr_regime.metadata.get("atr_pct", 1.5)
        vol_scalar = min(2.0 / max(atr_pct, 0.5), 2.0)
        # In bearish regime, shorts get full sizing (not scaled down)
        short_regime_scalar = 1.0 if regime.level == "bearish" else regime_scalar
        adjusted_capital = per_position_capital * vol_scalar * short_regime_scalar
        shares = adjusted_capital / entry_price

        atr_val = sv.atr_regime.metadata.get("atr_value", entry_price * 0.02)
        stop_price = entry_price + config.stop_loss_atr_mult * atr_val

        positions.append(Position(
            ticker=ticker, direction="SHORT",
            entry_date=future.index[config.execution_delay_days - 1],
            entry_price=entry_price, shares=shares,
            stop_price=stop_price, composite_score=score,
            flags=list(sv.flags),
        ))

    return positions


# ── Rebalance date generation ──────────────────────────────────────────

def generate_rebalance_dates(
    start: pd.Timestamp, end: pd.Timestamp, freq: str, trading_dates: pd.DatetimeIndex,
) -> list[pd.Timestamp]:
    """Generate rebalance dates aligned to actual trading days."""
    if freq == "weekly":
        # Every Friday (or last trading day of the week)
        candidates = pd.date_range(start, end, freq="W-FRI")
    elif freq == "monthly":
        # Last trading day of each month
        candidates = pd.date_range(start, end, freq="BME")
    else:
        raise ValueError(f"Unknown rebalance frequency: {freq}")

    # Snap to nearest prior trading day
    result = []
    for d in candidates:
        mask = trading_dates <= d
        if mask.any():
            result.append(trading_dates[mask][-1])
    return sorted(set(result))


# ── Core backtest loop ─────────────────────────────────────────────────

@dataclass
class TradeRecord:
    ticker: str
    direction: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    pnl_pct: float
    pnl_dollar: float
    exit_reason: str
    composite_score: float
    holding_days: int
    flags: list = field(default_factory=list)


@dataclass
class BacktestResult:
    status: str = "pending"
    # Summary metrics
    total_return_pct: float = 0.0
    annual_return_pct: float = 0.0
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    calmar: Optional[float] = None
    max_drawdown_pct: float = 0.0
    win_rate_pct: float = 0.0
    total_trades: int = 0
    avg_holding_days: float = 0.0
    # Benchmark comparison
    benchmark_return_pct: float = 0.0
    benchmark_sharpe: Optional[float] = None
    alpha_pct: float = 0.0
    # By conviction band
    conviction_bands: dict = field(default_factory=dict)
    # Curves and logs
    equity_curve: list[dict] = field(default_factory=list)
    benchmark_curve: list[dict] = field(default_factory=list)
    trade_log: list[dict] = field(default_factory=list)
    walk_forward: list[dict] = field(default_factory=list)
    # Config echo
    config_summary: dict = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "total_return_pct": self.total_return_pct,
            "annual_return_pct": self.annual_return_pct,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "calmar": self.calmar,
            "max_drawdown_pct": self.max_drawdown_pct,
            "win_rate_pct": self.win_rate_pct,
            "total_trades": self.total_trades,
            "avg_holding_days": self.avg_holding_days,
            "benchmark_return_pct": self.benchmark_return_pct,
            "benchmark_sharpe": self.benchmark_sharpe,
            "alpha_pct": self.alpha_pct,
            "conviction_bands": self.conviction_bands,
            "equity_curve": self.equity_curve,
            "benchmark_curve": self.benchmark_curve,
            "trade_log": [t if isinstance(t, dict) else vars(t) for t in self.trade_log],
            "walk_forward": self.walk_forward,
            "config_summary": self.config_summary,
            "error": self.error,
        }


def _compute_daily_portfolio_returns(
    positions: list[Position],
    universe_data: dict[str, pd.DataFrame],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    config: BacktestConfig,
) -> tuple[list[TradeRecord], pd.Series]:
    """
    Compute daily portfolio returns from positions held between start_date and end_date.
    Returns trade records and a daily return series.
    """
    trades = []
    daily_pnl = {}  # date -> total dollar pnl

    for pos in positions:
        df = universe_data.get(pos.ticker)
        if df is None:
            continue

        # Daily prices during holding period
        mask = (df.index >= pos.entry_date) & (df.index <= end_date)
        holding = df[mask]
        if len(holding) < 2:
            continue

        exit_price = None
        exit_date = None
        exit_reason = "rebalance"

        for i in range(1, len(holding)):
            date = holding.index[i]
            price = float(holding.iloc[i]["close"])
            prev_price = float(holding.iloc[i - 1]["close"])

            # Daily PnL
            if pos.direction == "LONG":
                day_ret = (price - prev_price) / prev_price
                day_pnl = pos.shares * (price - prev_price)
                # Stop loss check
                if price <= pos.stop_price:
                    exit_price = price
                    exit_date = date
                    exit_reason = "stop_loss"
            else:  # SHORT
                day_ret = (prev_price - price) / prev_price
                day_pnl = pos.shares * (prev_price - price)
                if price >= pos.stop_price:
                    exit_price = price
                    exit_date = date
                    exit_reason = "stop_loss"

            d_str = date
            daily_pnl[d_str] = daily_pnl.get(d_str, 0.0) + day_pnl

            if exit_reason == "stop_loss":
                break

        # Final exit
        if exit_price is None:
            exit_date = holding.index[-1]
            exit_price = float(holding.iloc[-1]["close"])

        # Transaction costs
        cost = pos.notional * config.transaction_cost_bps / 10000 * 2  # round trip

        if pos.direction == "LONG":
            pnl_dollar = pos.shares * (exit_price - pos.entry_price) - cost
            pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
        else:
            pnl_dollar = pos.shares * (pos.entry_price - exit_price) - cost
            pnl_pct = (pos.entry_price - exit_price) / pos.entry_price * 100

        pnl_pct -= config.transaction_cost_bps / 100 * 2  # adjust pct for costs

        trades.append(TradeRecord(
            ticker=pos.ticker,
            direction=pos.direction,
            entry_date=str(pos.entry_date.date()),
            entry_price=round(pos.entry_price, 2),
            exit_date=str(exit_date.date()) if hasattr(exit_date, 'date') else str(exit_date),
            exit_price=round(exit_price, 2),
            pnl_pct=round(pnl_pct, 2),
            pnl_dollar=round(pnl_dollar, 2),
            exit_reason=exit_reason,
            composite_score=round(pos.composite_score, 4),
            holding_days=(exit_date - pos.entry_date).days,
            flags=pos.flags,
        ))

    # Convert daily_pnl dict to sorted Series
    if daily_pnl:
        pnl_series = pd.Series(daily_pnl).sort_index()
    else:
        pnl_series = pd.Series(dtype=float)

    return trades, pnl_series


def run_backtest(
    config: BacktestConfig,
    progress_cb=None,
) -> BacktestResult:
    """
    Execute a full quant-only backtest.

    Steps:
      1. Load OHLCV data for universe + benchmark
      2. Generate rebalance dates
      3. At each rebalance: compute signals, build portfolio, track returns
      4. Aggregate metrics
    """
    result = BacktestResult(status="running")
    result.config_summary = {
        "tickers": config.tickers,
        "start_date": config.start_date,
        "end_date": config.end_date,
        "rebalance_freq": config.rebalance_freq,
        "long_threshold": config.long_threshold,
        "short_threshold": config.short_threshold,
        "transaction_cost_bps": config.transaction_cost_bps,
        "execution_delay_days": config.execution_delay_days,
        "stop_loss_atr_mult": config.stop_loss_atr_mult,
        "n_tickers": len(config.tickers),
        "enable_regime_filter": config.enable_regime_filter,
        "vix_caution_threshold": config.vix_caution_threshold,
        "vix_risk_off_threshold": config.vix_risk_off_threshold,
        "enable_death_golden_cross": config.enable_death_golden_cross,
        "short_min_bearish_signals": config.short_min_bearish_signals,
        "enable_ic_calibration": config.enable_ic_calibration,
        "ic_shrinkage": config.ic_shrinkage if config.enable_ic_calibration else None,
        "ic_trailing_periods": config.ic_trailing_periods if config.enable_ic_calibration else None,
        "enable_timesfm": config.enable_timesfm,
        "timesfm_weight": config.timesfm_weight if config.enable_timesfm else None,
        "enable_lstm": config.enable_lstm,
        "lstm_weight": config.lstm_weight if config.enable_lstm else None,
        "enable_news_sentiment": config.enable_news_sentiment,
        "news_sentiment_weight": config.news_sentiment_weight if config.enable_news_sentiment else None,
    }

    # Build price provider from env vars
    try:
        from price_provider import get_price_provider
        provider = get_price_provider()
    except EnvironmentError as exc:
        result.status = "error"
        result.error = str(exc)
        return result

    # Auto-init Finnhub client if sentiment is enabled
    global _finnhub_client, _sentiment_cache
    if config.enable_news_sentiment:
        from finnhub_client import FinnhubClient, SentimentDiskCache
        if _sentiment_cache is None:
            _sentiment_cache = SentimentDiskCache()
        if _finnhub_client is None:
            finnhub_key = os.getenv("FINNHUB_API_KEY", "").strip()
            if finnhub_key:
                _finnhub_client = FinnhubClient(finnhub_key)
            else:
                logger.info("FINNHUB_API_KEY not set — sentiment will run from cache only")

    # ── 1. Load data ──────────────────────────────────────────────
    if progress_cb:
        progress_cb("Loading price data...")

    # Fetch extra lookback before start_date for signal computation
    fetch_start = (datetime.strptime(config.start_date, "%Y-%m-%d")
                   - timedelta(days=config.lookback_days + 30)).strftime("%Y-%m-%d")

    all_tickers = list(set(config.tickers + [BENCHMARK]))
    universe_data = load_universe_data(all_tickers, fetch_start, progress_cb=progress_cb, provider=provider)

    if len(universe_data) < 3:
        result.status = "error"
        result.error = f"Only loaded {len(universe_data)} tickers — need at least 3"
        return result

    # Separate benchmark
    benchmark_df = universe_data.pop(BENCHMARK, None)

    # Load VIX data for enhanced regime detection
    vix_df = None
    if config.enable_regime_filter:
        if progress_cb:
            progress_cb("Loading VIX data...")
        vix_df = load_vix_data(fetch_start)

    # ── 2. Generate rebalance dates ───────────────────────────────
    # Use the union of all trading dates
    all_dates = sorted(set().union(*(df.index for df in universe_data.values())))
    trading_dates = pd.DatetimeIndex(all_dates)

    bt_start = pd.Timestamp(config.start_date)
    bt_end = pd.Timestamp(config.end_date)

    rebalance_dates = generate_rebalance_dates(
        bt_start, bt_end, config.rebalance_freq, trading_dates,
    )

    if len(rebalance_dates) < 2:
        result.status = "error"
        result.error = "Not enough rebalance dates in range"
        return result

    logger.info("Backtest: %d tickers, %d rebalance dates, %s to %s",
                len(universe_data), len(rebalance_dates),
                rebalance_dates[0].date(), rebalance_dates[-1].date())

    # ── 3. Walk through rebalance periods ─────────────────────────
    all_trades: list[TradeRecord] = []
    all_daily_pnl = pd.Series(dtype=float)
    capital = config.initial_capital
    calibrated_weights = None
    ic_history_log = {}

    # IC calibration: compute trailing ICs from pre-start history if available
    if config.enable_ic_calibration and len(rebalance_dates) > config.ic_trailing_periods:
        if progress_cb:
            progress_cb("Calibrating signal weights from historical IC...")
        # Use early rebalance dates as training data for initial calibration
        ic_history = compute_signal_ic(
            universe_data, rebalance_dates[:config.ic_trailing_periods],
            config.lookback_days, forward_days=21,
        )
        calibrated_weights = calibrate_weights_from_ic(
            ic_history, config.ic_trailing_periods, config.ic_shrinkage,
        )
        ic_history_log = {name: round(float(np.mean(ics)), 4) if ics else 0.0
                          for name, ics in ic_history.items()}
        logger.info("IC-calibrated weights: %s (mean ICs: %s)", calibrated_weights, ic_history_log)

    for i, reb_date in enumerate(rebalance_dates[:-1]):
        next_reb = rebalance_dates[i + 1]

        if progress_cb:
            progress_cb(f"Rebalancing {reb_date.date()} ({i+1}/{len(rebalance_dates)-1})")

        # Compute signals as of rebalance date
        signals = compute_signals_at_date(universe_data, reb_date, config.lookback_days)
        if not signals:
            continue

        # Apply IC-calibrated weights
        if calibrated_weights:
            signals = apply_calibrated_weights(signals, calibrated_weights)

        # Blend TimesFM 7th signal if enabled (DEPRECATED — prefer LSTM)
        if config.enable_timesfm:
            tfm_scores = compute_timesfm_scores(
                universe_data, reb_date,
                horizon=config.timesfm_horizon,
                lookback=config.timesfm_lookback,
            )
            if tfm_scores:
                signals = blend_timesfm_into_signals(
                    signals, tfm_scores, config.timesfm_weight,
                )

        # Blend LSTM ML signal if enabled and forecaster is provided
        if config.enable_lstm and _lstm_forecaster is not None:
            lstm_scores = compute_lstm_scores(
                universe_data, reb_date, _lstm_forecaster,
            )
            if lstm_scores:
                signals = blend_lstm_into_signals(
                    signals, lstm_scores, config.lstm_weight,
                )

        # Sentiment overlay (after IC + LSTM blends)
        if config.enable_news_sentiment and (_finnhub_client is not None or _sentiment_cache is not None):
            sent_scores = compute_sentiment_scores(
                universe_data, reb_date, config,
                client=_finnhub_client, disk_cache=_sentiment_cache,
            )
            if sent_scores:
                signals = blend_sentiment_into_signals(
                    signals, sent_scores, config.news_sentiment_weight,
                )

        # Detect market regime for short filtering + position sizing
        if config.enable_regime_filter:
            regime = detect_regime(benchmark_df, reb_date, vix_df=vix_df, config=config)
        else:
            regime = RegimeState(level="unknown")

        # Build target portfolio
        positions = build_target_portfolio(
            signals, universe_data, reb_date, config, capital, regime=regime,
        )
        if not positions:
            continue

        # Compute returns for this period
        trades, period_pnl = _compute_daily_portfolio_returns(
            positions, universe_data, reb_date, next_reb, config,
        )

        all_trades.extend(trades)
        if len(period_pnl) > 0:
            all_daily_pnl = pd.concat([all_daily_pnl, period_pnl])

        # Update capital
        period_dollar_pnl = sum(t.pnl_dollar for t in trades)
        capital += period_dollar_pnl

    # ── 4. Compute metrics ────────────────────────────────────────
    if progress_cb:
        progress_cb("Computing metrics...")

    result.trade_log = [vars(t) for t in all_trades]
    result.total_trades = len(all_trades)

    if not all_trades:
        result.status = "complete"
        result.error = "No trades generated — signals may be too weak for thresholds"
        return result

    # Win rate
    wins = sum(1 for t in all_trades if t.pnl_pct > 0)
    result.win_rate_pct = round(wins / len(all_trades) * 100, 1)

    # Average holding period
    result.avg_holding_days = round(
        sum(t.holding_days for t in all_trades) / len(all_trades), 1
    )

    # Equity curve from cumulative daily PnL
    if len(all_daily_pnl) > 0:
        all_daily_pnl = all_daily_pnl.groupby(all_daily_pnl.index).sum().sort_index()
        cumulative = config.initial_capital + all_daily_pnl.cumsum()
        result.equity_curve = [
            {"date": str(d.date()) if hasattr(d, 'date') else str(d),
             "equity": round(float(v), 2)}
            for d, v in cumulative.items()
        ]

        # Total and annual return
        final_equity = float(cumulative.iloc[-1])
        result.total_return_pct = round(
            (final_equity / config.initial_capital - 1) * 100, 2
        )
        n_years = max((cumulative.index[-1] - cumulative.index[0]).days / 365.25, 0.1)
        result.annual_return_pct = round(
            ((final_equity / config.initial_capital) ** (1 / n_years) - 1) * 100, 2
        )

        # Daily returns for Sharpe/Sortino
        daily_returns = all_daily_pnl / config.initial_capital  # approximate
        mean_daily = float(daily_returns.mean())
        std_daily = float(daily_returns.std())

        if std_daily > 0 and len(daily_returns) > 10:
            result.sharpe = round(mean_daily / std_daily * math.sqrt(252), 2)

            downside = daily_returns[daily_returns < 0]
            if len(downside) > 1:
                down_std = float(downside.std())
                if down_std > 0:
                    result.sortino = round(mean_daily / down_std * math.sqrt(252), 2)

        # Max drawdown
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / running_max
        result.max_drawdown_pct = round(abs(float(drawdown.min())) * 100, 2)

        # Calmar
        if result.max_drawdown_pct > 0:
            result.calmar = round(result.annual_return_pct / result.max_drawdown_pct, 2)

    # ── 5. Benchmark comparison ───────────────────────────────────
    if benchmark_df is not None:
        bench = benchmark_df[(benchmark_df.index >= bt_start) & (benchmark_df.index <= bt_end)]
        if len(bench) > 10:
            bench_start_price = float(bench.iloc[0]["close"])
            bench_end_price = float(bench.iloc[-1]["close"])
            result.benchmark_return_pct = round(
                (bench_end_price / bench_start_price - 1) * 100, 2
            )
            result.alpha_pct = round(
                result.total_return_pct - result.benchmark_return_pct, 2
            )

            # Benchmark Sharpe
            bench_returns = bench["close"].pct_change().dropna()
            if len(bench_returns) > 10:
                bench_mean = float(bench_returns.mean())
                bench_std = float(bench_returns.std())
                if bench_std > 0:
                    result.benchmark_sharpe = round(
                        bench_mean / bench_std * math.sqrt(252), 2
                    )

            # Benchmark equity curve
            result.benchmark_curve = [
                {"date": str(d.date()),
                 "equity": round(float(p / bench_start_price * config.initial_capital), 2)}
                for d, p in bench["close"].items()
            ]

    # ── 6. Win rate by conviction band ────────────────────────────
    bands = {
        "low (0.20-0.40)": (0.20, 0.40),
        "medium (0.40-0.60)": (0.40, 0.60),
        "high (0.60-0.80)": (0.60, 0.80),
        "very_high (0.80-1.00)": (0.80, 1.01),
    }
    for band_name, (lo, hi) in bands.items():
        band_trades = [t for t in all_trades if lo <= abs(t.composite_score) < hi]
        if band_trades:
            band_wins = sum(1 for t in band_trades if t.pnl_pct > 0)
            avg_ret = sum(t.pnl_pct for t in band_trades) / len(band_trades)
            result.conviction_bands[band_name] = {
                "n_trades": len(band_trades),
                "win_rate_pct": round(band_wins / len(band_trades) * 100, 1),
                "avg_return_pct": round(avg_ret, 2),
            }

    result.status = "complete"
    return result


# ── Walk-forward validation ────────────────────────────────────────────

def run_walk_forward(
    config: BacktestConfig,
    progress_cb=None,
) -> BacktestResult:
    """
    Walk-forward backtest: train on rolling window, test on next period.

    Splits the date range into overlapping train/test windows:
      - Train: 24 months → compute signal stats (not weight optimization yet)
      - Test: 6 months → run backtest with fixed weights

    Returns combined result with per-window breakdown.
    """
    result = BacktestResult(status="running")

    # Build price provider from env vars
    try:
        from price_provider import get_price_provider
        provider = get_price_provider()
    except EnvironmentError as exc:
        result.status = "error"
        result.error = str(exc)
        return result

    # Auto-init Finnhub client if sentiment is enabled
    global _finnhub_client, _sentiment_cache
    if config.enable_news_sentiment:
        from finnhub_client import FinnhubClient, SentimentDiskCache
        if _sentiment_cache is None:
            _sentiment_cache = SentimentDiskCache()
        if _finnhub_client is None:
            finnhub_key = os.getenv("FINNHUB_API_KEY", "").strip()
            if finnhub_key:
                _finnhub_client = FinnhubClient(finnhub_key)
            else:
                logger.info("FINNHUB_API_KEY not set — sentiment will run from cache only")

    # Load all data once
    if progress_cb:
        progress_cb("Loading price data for walk-forward...")

    fetch_start = (datetime.strptime(config.start_date, "%Y-%m-%d")
                   - timedelta(days=config.lookback_days + 30)).strftime("%Y-%m-%d")

    all_tickers = list(set(config.tickers + [BENCHMARK]))
    universe_data = load_universe_data(all_tickers, fetch_start, progress_cb=progress_cb, provider=provider)

    if len(universe_data) < 3:
        result.status = "error"
        result.error = f"Only loaded {len(universe_data)} tickers"
        return result

    benchmark_df = universe_data.pop(BENCHMARK, None)

    # Load VIX data for enhanced regime detection
    vix_df = None
    if config.enable_regime_filter:
        vix_df = load_vix_data(fetch_start)

    # Generate walk-forward windows
    start = datetime.strptime(config.start_date, "%Y-%m-%d")
    end = datetime.strptime(config.end_date, "%Y-%m-%d")

    windows = []
    cursor = start
    while True:
        train_end = cursor + timedelta(days=config.train_months * 30)
        test_end = train_end + timedelta(days=config.test_months * 30)
        if test_end > end:
            break
        windows.append({
            "train_start": cursor.strftime("%Y-%m-%d"),
            "train_end": train_end.strftime("%Y-%m-%d"),
            "test_start": train_end.strftime("%Y-%m-%d"),
            "test_end": test_end.strftime("%Y-%m-%d"),
        })
        cursor = train_end  # slide forward by test_months

    if not windows:
        result.status = "error"
        result.error = "Date range too short for walk-forward windows"
        return result

    # Run each window
    all_trades = []
    all_daily_pnl = pd.Series(dtype=float)
    capital = config.initial_capital
    window_results = []

    for wi, window in enumerate(windows):
        if progress_cb:
            progress_cb(f"Walk-forward window {wi+1}/{len(windows)}: "
                        f"test {window['test_start']} to {window['test_end']}")

        # Run backtest on test period using the same config
        window_config = BacktestConfig(
            tickers=config.tickers,
            start_date=window["test_start"],
            end_date=window["test_end"],
            rebalance_freq=config.rebalance_freq,
            lookback_days=config.lookback_days,
            long_threshold=config.long_threshold,
            short_threshold=config.short_threshold,
            short_min_bearish_signals=config.short_min_bearish_signals,
            enable_regime_filter=config.enable_regime_filter,
            enable_ic_calibration=config.enable_ic_calibration,
            ic_trailing_periods=config.ic_trailing_periods,
            ic_shrinkage=config.ic_shrinkage,
            max_long_positions=config.max_long_positions,
            max_short_positions=config.max_short_positions,
            transaction_cost_bps=config.transaction_cost_bps,
            execution_delay_days=config.execution_delay_days,
            stop_loss_atr_mult=config.stop_loss_atr_mult,
            initial_capital=capital,
            enable_timesfm=config.enable_timesfm,
            timesfm_weight=config.timesfm_weight,
            timesfm_horizon=config.timesfm_horizon,
            timesfm_lookback=config.timesfm_lookback,
            enable_lstm=config.enable_lstm,
            lstm_weight=config.lstm_weight,
        )

        # Reuse loaded data — compute signals within the window
        all_dates = sorted(set().union(*(df.index for df in universe_data.values())))
        trading_dates = pd.DatetimeIndex(all_dates)
        test_start = pd.Timestamp(window["test_start"])
        test_end_ts = pd.Timestamp(window["test_end"])

        rebalance_dates = generate_rebalance_dates(
            test_start, test_end_ts, config.rebalance_freq, trading_dates,
        )

        # IC calibration: compute ICs from the training window
        calibrated_weights = None
        if config.enable_ic_calibration:
            train_start_ts = pd.Timestamp(window["train_start"])
            train_end_ts = pd.Timestamp(window["train_end"])
            train_dates_all = sorted(set().union(*(df.index for df in universe_data.values())))
            train_trading_dates = pd.DatetimeIndex(train_dates_all)
            train_rebalance_dates = generate_rebalance_dates(
                train_start_ts, train_end_ts, config.rebalance_freq, train_trading_dates,
            )
            if len(train_rebalance_dates) >= config.ic_trailing_periods:
                ic_history = compute_signal_ic(
                    universe_data, train_rebalance_dates,
                    config.lookback_days, forward_days=21,
                )
                calibrated_weights = calibrate_weights_from_ic(
                    ic_history, config.ic_trailing_periods, config.ic_shrinkage,
                )
                logger.info("WF window %d IC weights: %s", wi + 1, calibrated_weights)

        window_trades = []
        window_pnl = pd.Series(dtype=float)

        for i, reb_date in enumerate(rebalance_dates[:-1]):
            next_reb = rebalance_dates[i + 1]
            signals = compute_signals_at_date(universe_data, reb_date, config.lookback_days)
            if not signals:
                continue

            # Apply IC-calibrated weights from training window
            if calibrated_weights:
                signals = apply_calibrated_weights(signals, calibrated_weights)

            # Blend TimesFM if enabled (DEPRECATED — prefer LSTM)
            if config.enable_timesfm:
                tfm_scores = compute_timesfm_scores(
                    universe_data, reb_date,
                    horizon=config.timesfm_horizon,
                    lookback=config.timesfm_lookback,
                )
                if tfm_scores:
                    signals = blend_timesfm_into_signals(
                        signals, tfm_scores, config.timesfm_weight,
                    )

            # Blend LSTM ML signal if enabled
            if config.enable_lstm and _lstm_forecaster is not None:
                lstm_scores = compute_lstm_scores(
                    universe_data, reb_date, _lstm_forecaster,
                )
                if lstm_scores:
                    signals = blend_lstm_into_signals(
                        signals, lstm_scores, config.lstm_weight,
                    )

            # Sentiment overlay (after IC + LSTM blends)
            if config.enable_news_sentiment and (_finnhub_client is not None or _sentiment_cache is not None):
                sent_scores = compute_sentiment_scores(
                    universe_data, reb_date, config,
                    client=_finnhub_client, disk_cache=_sentiment_cache,
                )
                if sent_scores:
                    signals = blend_sentiment_into_signals(
                        signals, sent_scores, config.news_sentiment_weight,
                    )

            if config.enable_regime_filter:
                regime = detect_regime(benchmark_df, reb_date, vix_df=vix_df, config=config)
            else:
                regime = RegimeState(level="unknown")

            positions = build_target_portfolio(
                signals, universe_data, reb_date, window_config, capital, regime=regime,
            )
            if not positions:
                continue
            trades, period_pnl = _compute_daily_portfolio_returns(
                positions, universe_data, reb_date, next_reb, window_config,
            )
            window_trades.extend(trades)
            if len(period_pnl) > 0:
                window_pnl = pd.concat([window_pnl, period_pnl])

        # Summarize window
        window_dollar_pnl = sum(t.pnl_dollar for t in window_trades)
        capital += window_dollar_pnl
        wins = sum(1 for t in window_trades if t.pnl_pct > 0)

        window_summary = {
            **window,
            "n_trades": len(window_trades),
            "win_rate_pct": round(wins / len(window_trades) * 100, 1) if window_trades else 0,
            "return_pct": round(window_dollar_pnl / window_config.initial_capital * 100, 2),
            "ending_capital": round(capital, 2),
        }
        window_results.append(window_summary)
        all_trades.extend(window_trades)
        if len(window_pnl) > 0:
            all_daily_pnl = pd.concat([all_daily_pnl, window_pnl])

    # Aggregate results (reuse the same metric computation)
    result.walk_forward = window_results
    result.trade_log = [vars(t) for t in all_trades]
    result.total_trades = len(all_trades)

    if all_trades:
        wins = sum(1 for t in all_trades if t.pnl_pct > 0)
        result.win_rate_pct = round(wins / len(all_trades) * 100, 1)
        result.avg_holding_days = round(
            sum(t.holding_days for t in all_trades) / len(all_trades), 1
        )

    if len(all_daily_pnl) > 0:
        all_daily_pnl = all_daily_pnl.groupby(all_daily_pnl.index).sum().sort_index()
        cumulative = config.initial_capital + all_daily_pnl.cumsum()
        result.equity_curve = [
            {"date": str(d.date()) if hasattr(d, 'date') else str(d),
             "equity": round(float(v), 2)}
            for d, v in cumulative.items()
        ]

        final_equity = float(cumulative.iloc[-1])
        result.total_return_pct = round(
            (final_equity / config.initial_capital - 1) * 100, 2
        )
        n_years = max((cumulative.index[-1] - cumulative.index[0]).days / 365.25, 0.1)
        result.annual_return_pct = round(
            ((final_equity / config.initial_capital) ** (1 / n_years) - 1) * 100, 2
        )

        daily_returns = all_daily_pnl / config.initial_capital
        mean_daily = float(daily_returns.mean())
        std_daily = float(daily_returns.std())

        if std_daily > 0 and len(daily_returns) > 10:
            result.sharpe = round(mean_daily / std_daily * math.sqrt(252), 2)
            downside = daily_returns[daily_returns < 0]
            if len(downside) > 1:
                down_std = float(downside.std())
                if down_std > 0:
                    result.sortino = round(mean_daily / down_std * math.sqrt(252), 2)

        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / running_max
        result.max_drawdown_pct = round(abs(float(drawdown.min())) * 100, 2)

        if result.max_drawdown_pct > 0:
            result.calmar = round(result.annual_return_pct / result.max_drawdown_pct, 2)

    # Benchmark
    if benchmark_df is not None:
        bt_start = pd.Timestamp(config.start_date)
        bt_end = pd.Timestamp(config.end_date)
        bench = benchmark_df[(benchmark_df.index >= bt_start) & (benchmark_df.index <= bt_end)]
        if len(bench) > 10:
            bench_start_price = float(bench.iloc[0]["close"])
            bench_end_price = float(bench.iloc[-1]["close"])
            result.benchmark_return_pct = round(
                (bench_end_price / bench_start_price - 1) * 100, 2
            )
            result.alpha_pct = round(
                result.total_return_pct - result.benchmark_return_pct, 2
            )

    result.config_summary = {
        "mode": "walk_forward",
        "n_windows": len(windows),
        "train_months": config.train_months,
        "test_months": config.test_months,
        **{k: v for k, v in vars(config).items()
           if k not in ("tickers",)},
        "n_tickers": len(config.tickers),
    }
    result.status = "complete"
    return result
