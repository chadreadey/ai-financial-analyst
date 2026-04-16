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

from quant import metrics
from quant.scoring import reclassify
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
    vix_caution_threshold: float = 28.0       # VIX above this = cautious (P90 of VIX distribution)
    vix_risk_off_threshold: float = 35.0      # VIX above this = risk-off (P95, extreme spikes only)
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
    # FOMC proximity risk premium
    enable_fomc_proximity: bool = False
    fomc_high_vix_boost: float = 0.15     # composite boost when FOMC <= 3 days & VIX > 20
    fomc_low_vix_boost: float = 0.05      # composite boost when FOMC <= 3 days & VIX <= 20
    fomc_proximity_days: int = 3          # trading days before FOMC to activate
    # Fundamental signal overlay (FMP data or WRDS point-in-time)
    enable_fundamentals: bool = False
    fundamentals_weight: float = 0.10     # weight for quality + earnings revision overlay
    fundamental_provider: str = "fmp"     # "fmp" or "wrds" — WRDS uses point-in-time store
    # Earnings signals overlay (WRDS IBES — ERM, SUE, Dispersion)
    enable_earnings_signals: bool = False
    earnings_signal_weight: float = 0.30  # total weight for combined earnings signal
    earnings_rank_mode: bool = False      # Path A: rank by earnings score, technicals filter only
    # Institutional flow signal (FMP + Finnhub 13F ownership data)
    enable_institutional_flow: bool = False
    institutional_flow_weight: float = 0.15  # weight in composite
    # XGBoost meta-model
    enable_xgb_ranker: bool = False
    xgb_train_months: int = 96           # months of history to train on (8 years)
    xgb_retrain_freq: int = 12           # retrain every N rebalance periods
    conviction_sizing: float = 0.0        # 0=equal weight, 1=fully score-proportional sizing
    enable_agent_veto: bool = False       # Path C: quantified agent veto on candidates
    agent_veto_min_flags: int = 2         # minimum veto signals to remove a candidate (2 of 3)
    # Kalshi event prediction signals
    enable_kalshi_signal: bool = False          # Master switch for all Kalshi signals
    kalshi_macro_weight: float = 0.10           # Weight of macro modifier in composite
    kalshi_event_weight: float = 0.20           # Weight of event divergence signal in composite
    kalshi_event_threshold: float = 0.20        # Min divergence to fire event signal (20pp)
    # Sector-diversified selection (wide scan, concentrated picks)
    max_per_sector: int = 3               # max positions from any single GICS sector
    min_score_gap: float = 0.0            # min score above universe median to enter (0 = disabled)

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
        # Normalize index to midnight — guards against cached files with time components
        df.index = df.index.normalize()
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
        df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(None).dt.normalize()
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

    Uses parallel loading (ThreadPoolExecutor) for universes > 10 tickers.
    CSV cache is checked first per ticker, so re-runs are fast.

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

    # Parallel loading for larger universes
    if len(tickers) > 10:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        max_workers = min(10, len(tickers))
        if progress_cb:
            progress_cb(f"Loading {len(tickers)} tickers ({max_workers} parallel workers)...")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_ohlcv, t, start_date, provider): t for t in tickers}
            done = 0
            for future in as_completed(futures):
                ticker = futures[future]
                done += 1
                try:
                    df = future.result()
                    if df is not None:
                        data[ticker] = df
                        logger.info("Loaded %s: %d rows (%s to %s)",
                                    ticker, len(df), df.index[0].date(), df.index[-1].date())
                    else:
                        logger.warning("Skipping %s — no data", ticker)
                except Exception as exc:
                    logger.warning("Failed to load %s: %s", ticker, exc)
                if progress_cb and done % 10 == 0:
                    progress_cb(f"Loaded {done}/{len(tickers)} tickers...")
    else:
        # Sequential for small universes (simpler, good progress feedback)
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

    if progress_cb:
        progress_cb(f"Loaded {len(data)}/{len(tickers)} tickers successfully")
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
    "sma_trend": 0.0, "mean_reversion_z": 0.0,
    "bollinger_pctb": 0.0, "rsi": 0.0, "obv_trend": 1.0,
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
    Only calibrates signals that have non-zero DEFAULT_WEIGHTS (active signals).
    """
    # Only calibrate active signals (non-zero default weight)
    active_signals = [s for s in SIGNAL_NAMES if DEFAULT_WEIGHTS.get(s, 0) > 0]

    if not active_signals:
        return dict(DEFAULT_WEIGHTS)

    raw_ics = {}
    for name in active_signals:
        ics = ic_history.get(name, [])
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

    # IC-proportional weights (only for active signals)
    ic_weights = {name: ic / total_ic for name, ic in raw_ics.items()}

    # Shrink toward equal weights among active signals
    equal_weight = 1.0 / len(active_signals)
    blended = {}
    for name in SIGNAL_NAMES:
        if name in active_signals:
            blended[name] = (1 - shrinkage) * ic_weights.get(name, 0) + shrinkage * equal_weight
        else:
            blended[name] = 0.0  # keep zeroed signals at zero

    # Normalize
    total = sum(blended.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {name: round(w / total, 4) for name, w in blended.items()}


def apply_calibrated_weights(
    signals: dict[str, SignalVector],
    weights: dict[str, float],
) -> dict[str, SignalVector]:
    """Recompute composite scores using calibrated weights instead of defaults."""
    for ticker, sv in signals.items():
        score = (
            sv.sma_trend.score * weights.get("sma_trend", 0.0) +
            sv.mean_reversion_z.score * weights.get("mean_reversion_z", 0.0) +
            sv.bollinger_pctb.score * weights.get("bollinger_pctb", 0.0) +
            sv.rsi.score * weights.get("rsi", 0.0) +
            sv.obv_trend.score * weights.get("obv_trend", 1.0)
        )
        sv.composite_score = float(np.clip(score, -1.0, 1.0))

        reclassify(sv)

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
    turbulence: Optional[float] = None  # Mahalanobis distance (sector decorrelation)
    macro_signal: Optional[object] = None  # MacroRegimeSignal from quant/macro_signals.py


# ── Turbulence Index ─────────────────────────────────────────────────
# Kritzman & Li (2010): Mahalanobis distance of current sector return
# vector vs. historical mean/covariance. Spikes when sectors decorrelate
# (e.g., tech crashes while defensives hold). Catches rotation events
# that VIX misses.

SECTOR_ETFS = ["XLK", "XLV", "XLF", "XLY", "XLP", "XLI", "XLE", "XLB", "XLU", "XLRE", "XLC"]

_sector_etf_data: Optional[dict[str, pd.DataFrame]] = None


def _load_sector_etf_data(start_date: str, provider=None) -> dict[str, pd.DataFrame]:
    """Load sector ETF price data (cached globally for the run)."""
    global _sector_etf_data
    if _sector_etf_data is not None:
        return _sector_etf_data

    data = {}
    for etf in SECTOR_ETFS:
        df = _fetch_ohlcv(etf, start_date, provider)
        if df is not None and len(df) >= 60:
            data[etf] = df
    _sector_etf_data = data
    logger.info("Loaded %d/%d sector ETFs for turbulence index", len(data), len(SECTOR_ETFS))
    return data


def compute_turbulence(
    sector_data: dict[str, pd.DataFrame],
    as_of_date: pd.Timestamp,
    lookback_days: int = 252,
) -> Optional[float]:
    """
    Compute the Kritzman-Li turbulence index as of a date.

    turbulence = (r - mu)' * Sigma_inv * (r - mu)

    where r is today's sector return vector, mu is the historical mean,
    and Sigma is the historical covariance matrix.

    Returns the Mahalanobis distance, or None if insufficient data.
    Typical values: 0-5 normal, 5-15 elevated, >15 turbulent.
    """
    # Build daily return matrix for all available sectors
    returns = {}
    for etf, df in sector_data.items():
        available = df[df.index <= as_of_date]
        if len(available) < lookback_days:
            continue
        window = available["close"].tail(lookback_days)
        daily_ret = window.pct_change().dropna()
        if len(daily_ret) >= lookback_days - 10:
            returns[etf] = daily_ret

    if len(returns) < 5:  # need at least 5 sectors for meaningful covariance
        return None

    # Align all return series to common dates
    ret_df = pd.DataFrame(returns).dropna()
    if len(ret_df) < 60:
        return None

    # Current day's return vector (last row)
    r_today = ret_df.iloc[-1].values

    # Historical mean and covariance (excluding the last day)
    hist = ret_df.iloc[:-1]
    mu = hist.mean().values
    cov = hist.cov().values

    try:
        cov_inv = np.linalg.inv(cov)
    except np.linalg.LinAlgError:
        return None

    diff = r_today - mu
    turbulence = float(diff @ cov_inv @ diff)
    return round(turbulence, 2)


def detect_regime(
    benchmark_df: Optional[pd.DataFrame],
    as_of_date: pd.Timestamp,
    vix_df: Optional[pd.DataFrame] = None,
    config: Optional[BacktestConfig] = None,
    sector_data: Optional[dict[str, pd.DataFrame]] = None,
    hy_oas_series: Optional[pd.Series] = None,
    t10y3m_series: Optional[pd.Series] = None,
) -> RegimeState:
    """
    Multi-factor regime detection: VIX + SPY SMA + death/golden cross + turbulence + macro.

    Regime hierarchy (strongest signal wins):
      risk_off   — VIX > risk_off_threshold OR death cross + bearish SMA OR turbulence > 30
                   OR macro recession_score >= 0.50
      bearish    — SPY below 200d SMA (or death cross active)
      cautious   — VIX > caution_threshold OR turbulence > 18 OR macro recession elevated
      bullish    — SPY above 200d SMA
      strong_bull — golden cross active + SPY above 200d SMA + low VIX + low turbulence
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

    # Turbulence index (sector decorrelation)
    if sector_data:
        turb = compute_turbulence(sector_data, as_of_date)
        state.turbulence = turb

    # Determine regime level (hierarchy: risk_off > bearish > cautious > bullish > strong_bull)
    vix_threshold_caution = config.vix_caution_threshold if config else 20.0
    vix_threshold_risk_off = config.vix_risk_off_threshold if config else 28.0

    # Turbulence thresholds — recalibrated from 2014-2026 empirical distribution
    # P90=19, P95=28, P99=54. Forward returns are positive below turb=35.
    turb_risk_off = 45.0   # P99 — true crisis only (COVID, etc.)
    turb_cautious = 30.0   # P95 — only extreme stress, not normal volatility

    if state.vix is not None and state.vix >= vix_threshold_risk_off:
        state.level = "risk_off"
        state.sizing_scalar = 0.25
    elif state.turbulence is not None and state.turbulence >= turb_risk_off:
        state.level = "risk_off"
        state.sizing_scalar = 0.25
        logger.info("Turbulence risk-off: %.1f (threshold %.1f)", state.turbulence, turb_risk_off)
    elif state.sma_cross == "death_cross" and state.spy_vs_sma200 == "below":
        state.level = "risk_off"
        state.sizing_scalar = 0.25
    elif state.spy_vs_sma200 == "below":
        state.level = "bearish"
        state.sizing_scalar = 0.50
    elif state.vix is not None and state.vix >= vix_threshold_caution:
        state.level = "cautious"
        state.sizing_scalar = 0.70
    elif state.turbulence is not None and state.turbulence >= turb_cautious:
        state.level = "cautious"
        state.sizing_scalar = 0.70
        logger.info("Turbulence cautious: %.1f (threshold %.1f)", state.turbulence, turb_cautious)
    elif state.sma_cross == "golden_cross":
        # Strong bull requires low turbulence too
        if state.turbulence is not None and state.turbulence >= turb_cautious:
            state.level = "bullish"  # downgrade from strong_bull
            state.sizing_scalar = 1.0
        else:
            state.level = "strong_bull"
            state.sizing_scalar = 1.0
    elif state.spy_vs_sma200 == "above":
        state.level = "bullish"
        state.sizing_scalar = 1.0
    else:
        state.level = "unknown"

    # Macro regime overlay (HY OAS + yield curve + recession score)
    if hy_oas_series is not None or t10y3m_series is not None:
        try:
            from quant.macro_signals import compute_macro_regime
            macro = compute_macro_regime(hy_oas_series, t10y3m_series, as_of_date, state.vix)
            state.macro_signal = macro

            # Macro can override to more cautious levels (never less cautious)
            if macro.regime_multiplier < state.sizing_scalar:
                logger.info("Macro override: %s → sizing %.2f (recession=%.0f%%, hy=%s)",
                            macro.regime_label, macro.regime_multiplier,
                            macro.recession_score * 100, macro.hy_oas_regime)
                state.sizing_scalar = macro.regime_multiplier
                if macro.regime_label == "risk_off" and state.level not in ("risk_off",):
                    state.level = "risk_off"
                elif macro.regime_label == "cautious" and state.level in ("bullish", "strong_bull"):
                    state.level = "cautious"
        except Exception as e:
            logger.debug("Macro regime computation failed: %s", e)

    return state


# ── FOMC Proximity Risk Premium ──────────────────────────────────────

# All scheduled FOMC announcement dates 2020-2027
# Source: federalreserve.gov/monetarypolicy/fomccalendars.htm
FOMC_DATES = [
    # 2020
    "2020-01-29", "2020-03-03", "2020-03-15", "2020-04-29", "2020-06-10",
    "2020-07-29", "2020-09-16", "2020-11-05", "2020-12-16",
    # 2021
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
    "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    # 2022
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    # 2023
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-17",
    # 2026
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-16",
    # 2027
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-16",
    "2027-07-28", "2027-09-22", "2027-10-27", "2027-12-15",
]
_FOMC_TIMESTAMPS = sorted(pd.Timestamp(d) for d in FOMC_DATES)


def compute_fomc_proximity_boost(
    as_of_date: pd.Timestamp,
    trading_dates: pd.DatetimeIndex,
    vix_level: Optional[float],
    config: "BacktestConfig",
) -> float:
    """
    Compute FOMC proximity boost for composite scores.

    Returns a boost value (0.0 to 0.15) based on:
    - Trading days until next FOMC announcement
    - Current VIX level (higher VIX = stronger drift)

    Based on Lucca-Moench (2015): 49bps avg pre-FOMC drift in 24hrs,
    conditional on monetary policy uncertainty (proxied by VIX > 20).
    """
    # Find next FOMC date on or after as_of_date
    next_fomc = None
    for fomc_date in _FOMC_TIMESTAMPS:
        if fomc_date >= as_of_date:
            next_fomc = fomc_date
            break

    if next_fomc is None:
        return 0.0

    # Count trading days between as_of_date and next FOMC
    mask = (trading_dates > as_of_date) & (trading_dates <= next_fomc)
    trading_days_to_fomc = int(mask.sum())

    if trading_days_to_fomc > config.fomc_proximity_days:
        return 0.0

    # VIX-conditional boost: stronger when uncertainty is high
    if vix_level is not None and vix_level > 20.0:
        return config.fomc_high_vix_boost
    else:
        return config.fomc_low_vix_boost


def apply_fomc_boost(
    signals: dict[str, "SignalVector"],
    boost: float,
) -> dict[str, "SignalVector"]:
    """Apply FOMC proximity boost to all composite scores (long bias)."""
    if boost <= 0.0:
        return signals

    for ticker, sv in signals.items():
        sv.composite_score = float(np.clip(sv.composite_score + boost, -1.0, 1.0))
        # Recompute direction after boost
        reclassify(sv)
        sv.flags.append(f"fomc_boost={boost:.3f}")

    return signals


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
_fmp_client = None       # FMPClient — auto-initialized from FMP_API_KEY
_fmp_cache = None        # FMPFundamentalCache — SQLite cache for fundamentals
_wrds_provider = None    # WRDSFundamentalProvider — auto-initialized from .wrds_pit.db
_inst_fmp_cache = None  # FMPFundamentalCache for institutional data
_inst_wrds_store = None  # WRDSPointInTimeStore for 13F holdings


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
        reclassify(sv)

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

        reclassify(sv)

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

    Scores are cross-sectionally z-score normalized across the universe before
    returning. This removes the structural bullish bias in financial news (VADER
    on headlines skews positive for nearly all stocks) so what's blended is
    *relative* sentiment — a stock with better-than-average news vs one with
    worse-than-average — rather than an absolute level that inflates all scores.

    Normalization: z = (raw - universe_mean) / universe_std, scaled to [-1, +1]
    via tanh(z) so extreme outliers are capped smoothly. Only tickers with
    sufficient coverage (n_articles >= min_articles) participate in the
    normalization pool; insider-only tickers are normalized separately.
    """
    from quant.sentiment import compute_news_sentiment_score, compute_insider_sentiment_score

    raw_scores: dict[str, tuple[float, int]] = {}
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

        raw_scores[ticker] = (float(np.clip(combined, -1.0, 1.0)), n_articles)

    if not raw_scores:
        return raw_scores

    # Cross-sectional z-score normalization — remove universe-wide bullish bias
    # Only news-covered tickers drive the mean/std (insider-only are sparse noise)
    news_vals = [s for s, n in raw_scores.values() if n >= config.news_sentiment_min_articles]
    if len(news_vals) >= 3:
        mean_s = float(np.mean(news_vals))
        std_s = float(np.std(news_vals))
        if std_s < 1e-6:
            std_s = 1e-6
        normalized: dict[str, tuple[float, int]] = {}
        for ticker, (score, n_articles) in raw_scores.items():
            if n_articles >= config.news_sentiment_min_articles:
                z = (score - mean_s) / std_s
                # tanh maps z-score smoothly to (-1, +1); scale=0.5 keeps it conservative
                norm_score = float(np.tanh(z * 0.5))
            else:
                # Insider-only: pass through unmodified (MSPR is already relative)
                norm_score = score
            normalized[ticker] = (norm_score, n_articles)
        return normalized

    # Not enough covered tickers to normalize — return raw (rare case)
    return raw_scores


_SENTIMENT_COVERAGE_FULL = 20   # articles/month for full weight
_SENTIMENT_HIGH_VOL_SCALE = 0.5  # halve weight during high-vol regime


def blend_sentiment_into_signals(
    signals: dict[str, SignalVector],
    sentiment_scores: dict[str, tuple[float, int]],
    sentiment_weight: float = 0.10,
) -> dict[str, SignalVector]:
    """
    Set sentiment scores on SignalVectors for cross-sectional normalization.

    Applies coverage and regime scaling to the raw sentiment score, then
    stores on sv.sentiment_score. No longer modifies composite_score.
    """
    if not sentiment_scores:
        return signals

    for ticker, sv in signals.items():
        entry = sentiment_scores.get(ticker)
        if entry is None:
            continue

        score, n_articles = entry

        # Coverage scaling: sparse news → reduced confidence
        coverage_scale = min(1.0, n_articles / _SENTIMENT_COVERAGE_FULL)

        # Regime scaling: noisy in high-vol environments
        vol_regime = sv.atr_regime.metadata.get("volatility_regime", "normal")
        regime_scale = _SENTIMENT_HIGH_VOL_SCALE if vol_regime == "high_vol" else 1.0

        effective_scale = coverage_scale * regime_scale

        if effective_scale < 1e-6:
            sv.flags.append(
                f"sentiment_suppressed(articles={n_articles},regime={vol_regime})"
            )
            continue

        # Scale the raw sentiment score by coverage/regime confidence
        sv.sentiment_score = score * effective_scale

        sv.flags.append(
            f"sentiment(cov={coverage_scale:.2f},regime={vol_regime})"
        )

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
    """Rank stocks by composite score (or earnings rank score) and build positions."""
    if regime is None:
        regime = RegimeState(level="unknown")

    # Path A earnings ranking: technicals filter (composite >= threshold),
    # but RANKING uses earnings_rank_score for position selection.
    # SMA gate still applies. OBV contributes to composite for filtering.
    if config.earnings_rank_mode:
        # Filter: must pass technical threshold
        eligible = [(t, sv) for t, sv in signals.items()
                    if sv.composite_score >= config.long_threshold
                    and sv.earnings_rank_score != 0.0]  # must have earnings data
        # Rank by earnings score (not composite)
        scored = [(t, sv.earnings_rank_score, sv) for t, sv in eligible]
        scored.sort(key=lambda x: x[1], reverse=True)
        # Also include stocks that pass threshold but lack earnings data,
        # ranked by composite (fallback for coverage gaps)
        no_earnings = [(t, sv.composite_score, sv) for t, sv in signals.items()
                       if sv.composite_score >= config.long_threshold
                       and sv.earnings_rank_score == 0.0]
        no_earnings.sort(key=lambda x: x[1], reverse=True)
        scored = scored + no_earnings
    else:
        # Original: sort by composite score
        scored = [(ticker, sv.composite_score, sv) for ticker, sv in signals.items()]
        scored.sort(key=lambda x: x[1], reverse=True)

    positions = []
    n_stocks = len(scored)
    if n_stocks == 0:
        return positions

    # ── Decile-based portfolio construction ──────────────────────────
    # Instead of absolute thresholds (composite >= 0.20), use relative
    # ranking: long the top decile, short the bottom decile. This
    # generalizes across any universe size and avoids overfitting to
    # threshold values calibrated on a specific stock list.
    #
    # Absolute thresholds still serve as a minimum quality floor —
    # a stock in the top decile with a negative composite score
    # shouldn't be longed just because it's the "least bad."

    # Risk-off: no new longs (close existing at next rebalance)
    if regime.level == "risk_off":
        longs = []
    else:
        # Top decile = top 10% of universe by score
        n_long_candidates = max(1, n_stocks // 10)
        # But don't exceed max_long_positions
        n_long_candidates = min(n_long_candidates, config.max_long_positions)

        # Quality floor: still require positive composite score
        # (weaker than old 0.20 threshold, but prevents longing negative-signal stocks)
        _QUALITY_FLOOR = 0.05
        longs_raw = [(t, sc, sv) for t, sc, sv in scored[:n_long_candidates]
                     if sc >= _QUALITY_FLOOR
]  # earnings_blocked disabled — Finnhub calendar data sparse in backtest

        # Sector-diversified selection: cap positions per GICS sector
        if config.max_per_sector > 0 and config.max_per_sector < config.max_long_positions:
            from quant.universe import get_sector
            longs = []
            sector_counts: dict[str, int] = {}
            for t, sc, sv in longs_raw:
                sector = get_sector(t)
                count = sector_counts.get(sector, 0)
                if count >= config.max_per_sector:
                    logger.debug("Sector cap: skipping %s (%s, %d/%d)",
                                 t, sector, count, config.max_per_sector)
                    continue
                longs.append((t, sc, sv))
                sector_counts[sector] = count + 1
                if len(longs) >= config.max_long_positions:
                    break
        else:
            longs = longs_raw[:config.max_long_positions]

    # Short: bottom decile of universe by score
    n_short_candidates = max(1, n_stocks // 10)
    n_short_candidates = min(n_short_candidates, config.max_short_positions)
    # Quality floor for shorts: must have meaningfully negative score
    _SHORT_FLOOR = -0.10
    shorts_raw = [(t, sc, sv) for t, sc, sv in scored[-n_short_candidates:]
                  if sc <= _SHORT_FLOOR]
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

    # Agent veto: remove candidates that fail fundamental risk checks
    if config.enable_agent_veto and _wrds_provider is not None and longs:
        from quant.agent_veto import apply_agent_veto
        longs, _veto_log = apply_agent_veto(
            longs, _wrds_provider,
            as_of_date=as_of_date.date() if hasattr(as_of_date, 'date') else as_of_date,
            min_flags=config.agent_veto_min_flags,
        )

    # Position sizing: equal-weight or conviction-weighted
    n_positions = len(longs) + len(shorts)
    if n_positions == 0:
        return positions

    # Conviction-weighted sizing: allocate capital proportional to score
    # conviction_sizing in [0, 1]: 0 = equal weight, 1 = fully score-proportional
    conviction = getattr(config, "conviction_sizing", 0.0)

    if conviction > 0 and longs and len(longs) > 1:
        # Rank-based conviction weighting:
        # Longs are already sorted best-first (by composite or earnings rank).
        # Assign rank weights: rank 1 gets the most, rank N gets the least.
        # Weight formula: w_i = (N - rank_i + 1)^conviction_exponent
        # conviction=0.5 → sqrt weighting (mild), conviction=1.0 → linear (moderate),
        # conviction=2.0 → quadratic (aggressive)
        n = len(longs)
        rank_weights = []
        for i in range(n):
            rank_score = (n - i) / n  # 1.0 for best, 1/n for worst
            rank_weights.append(rank_score ** max(conviction, 0.1))

        total_rw = sum(rank_weights)
        # Blend: (1-conviction)*equal + conviction*rank
        equal_w = 1.0 / n
        long_weights = []
        blend_factor = min(conviction, 1.0)  # cap blend at 1.0
        for rw in rank_weights:
            w = (1.0 - blend_factor) * equal_w + blend_factor * (rw / total_rw)
            long_weights.append(w)

        total_w = sum(long_weights)
        long_weights = [w / total_w for w in long_weights]
    else:
        long_weights = [1.0 / max(len(longs), 1)] * len(longs)

    # Capital pools: 130/30 structure — independent long and short books.
    # Longs invest 100% of capital. Shorts are a 30% overlay (funded by margin).
    # Gross exposure: 130%, Net exposure: ~70%, Target beta: ~0.5-0.7.
    long_capital = capital  # 100% of capital to longs
    short_capital_pool = capital * 0.30  # 30% overlay for shorts

    # Apply regime-based sizing scalar
    regime_scalar = regime.sizing_scalar

    for i, (ticker, score, sv) in enumerate(longs):
        df = universe_data[ticker]
        # Execution delay: use price 1 day after signal
        future = df[df.index > as_of_date]
        if len(future) < config.execution_delay_days:
            continue
        entry_row = future.iloc[config.execution_delay_days - 1]
        entry_price = float(entry_row["close"])
        if entry_price <= 0:
            continue

        # Position capital: conviction-weighted share of the long pool
        per_position_capital = long_capital * long_weights[i]

        # ATR-based position sizing: reduce size in high-vol regimes
        atr_pct = sv.atr_regime.metadata.get("atr_pct", 1.5)
        vol_scalar = min(2.0 / max(atr_pct, 0.5), 2.0)  # TODO: replace with dynamic ATR scaling
        adjusted_capital = per_position_capital * vol_scalar * regime_scalar
        shares = adjusted_capital / entry_price

        # Stop loss: widen multiplier in high-vol regime so normal daily
        # swings don't trigger exits — standard risk management practice.
        atr_val = sv.atr_regime.metadata.get("atr_value", entry_price * 0.02)
        vol_regime = sv.atr_regime.metadata.get("volatility_regime", "normal")
        effective_atr_mult = config.stop_loss_atr_mult * (1.5 if vol_regime == "high_vol" else 1.0)
        stop_price = entry_price - effective_atr_mult * atr_val

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
        vol_scalar = min(2.0 / max(atr_pct, 0.5), 2.0)  # TODO: replace with dynamic ATR scaling
        # In bearish regime, shorts get full sizing (not scaled down)
        short_regime_scalar = 1.0 if regime.level == "bearish" else regime_scalar
        per_short_capital = short_capital_pool / max(len(shorts), 1)  # equal-weight from 30% pool
        adjusted_capital = per_short_capital * vol_scalar * short_regime_scalar
        shares = adjusted_capital / entry_price

        atr_val = sv.atr_regime.metadata.get("atr_value", entry_price * 0.02)
        vol_regime = sv.atr_regime.metadata.get("volatility_regime", "normal")
        effective_atr_mult = config.stop_loss_atr_mult * (1.5 if vol_regime == "high_vol" else 1.0)
        stop_price = entry_price + effective_atr_mult * atr_val

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
        "enable_fomc_proximity": config.enable_fomc_proximity,
        "fomc_high_vix_boost": config.fomc_high_vix_boost if config.enable_fomc_proximity else None,
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
    hy_oas_series = None
    t10y3m_series = None
    if config.enable_regime_filter:
        if progress_cb:
            progress_cb("Loading VIX data...")
        vix_df = load_vix_data(fetch_start)
        # Load sector ETFs for turbulence index
        if progress_cb:
            progress_cb("Loading sector ETFs for turbulence index...")
        _load_sector_etf_data(fetch_start, provider)
        # Load FRED macro data for credit spread + yield curve regime signals
        try:
            from quant.macro_signals import load_fred_macro_data
            hy_oas_series, t10y3m_series = load_fred_macro_data(fetch_start)
        except Exception as e:
            logger.warning("FRED macro data load failed (continuing without): %s", e)

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

        # Fundamental overlay (quality + earnings revisions)
        if config.enable_fundamentals and (_fmp_client is not None or _fmp_cache is not None or _wrds_provider is not None):
            from quant.fundamentals import compute_fundamental_scores, blend_fundamentals_into_signals
            fund_scores = compute_fundamental_scores(
                list(signals.keys()),
                fmp_client=_fmp_client, fmp_cache=_fmp_cache,
                wrds_provider=_wrds_provider,
                as_of_date=reb_date.date() if _wrds_provider else None,
            )
            if fund_scores:
                signals = blend_fundamentals_into_signals(signals, fund_scores, config.fundamentals_weight)

        # Earnings signals overlay (ERM + SUE + Dispersion from WRDS IBES)
        if config.enable_earnings_signals and _wrds_provider is not None:
            from quant.earnings_signals import compute_earnings_signal_scores, blend_earnings_signals
            earn_scores = compute_earnings_signal_scores(
                list(signals.keys()), _wrds_provider,
                as_of_date=reb_date.date(),
            )
            if earn_scores:
                signals = blend_earnings_signals(signals, earn_scores, config.earnings_signal_weight)

        # Institutional flow overlay (FMP + Finnhub 13F ownership)
        if config.enable_institutional_flow:
            from quant.institutional_flow import compute_institutional_flow_scores, blend_institutional_flow
            inst_scores = compute_institutional_flow_scores(
                list(signals.keys()),
                as_of_date=reb_date.date(),
                wrds_store=_inst_wrds_store,
                fmp_client=_fmp_client,
                fmp_cache=_inst_fmp_cache,
                finnhub_client=_finnhub_client,
                finnhub_disk_cache=_sentiment_cache,
            )
            if inst_scores:
                signals = blend_institutional_flow(signals, inst_scores, config.institutional_flow_weight)

        # Sector momentum (sets sector_momentum_score from sector ETF returns)
        if _sector_etf_data:
            from quant.sector_momentum import compute_sector_momentum_scores
            from quant.universe import get_sector
            sec_mom_scores = compute_sector_momentum_scores(
                _sector_etf_data, signals, reb_date, get_sector,
            )
            for ticker, mom_score in sec_mom_scores.items():
                if ticker in signals:
                    signals[ticker].sector_momentum_score = mom_score

        # Quality / Profitability (sets quality_score from WRDS Compustat)
        if _wrds_provider is not None:
            from quant.additional_signals import compute_quality_scores
            quality_scores = compute_quality_scores(
                list(signals.keys()), _wrds_provider, as_of_date=reb_date.date(),
            )
            for ticker, qscore in quality_scores.items():
                if ticker in signals:
                    signals[ticker].quality_score = qscore

        # Price Momentum 12-1M (sets price_momentum_score from price cache)
        from quant.additional_signals import compute_price_momentum_scores
        mom_scores = compute_price_momentum_scores(universe_data, reb_date)
        for ticker, mscore in mom_scores.items():
            if ticker in signals:
                signals[ticker].price_momentum_score = mscore

        # Insider Activity (sets insider_score from Finnhub MSPR)
        if _finnhub_client is not None or _sentiment_cache is not None:
            from quant.additional_signals import compute_insider_scores
            insider_scores = compute_insider_scores(
                list(signals.keys()), reb_date,
                finnhub_client=_finnhub_client,
                sentiment_cache=_sentiment_cache,
            )
            for ticker, iscore in insider_scores.items():
                if ticker in signals:
                    signals[ticker].insider_score = iscore

        # Event timing (PEAD from WRDS IBES actuals + consensus)
        if _wrds_provider is not None:
            from quant.event_timing import compute_event_timing_scores
            from quant.wrds_store import WRDSPointInTimeStore
            _evt_store = WRDSPointInTimeStore()
            event_scores = compute_event_timing_scores(
                list(signals.keys()), reb_date,
                wrds_store=_evt_store,
            )
            for ticker, (escore, emeta) in event_scores.items():
                if ticker in signals:
                    signals[ticker].event_timing_score = escore
                    signals[ticker].earnings_blocked = emeta.get("earnings_blocked", False)

        # Kalshi signals (macro modifier + event divergence)
        if config.enable_kalshi_signal:
            try:
                from quant.kalshi_client import KalshiClient
                from quant.kalshi_signal import compute_macro_modifier, compute_event_divergence
                _kalshi_client = KalshiClient()
                _kalshi_macro = compute_macro_modifier(_kalshi_client)
                for _ticker in signals:
                    signals[_ticker].kalshi_macro_score = _kalshi_macro
                    _earn_prob = getattr(signals[_ticker], "earnings_rank_score", 0.0)
                    # Map earnings_rank_score ([-1,1]) to probability space [0,1]
                    _our_prob = (_earn_prob + 1.0) / 2.0
                    signals[_ticker].kalshi_event_score = compute_event_divergence(
                        _kalshi_client,
                        ticker=_ticker,
                        our_prob_beat=_our_prob,
                        threshold=config.kalshi_event_threshold,
                    )
            except Exception as _exc:
                logger.warning("Kalshi signal injection failed: %s", _exc)

        # ── Cross-sectional normalization barrier ──
        # Group by volatility tier (not sector) to preserve sector momentum
        from quant.cross_sectional import normalize_signals_cross_sectionally, compute_normalized_composite, make_volatility_tier_fn
        from quant.scoring import reclassify
        signals = normalize_signals_cross_sectionally(signals, make_volatility_tier_fn(signals))

        # ── XGBoost ranking OR linear composite ──
        _xgb_active = False
        if config.enable_xgb_ranker and hasattr(config, '_xgb_feature_matrix') and config._xgb_feature_matrix is not None:
            from quant.xgb_ranker import XGBMetaModel, FEATURE_COLS
            import pandas as _pd

            # Rolling retrain: retrain every xgb_retrain_freq periods using expanding window
            _needs_retrain = (
                config._xgb_model is None or
                config._xgb_last_train_date is None or
                (reb_date - config._xgb_last_train_date).days > config.xgb_retrain_freq * 30
            )

            if _needs_retrain:
                _fm = config._xgb_feature_matrix
                _fm_train = _fm[_fm["date"] < reb_date]  # strict: no data from current date
                if len(_fm_train) >= 200:
                    _model = XGBMetaModel()
                    _model.fit(_fm_train[FEATURE_COLS], _fm_train["fwd_21d_return"], _fm_train["qid"])
                    config._xgb_model = _model
                    config._xgb_last_train_date = reb_date
                    logger.info("XGB retrained on %d rows (up to %s)", len(_fm_train), reb_date.date())

            if config._xgb_model is not None:
                # Build feature row for each ticker from current signals
                feature_rows = []
                feature_tickers = []
                for ticker, sv in signals.items():
                    feature_rows.append({
                        "obv_trend": sv.obv_trend.score,
                        "earnings": sv.earnings_rank_score,
                        "inst_flow": sv.institutional_flow_score,
                        "sentiment": sv.sentiment_score,
                        "quality": sv.quality_score,
                        "price_mom": sv.price_momentum_score,
                        "insider": sv.insider_score,
                        "event_timing": sv.event_timing_score,
                        "atr_pct": sv.atr_regime.metadata.get("atr_pct", 0.0),
                        "vix_level": float(vix_df[vix_df.index <= reb_date].iloc[-1]["close"]) if vix_df is not None and len(vix_df[vix_df.index <= reb_date]) > 0 else 0.0,
                    })
                    feature_tickers.append(ticker)

                X = _pd.DataFrame(feature_rows, columns=FEATURE_COLS)
                xgb_scores = config._xgb_model.predict(X)

                # Normalize XGB scores to [-1, +1] via rank percentile
                ranks = xgb_scores.argsort().argsort()
                n = len(ranks)
                normalized = (ranks / (n - 1)) * 2.0 - 1.0 if n > 1 else np.zeros(n)

                for i, ticker in enumerate(feature_tickers):
                    signals[ticker].composite_score = float(normalized[i])
                    reclassify(signals[ticker])
                    signals[ticker].flags.append(f"xgb_rank={float(xgb_scores[i]):.3f}")
                _xgb_active = True

        if not _xgb_active:
            for sv in signals.values():
                sv.composite_score = compute_normalized_composite(sv)
                if config.enable_kalshi_signal:
                    sv.composite_score = float(np.clip(
                        sv.composite_score
                        + sv.kalshi_macro_score * config.kalshi_macro_weight
                        + sv.kalshi_event_score * config.kalshi_event_weight,
                        -1.0, 1.0,
                    ))
                reclassify(sv)

        # FOMC proximity risk premium (after all signal blends, before regime)
        if config.enable_fomc_proximity:
            all_dates_flat = sorted(set().union(*(df.index for df in universe_data.values())))
            td_index = pd.DatetimeIndex(all_dates_flat)
            vix_now = None
            if vix_df is not None:
                vix_avail = vix_df[vix_df.index <= reb_date]
                if len(vix_avail) > 0:
                    vix_now = float(vix_avail.iloc[-1]["close"])
            fomc_boost = compute_fomc_proximity_boost(reb_date, td_index, vix_now, config)
            if fomc_boost > 0:
                signals = apply_fomc_boost(signals, fomc_boost)

        # Detect market regime for short filtering + position sizing
        if config.enable_regime_filter:
            regime = detect_regime(benchmark_df, reb_date, vix_df=vix_df, config=config, sector_data=_sector_etf_data, hy_oas_series=hy_oas_series, t10y3m_series=t10y3m_series)
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
        result.annual_return_pct = metrics.compute_annual_return(cumulative, config.initial_capital)

        # Daily returns for Sharpe/Sortino
        daily_returns = all_daily_pnl / config.initial_capital  # approximate
        result.sharpe = metrics.compute_sharpe(daily_returns)
        result.sortino = metrics.compute_sortino(daily_returns)

        # Max drawdown & Calmar
        result.max_drawdown_pct = metrics.compute_max_drawdown(cumulative)
        result.calmar = metrics.compute_calmar(result.annual_return_pct, result.max_drawdown_pct)

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
            result.benchmark_sharpe = metrics.compute_sharpe(bench_returns)

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
    global _finnhub_client, _sentiment_cache, _fmp_client
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

    # Auto-init fundamental data provider (also needed for earnings signals)
    if config.enable_fundamentals or config.enable_earnings_signals:
        global _fmp_cache, _wrds_provider
        if config.fundamental_provider == "wrds" or config.enable_earnings_signals:
            if _wrds_provider is None:
                try:
                    from quant.wrds_store import WRDSPointInTimeStore
                    from quant.fundamental_provider import WRDSFundamentalProvider
                    store = WRDSPointInTimeStore()
                    if store.summary().get("compustat_quarterly", 0) > 0:
                        _wrds_provider = WRDSFundamentalProvider(store)
                        logger.info("WRDS provider initialized: %d compustat, %d IBES rows",
                                    store.summary()["compustat_quarterly"],
                                    store.summary()["ibes_consensus"])
                    else:
                        logger.warning("WRDS store empty — run scripts/seed_wrds.py first")
                except Exception as exc:
                    logger.warning("WRDS provider init failed: %s", exc)
        else:
            if _fmp_cache is None:
                from quant.fmp_cache import FMPFundamentalCache
                _fmp_cache = FMPFundamentalCache()
                cached_count = _fmp_cache.ticker_count()
                if cached_count > 0:
                    logger.info("FMP cache loaded: %d tickers", cached_count)
            if _fmp_client is None:
                fmp_key = os.getenv("FMP_API_KEY", "").strip()
                if fmp_key:
                    from fmp_client import FMPClient
                    _fmp_client = FMPClient(fmp_key)
                    logger.info("FMP client initialized for fundamental signals")
                elif _fmp_cache.ticker_count() == 0:
                    logger.info("FMP_API_KEY not set and cache empty — fundamentals disabled")

    # Auto-init institutional flow data sources + prefetch
    if config.enable_institutional_flow:
        global _inst_fmp_cache, _inst_wrds_store
        if _inst_fmp_cache is None:
            from quant.fmp_cache import FMPFundamentalCache
            _inst_fmp_cache = FMPFundamentalCache()
        if _fmp_client is None:
            fmp_key = os.getenv("FMP_API_KEY", "").strip()
            if fmp_key:
                from fmp_client import FMPClient
                _fmp_client = FMPClient(fmp_key)
        # Use WRDS 13F store as primary source (if seeded)
        if _inst_wrds_store is None and _wrds_provider is not None:
            try:
                from quant.wrds_store import WRDSPointInTimeStore
                _inst_wrds_store = WRDSPointInTimeStore()
                # Quick check if 13F data is seeded
                test = _inst_wrds_store.get_inst_holdings_as_of(config.tickers[0], "2099-12-31", n_quarters=1)
                if test:
                    logger.info("WRDS 13F store available (%d test rows for %s)", len(test), config.tickers[0])
                else:
                    logger.info("WRDS 13F store empty — run: python scripts/seed_wrds.py --universe liquid_50")
                    _inst_wrds_store = None
            except Exception as exc:
                logger.debug("WRDS 13F store init failed: %s", exc)
                _inst_wrds_store = None
        # Prefetch all institutional data once before the backtest loop
        from quant.institutional_flow import prefetch_institutional_data
        prefetch_stats = prefetch_institutional_data(
            config.tickers,
            wrds_store=_inst_wrds_store,
            fmp_client=_fmp_client,
            fmp_cache=_inst_fmp_cache,
            finnhub_client=_finnhub_client,
            finnhub_disk_cache=_sentiment_cache,
        )
        logger.info("Institutional flow prefetch: %d/%d tickers with data",
                     len(prefetch_stats), len(config.tickers))

    # XGBoost: load feature matrix for rolling retraining during walk-forward
    if config.enable_xgb_ranker:
        import os as _os
        _fm_path = None
        for _try_path in [f".xgb_features_liquid_{len(config.tickers)}.csv", ".xgb_features.csv"]:
            if _os.path.exists(_try_path):
                _fm_path = _try_path
                break
        if _fm_path:
            from quant.xgb_features import load_feature_matrix
            config._xgb_feature_matrix = load_feature_matrix(_fm_path)
            config._xgb_feature_matrix["date"] = pd.to_datetime(config._xgb_feature_matrix["date"])
            config._xgb_model = None  # trained per-window below
            config._xgb_last_train_date = None
            logger.info("XGB feature matrix loaded: %d rows for rolling retraining", len(config._xgb_feature_matrix))
        else:
            logger.warning("XGB: no feature matrix found — run scripts/run_xgb_test.py --rebuild-features first")
            config._xgb_feature_matrix = None
            config._xgb_model = None

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

    # Load VIX data and sector ETFs for enhanced regime detection
    vix_df = None
    hy_oas_series = None
    t10y3m_series = None
    if config.enable_regime_filter:
        vix_df = load_vix_data(fetch_start)
        if progress_cb:
            progress_cb("Loading sector ETFs for turbulence index...")
        _load_sector_etf_data(fetch_start, provider)
        # Load FRED macro data for credit spread + yield curve regime signals
        try:
            from quant.macro_signals import load_fred_macro_data
            hy_oas_series, t10y3m_series = load_fred_macro_data(fetch_start)
            if hy_oas_series is not None and progress_cb:
                progress_cb(f"FRED macro data loaded: HY OAS ({len(hy_oas_series)} obs), T10Y3M ({len(t10y3m_series) if t10y3m_series is not None else 0} obs)")
        except Exception as e:
            logger.warning("FRED macro data load failed (continuing without): %s", e)

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
        cursor += timedelta(days=config.test_months * 30)  # slide forward by test_months (rolling windows)

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
            enable_fomc_proximity=config.enable_fomc_proximity,
            fomc_high_vix_boost=config.fomc_high_vix_boost,
            fomc_low_vix_boost=config.fomc_low_vix_boost,
            fomc_proximity_days=config.fomc_proximity_days,
            max_per_sector=config.max_per_sector,
            enable_fundamentals=config.enable_fundamentals,
            fundamentals_weight=config.fundamentals_weight,
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
                active_w = {k: v for k, v in calibrated_weights.items() if v > 0}
                logger.info("WF window %d IC weights: %s", wi + 1, active_w)

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

            # Fundamental overlay (quality + earnings revisions)
            if config.enable_fundamentals and (_fmp_client is not None or _fmp_cache is not None or _wrds_provider is not None):
                from quant.fundamentals import compute_fundamental_scores, blend_fundamentals_into_signals
                fund_scores = compute_fundamental_scores(
                    list(signals.keys()),
                    fmp_client=_fmp_client, fmp_cache=_fmp_cache,
                    wrds_provider=_wrds_provider,
                    as_of_date=reb_date.date() if _wrds_provider else None,
                )
                if fund_scores:
                    signals = blend_fundamentals_into_signals(signals, fund_scores, config.fundamentals_weight)

            # Earnings signals overlay (ERM + SUE + Dispersion from WRDS IBES)
            if config.enable_earnings_signals and _wrds_provider is not None:
                from quant.earnings_signals import compute_earnings_signal_scores, blend_earnings_signals
                earn_scores = compute_earnings_signal_scores(
                    list(signals.keys()), _wrds_provider,
                    as_of_date=reb_date.date(),
                )
                if earn_scores:
                    signals = blend_earnings_signals(signals, earn_scores, config.earnings_signal_weight)

            # Institutional flow overlay (FMP + Finnhub 13F ownership)
            if config.enable_institutional_flow:
                from quant.institutional_flow import compute_institutional_flow_scores, blend_institutional_flow
                inst_scores = compute_institutional_flow_scores(
                    list(signals.keys()),
                    as_of_date=reb_date.date(),
                    fmp_client=_fmp_client,
                    fmp_cache=_inst_fmp_cache,
                    finnhub_client=_finnhub_client,
                    finnhub_disk_cache=_sentiment_cache,
                )
                if inst_scores:
                    signals = blend_institutional_flow(signals, inst_scores, config.institutional_flow_weight)

            # Sector momentum
            if _sector_etf_data:
                from quant.sector_momentum import compute_sector_momentum_scores
                from quant.universe import get_sector
                sec_mom_scores = compute_sector_momentum_scores(
                    _sector_etf_data, signals, reb_date, get_sector,
                )
                for ticker, mom_score in sec_mom_scores.items():
                    if ticker in signals:
                        signals[ticker].sector_momentum_score = mom_score

            # Quality / Profitability
            if _wrds_provider is not None:
                from quant.additional_signals import compute_quality_scores
                quality_scores = compute_quality_scores(
                    list(signals.keys()), _wrds_provider, as_of_date=reb_date.date(),
                )
                for ticker, qscore in quality_scores.items():
                    if ticker in signals:
                        signals[ticker].quality_score = qscore

            # Price Momentum 12-1M
            from quant.additional_signals import compute_price_momentum_scores
            mom_scores = compute_price_momentum_scores(universe_data, reb_date)
            for ticker, mscore in mom_scores.items():
                if ticker in signals:
                    signals[ticker].price_momentum_score = mscore

            # Insider Activity
            if _finnhub_client is not None or _sentiment_cache is not None:
                from quant.additional_signals import compute_insider_scores
                insider_scores = compute_insider_scores(
                    list(signals.keys()), reb_date,
                    finnhub_client=_finnhub_client,
                    sentiment_cache=_sentiment_cache,
                )
                for ticker, iscore in insider_scores.items():
                    if ticker in signals:
                        signals[ticker].insider_score = iscore

            # Event timing (PEAD from WRDS IBES)
            if _wrds_provider is not None:
                from quant.event_timing import compute_event_timing_scores
                from quant.wrds_store import WRDSPointInTimeStore
                _evt_store = WRDSPointInTimeStore()
                event_scores = compute_event_timing_scores(
                    list(signals.keys()), reb_date,
                    wrds_store=_evt_store,
                )
                for ticker, (escore, emeta) in event_scores.items():
                    if ticker in signals:
                        signals[ticker].event_timing_score = escore
                        signals[ticker].earnings_blocked = emeta.get("earnings_blocked", False)

            # Kalshi signals (macro modifier + event divergence)
            if config.enable_kalshi_signal:
                try:
                    from quant.kalshi_client import KalshiClient
                    from quant.kalshi_signal import compute_macro_modifier, compute_event_divergence
                    _kalshi_client = KalshiClient()
                    _kalshi_macro = compute_macro_modifier(_kalshi_client)
                    for _ticker in signals:
                        signals[_ticker].kalshi_macro_score = _kalshi_macro
                        _earn_prob = getattr(signals[_ticker], "earnings_rank_score", 0.0)
                        # Map earnings_rank_score ([-1,1]) to probability space [0,1]
                        _our_prob = (_earn_prob + 1.0) / 2.0
                        signals[_ticker].kalshi_event_score = compute_event_divergence(
                            _kalshi_client,
                            ticker=_ticker,
                            our_prob_beat=_our_prob,
                            threshold=config.kalshi_event_threshold,
                        )
                except Exception as _exc:
                    logger.warning("Kalshi signal injection failed: %s", _exc)

            # ── Cross-sectional normalization barrier ──
            from quant.cross_sectional import normalize_signals_cross_sectionally, compute_normalized_composite, make_volatility_tier_fn
            from quant.scoring import reclassify
            signals = normalize_signals_cross_sectionally(signals, make_volatility_tier_fn(signals))

            # ── XGBoost ranking OR linear composite ──
            _xgb_active = False
            if config.enable_xgb_ranker and hasattr(config, '_xgb_feature_matrix') and config._xgb_feature_matrix is not None:
                from quant.xgb_ranker import XGBMetaModel, FEATURE_COLS
                import pandas as _pd

                _needs_retrain = (
                    config._xgb_model is None or
                    config._xgb_last_train_date is None or
                    (reb_date - config._xgb_last_train_date).days > config.xgb_retrain_freq * 30
                )
                if _needs_retrain:
                    _fm = config._xgb_feature_matrix
                    _fm_train = _fm[_fm["date"] < reb_date]
                    if len(_fm_train) >= 200:
                        _model = XGBMetaModel()
                        _model.fit(_fm_train[FEATURE_COLS], _fm_train["fwd_21d_return"], _fm_train["qid"])
                        config._xgb_model = _model
                        config._xgb_last_train_date = reb_date
                        logger.info("XGB retrained on %d rows (up to %s)", len(_fm_train), reb_date.date())

                if config._xgb_model is not None:
                    feature_rows = []
                    feature_tickers = []
                    for ticker, sv in signals.items():
                        feature_rows.append({
                            "obv_trend": sv.obv_trend.score,
                            "earnings": sv.earnings_rank_score,
                            "inst_flow": sv.institutional_flow_score,
                            "sentiment": sv.sentiment_score,
                            "quality": sv.quality_score,
                            "price_mom": sv.price_momentum_score,
                            "insider": sv.insider_score,
                            "atr_pct": sv.atr_regime.metadata.get("atr_pct", 0.0),
                            "vix_level": float(vix_df[vix_df.index <= reb_date].iloc[-1]["close"]) if vix_df is not None and len(vix_df[vix_df.index <= reb_date]) > 0 else 0.0,
                        })
                        feature_tickers.append(ticker)

                    X = _pd.DataFrame(feature_rows, columns=FEATURE_COLS)
                    xgb_scores = config._xgb_model.predict(X)

                    ranks = xgb_scores.argsort().argsort()
                    n = len(ranks)
                    normalized = (ranks / (n - 1)) * 2.0 - 1.0 if n > 1 else np.zeros(n)

                    for i, ticker in enumerate(feature_tickers):
                        signals[ticker].composite_score = float(normalized[i])
                        reclassify(signals[ticker])
                        signals[ticker].flags.append(f"xgb_rank={float(xgb_scores[i]):.3f}")
                    _xgb_active = True

            if not _xgb_active:
                for sv in signals.values():
                    sv.composite_score = compute_normalized_composite(sv)
                    if config.enable_kalshi_signal:
                        sv.composite_score = float(np.clip(
                            sv.composite_score
                            + sv.kalshi_macro_score * config.kalshi_macro_weight
                            + sv.kalshi_event_score * config.kalshi_event_weight,
                            -1.0, 1.0,
                        ))
                    reclassify(sv)

            # FOMC proximity risk premium
            if config.enable_fomc_proximity:
                vix_now = None
                if vix_df is not None:
                    vix_avail = vix_df[vix_df.index <= reb_date]
                    if len(vix_avail) > 0:
                        vix_now = float(vix_avail.iloc[-1]["close"])
                fomc_boost = compute_fomc_proximity_boost(reb_date, trading_dates, vix_now, config)
                if fomc_boost > 0:
                    signals = apply_fomc_boost(signals, fomc_boost)

            if config.enable_regime_filter:
                regime = detect_regime(benchmark_df, reb_date, vix_df=vix_df, config=config, sector_data=_sector_etf_data, hy_oas_series=hy_oas_series, t10y3m_series=t10y3m_series)
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
        result.annual_return_pct = metrics.compute_annual_return(cumulative, config.initial_capital)

        daily_returns = all_daily_pnl / config.initial_capital
        result.sharpe = metrics.compute_sharpe(daily_returns)
        result.sortino = metrics.compute_sortino(daily_returns)

        result.max_drawdown_pct = metrics.compute_max_drawdown(cumulative)
        result.calmar = metrics.compute_calmar(result.annual_return_pct, result.max_drawdown_pct)

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


# ── CPCV validation ───────────────────────────────────────────────────

def run_cpcv(
    config: BacktestConfig,
    n_groups: int = 16,
    n_test_groups: int = 0,
    purge_months: int = 1,
    embargo_months: int = 1,
    max_combinations: Optional[int] = None,
    progress_cb=None,
):
    """
    Combinatorial Purged Cross-Validation (Lopez de Prado, 2018).

    Generates C(n_groups, n_test_groups) train/test splits from the full
    date range, applies purge and embargo to prevent leakage, runs the
    backtest on each test split, and computes PBO + Deflated Sharpe Ratio.

    Returns a CPCVResult with the full OOS Sharpe distribution.
    """
    import random
    import time as _time
    from quant.cpcv import (
        make_cpcv_groups, generate_cpcv_combinations, apply_purge_embargo,
        compute_sharpe_from_returns, CPCVResult,
    )

    t0 = _time.time()

    if n_test_groups <= 0:
        n_test_groups = n_groups // 2

    result = CPCVResult(
        n_groups=n_groups,
        n_test_groups=n_test_groups,
        purge_months=purge_months,
        embargo_months=embargo_months,
    )

    # ── 1. Initialize providers (same as run_walk_forward) ──
    try:
        from price_provider import get_price_provider
        provider = get_price_provider()
    except EnvironmentError as exc:
        result.error = str(exc)
        return result

    global _finnhub_client, _sentiment_cache, _fmp_client
    if config.enable_news_sentiment:
        from finnhub_client import FinnhubClient, SentimentDiskCache
        if _sentiment_cache is None:
            _sentiment_cache = SentimentDiskCache()
        if _finnhub_client is None:
            finnhub_key = os.getenv("FINNHUB_API_KEY", "").strip()
            if finnhub_key:
                _finnhub_client = FinnhubClient(finnhub_key)

    if config.enable_fundamentals:
        global _fmp_cache
        if _fmp_cache is None:
            from quant.fmp_cache import FMPFundamentalCache
            _fmp_cache = FMPFundamentalCache()
            cached_count = _fmp_cache.ticker_count()
            if cached_count > 0:
                logger.info("FMP cache loaded: %d tickers", cached_count)
        if _fmp_client is None:
            fmp_key = os.getenv("FMP_API_KEY", "").strip()
            if fmp_key:
                from fmp_client import FMPClient
                _fmp_client = FMPClient(fmp_key)

    # ── 2. Load all data once ──
    if progress_cb:
        progress_cb("Loading price data for CPCV...")

    fetch_start = (datetime.strptime(config.start_date, "%Y-%m-%d")
                   - timedelta(days=config.lookback_days + 30)).strftime("%Y-%m-%d")

    all_tickers = list(set(config.tickers + [BENCHMARK]))
    universe_data = load_universe_data(all_tickers, fetch_start, progress_cb=progress_cb, provider=provider)

    if len(universe_data) < 3:
        result.error = f"Only loaded {len(universe_data)} tickers"
        return result

    benchmark_df = universe_data.pop(BENCHMARK, None)

    vix_df = None
    hy_oas_series = None
    t10y3m_series = None
    if config.enable_regime_filter:
        vix_df = load_vix_data(fetch_start)
        if progress_cb:
            progress_cb("Loading sector ETFs for turbulence index...")
        _load_sector_etf_data(fetch_start, provider)
        try:
            from quant.macro_signals import load_fred_macro_data
            hy_oas_series, t10y3m_series = load_fred_macro_data(fetch_start)
        except Exception as e:
            logger.warning("FRED macro data load failed (continuing without): %s", e)

    # ── 3. Build CPCV groups and combinations ──
    all_dates = sorted(set().union(*(df.index for df in universe_data.values())))
    trading_dates = pd.DatetimeIndex(all_dates)

    groups = make_cpcv_groups(config.start_date, config.end_date, n_groups, trading_dates)

    all_rebalance_dates = generate_rebalance_dates(
        pd.Timestamp(config.start_date), pd.Timestamp(config.end_date),
        config.rebalance_freq, trading_dates,
    )

    combos = generate_cpcv_combinations(n_groups, n_test_groups)
    result.n_combinations = len(combos)

    if max_combinations and max_combinations < len(combos):
        rng = random.Random(42)
        combos = rng.sample(combos, max_combinations)
        result.n_combinations = len(combos)

    if progress_cb:
        progress_cb(f"Running {len(combos)} CPCV combinations "
                    f"({n_groups} groups, {n_test_groups} test)...")

    # ── 4. Run each combination ──
    # SYNC WITH run_walk_forward inner loop (lines 2051-2127)
    for ci, (train_indices, test_indices) in enumerate(combos):
        if progress_cb and (ci % 10 == 0 or ci == len(combos) - 1):
            progress_cb(f"CPCV combination {ci+1}/{len(combos)}")

        safe_train_dates, safe_test_dates = apply_purge_embargo(
            groups, train_indices, test_indices,
            all_rebalance_dates, purge_months, embargo_months,
        )

        if len(safe_test_dates) < 2:
            result.n_combinations_skipped += 1
            continue

        # IC calibration from training dates (if enabled)
        calibrated_weights = None
        if config.enable_ic_calibration and len(safe_train_dates) >= config.ic_trailing_periods:
            ic_history = compute_signal_ic(
                universe_data, safe_train_dates,
                config.lookback_days, forward_days=21,
            )
            calibrated_weights = calibrate_weights_from_ic(
                ic_history, config.ic_trailing_periods, config.ic_shrinkage,
            )

        combo_daily_pnl = pd.Series(dtype=float)
        combo_trades = []

        # Iterate test rebalance dates
        for i, reb_date in enumerate(safe_test_dates[:-1]):
            next_reb = safe_test_dates[i + 1]
            _xgb_active = False
            signals = compute_signals_at_date(universe_data, reb_date, config.lookback_days)
            if not signals:
                continue

            if calibrated_weights:
                signals = apply_calibrated_weights(signals, calibrated_weights)

            if config.enable_timesfm:
                tfm_scores = compute_timesfm_scores(
                    universe_data, reb_date,
                    horizon=config.timesfm_horizon,
                    lookback=config.timesfm_lookback,
                )
                if tfm_scores:
                    signals = blend_timesfm_into_signals(signals, tfm_scores, config.timesfm_weight)

            if config.enable_lstm and _lstm_forecaster is not None:
                lstm_scores = compute_lstm_scores(universe_data, reb_date, _lstm_forecaster)
                if lstm_scores:
                    signals = blend_lstm_into_signals(signals, lstm_scores, config.lstm_weight)

            if config.enable_news_sentiment and (_finnhub_client is not None or _sentiment_cache is not None):
                sent_scores = compute_sentiment_scores(
                    universe_data, reb_date, config,
                    client=_finnhub_client, disk_cache=_sentiment_cache,
                )
                if sent_scores:
                    signals = blend_sentiment_into_signals(signals, sent_scores, config.news_sentiment_weight)

            if config.enable_fundamentals and (_fmp_client is not None or _fmp_cache is not None or _wrds_provider is not None):
                from quant.fundamentals import compute_fundamental_scores, blend_fundamentals_into_signals
                fund_scores = compute_fundamental_scores(
                    list(signals.keys()),
                    fmp_client=_fmp_client, fmp_cache=_fmp_cache,
                    wrds_provider=_wrds_provider,
                    as_of_date=reb_date.date() if _wrds_provider else None,
                )
                if fund_scores:
                    signals = blend_fundamentals_into_signals(signals, fund_scores, config.fundamentals_weight)

            # Earnings signals overlay (ERM + SUE + Dispersion from WRDS IBES)
            if config.enable_earnings_signals and _wrds_provider is not None:
                from quant.earnings_signals import compute_earnings_signal_scores, blend_earnings_signals
                earn_scores = compute_earnings_signal_scores(
                    list(signals.keys()), _wrds_provider,
                    as_of_date=reb_date.date(),
                )
                if earn_scores:
                    signals = blend_earnings_signals(signals, earn_scores, config.earnings_signal_weight)

            # Institutional flow overlay (FMP + Finnhub 13F ownership)
            if config.enable_institutional_flow:
                from quant.institutional_flow import compute_institutional_flow_scores, blend_institutional_flow
                inst_scores = compute_institutional_flow_scores(
                    list(signals.keys()),
                    as_of_date=reb_date.date(),
                    fmp_client=_fmp_client,
                    fmp_cache=_inst_fmp_cache,
                    finnhub_client=_finnhub_client,
                    finnhub_disk_cache=_sentiment_cache,
                )
                if inst_scores:
                    signals = blend_institutional_flow(signals, inst_scores, config.institutional_flow_weight)

            # Sector momentum
            if _sector_etf_data:
                from quant.sector_momentum import compute_sector_momentum_scores
                from quant.universe import get_sector
                sec_mom_scores = compute_sector_momentum_scores(
                    _sector_etf_data, signals, reb_date, get_sector,
                )
                for ticker, mom_score in sec_mom_scores.items():
                    if ticker in signals:
                        signals[ticker].sector_momentum_score = mom_score

            # Quality / Profitability
            if _wrds_provider is not None:
                from quant.additional_signals import compute_quality_scores
                quality_scores = compute_quality_scores(
                    list(signals.keys()), _wrds_provider, as_of_date=reb_date.date(),
                )
                for ticker, qscore in quality_scores.items():
                    if ticker in signals:
                        signals[ticker].quality_score = qscore

            # Price Momentum 12-1M
            from quant.additional_signals import compute_price_momentum_scores
            mom_scores = compute_price_momentum_scores(universe_data, reb_date)
            for ticker, mscore in mom_scores.items():
                if ticker in signals:
                    signals[ticker].price_momentum_score = mscore

            # Insider Activity
            if _finnhub_client is not None or _sentiment_cache is not None:
                from quant.additional_signals import compute_insider_scores
                insider_scores = compute_insider_scores(
                    list(signals.keys()), reb_date,
                    finnhub_client=_finnhub_client,
                    sentiment_cache=_sentiment_cache,
                )
                for ticker, iscore in insider_scores.items():
                    if ticker in signals:
                        signals[ticker].insider_score = iscore

            # Event timing (PEAD from WRDS IBES)
            if _wrds_provider is not None:
                from quant.event_timing import compute_event_timing_scores
                from quant.wrds_store import WRDSPointInTimeStore
                _evt_store = WRDSPointInTimeStore()
                event_scores = compute_event_timing_scores(
                    list(signals.keys()), reb_date,
                    wrds_store=_evt_store,
                )
                for ticker, (escore, emeta) in event_scores.items():
                    if ticker in signals:
                        signals[ticker].event_timing_score = escore
                        signals[ticker].earnings_blocked = emeta.get("earnings_blocked", False)

            # Kalshi signals (macro modifier + event divergence)
            if config.enable_kalshi_signal:
                try:
                    from quant.kalshi_client import KalshiClient
                    from quant.kalshi_signal import compute_macro_modifier, compute_event_divergence
                    _kalshi_client = KalshiClient()
                    _kalshi_macro = compute_macro_modifier(_kalshi_client)
                    for _ticker in signals:
                        signals[_ticker].kalshi_macro_score = _kalshi_macro
                        _earn_prob = getattr(signals[_ticker], "earnings_rank_score", 0.0)
                        # Map earnings_rank_score ([-1,1]) to probability space [0,1]
                        _our_prob = (_earn_prob + 1.0) / 2.0
                        signals[_ticker].kalshi_event_score = compute_event_divergence(
                            _kalshi_client,
                            ticker=_ticker,
                            our_prob_beat=_our_prob,
                            threshold=config.kalshi_event_threshold,
                        )
                except Exception as _exc:
                    logger.warning("Kalshi signal injection failed: %s", _exc)

            # ── Cross-sectional normalization barrier ──
            if not _xgb_active:
                from quant.cross_sectional import normalize_signals_cross_sectionally, compute_normalized_composite, make_volatility_tier_fn
                from quant.scoring import reclassify
                signals = normalize_signals_cross_sectionally(signals, make_volatility_tier_fn(signals))
                for sv in signals.values():
                    sv.composite_score = compute_normalized_composite(sv)
                    if config.enable_kalshi_signal:
                        sv.composite_score = float(np.clip(
                            sv.composite_score
                            + sv.kalshi_macro_score * config.kalshi_macro_weight
                            + sv.kalshi_event_score * config.kalshi_event_weight,
                            -1.0, 1.0,
                        ))
                    reclassify(sv)

            if config.enable_fomc_proximity:
                vix_now = None
                if vix_df is not None:
                    vix_avail = vix_df[vix_df.index <= reb_date]
                    if len(vix_avail) > 0:
                        vix_now = float(vix_avail.iloc[-1]["close"])
                fomc_boost = compute_fomc_proximity_boost(reb_date, trading_dates, vix_now, config)
                if fomc_boost > 0:
                    signals = apply_fomc_boost(signals, fomc_boost)

            if config.enable_regime_filter:
                regime = detect_regime(benchmark_df, reb_date, vix_df=vix_df, config=config, sector_data=_sector_etf_data, hy_oas_series=hy_oas_series, t10y3m_series=t10y3m_series)
            else:
                regime = RegimeState(level="unknown")

            # Use fresh capital per combination (no carry-over between
            # non-contiguous test groups — per CPCV methodology)
            positions = build_target_portfolio(
                signals, universe_data, reb_date, config, config.initial_capital, regime=regime,
            )
            if not positions:
                continue
            trades, period_pnl = _compute_daily_portfolio_returns(
                positions, universe_data, reb_date, next_reb, config,
            )
            combo_trades.extend(trades)
            if len(period_pnl) > 0:
                combo_daily_pnl = pd.concat([combo_daily_pnl, period_pnl])

        # Compute Sharpe for this combination
        oos_sharpe = None
        n_trades = len(combo_trades)
        combo_return = 0.0
        if len(combo_daily_pnl) > 0:
            combo_daily_pnl = combo_daily_pnl.groupby(combo_daily_pnl.index).sum().sort_index()
            daily_returns = combo_daily_pnl / config.initial_capital
            oos_sharpe = compute_sharpe_from_returns(daily_returns)
            combo_return = round(float(combo_daily_pnl.sum() / config.initial_capital * 100), 2)

        if oos_sharpe is not None:
            result.oos_sharpes.append(oos_sharpe)
            result.combination_details.append({
                "combo_idx": ci,
                "train_groups": train_indices,
                "test_groups": test_indices,
                "n_test_dates": len(safe_test_dates),
                "n_trades": n_trades,
                "oos_sharpe": oos_sharpe,
                "return_pct": combo_return,
            })
            result.n_combinations_completed += 1
        else:
            result.n_combinations_skipped += 1

    # ── 5. Compute aggregate stats ──
    result.elapsed_seconds = round(_time.time() - t0, 1)
    result.compute_summary_stats()

    return result
