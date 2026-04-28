"""
Mathematical computation of technical trading signals.

Replaces LLM-approximated indicators with exact numpy/pandas calculations.
Each function returns a score in [-1.0, +1.0] plus metadata.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class SignalResult:
    score: float  # -1.0 to +1.0
    detail: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class SignalVector:
    """Complete scored signal vector from price/volume data."""
    sma_trend: SignalResult
    mean_reversion_z: SignalResult
    bollinger_pctb: SignalResult
    rsi: SignalResult
    obv_trend: SignalResult
    atr_regime: SignalResult
    high_52w: SignalResult = field(default_factory=lambda: SignalResult(0.0, "not computed"))
    composite_score: float = 0.0
    composite_direction: str = "HOLD"
    actionable: bool = False
    earnings_rank_score: float = 0.0   # Set by earnings signals for ranking (Path A)
    institutional_flow_score: float = 0.0  # Set by institutional flow signal
    sentiment_score: float = 0.0  # Set by sentiment blend for cross-sectional normalization
    sector_momentum_score: float = 0.0  # Set by sector ETF momentum signal
    quality_score: float = 0.0  # Set by quality/profitability signal (WRDS Compustat)
    price_momentum_score: float = 0.0  # Set by 12-1M price momentum
    insider_score: float = 0.0  # Set by standalone insider MSPR signal
    event_timing_score: float = 0.0  # Set by event timing (PEAD + catalyst proximity)
    copper_regime_score: float = 0.0   # Set by copper macro signal (-1 to +1)
    kalshi_macro_score: float = 0.0   # Macro regime from Kalshi Fed/CPI/JOBS markets
    kalshi_event_score: float = 0.0   # Pre-earnings divergence vs Kalshi-implied prob
    kalshi_macro_momentum: float = 0.0  # Rate-of-change of macro modifier (velocity)
    price_regression_score: float = 0.0  # R²-filtered OLS trend signal [-1, +1]
    arima_forecast_score: float = 0.0    # ARIMA(1,1,1) forecast signal, stable regimes only [-1, +1]
    qmj_score: float = 0.0  # Quality-Minus-Junk composite (Asness/Frazzini/Pedersen 2019) — opt-in via cfg.enable_qmj_signal
    earnings_blocked: bool = False  # True if earnings within 3 days — block new entries
    flags: list = field(default_factory=list)

    # Weights — Phase 0 (2026-04-09) showed zero IC for SMA, MR, BB, RSI, 52W.
    # Only OBV had marginal independent signal (residual t=1.82 in redundancy).
    # All other signals zeroed pending replacement with orthogonal signals.
    WEIGHTS = {
        "sma_trend": 0.0,
        "mean_reversion_z": 0.0,
        "bollinger_pctb": 0.0,
        "rsi": 0.0,
        "obv_trend": 1.0,
        "high_52w": 0.0,
    }

    def compute_composite(self) -> None:
        signals = {
            "sma_trend": self.sma_trend.score,
            "mean_reversion_z": self.mean_reversion_z.score,
            "bollinger_pctb": self.bollinger_pctb.score,
            "rsi": self.rsi.score,
            "obv_trend": self.obv_trend.score,
            "high_52w": self.high_52w.score,
        }
        self.composite_score = sum(
            signals[k] * self.WEIGHTS[k] for k in signals
        )
        self.composite_score = np.clip(self.composite_score, -1.0, 1.0)

        from quant.scoring import reclassify
        reclassify(self)

        # Gate: suppress long entries if SMA is bearish (disabled — SMA weight=0)
        # if self.sma_trend.score <= -0.5 and self.composite_direction == "BUY":
        #     self.flags.append("sma_gate_bearish")

    @staticmethod
    def _clean(val):
        """Convert numpy types to native Python for JSON serialization."""
        if isinstance(val, (np.bool_,)):
            return bool(val)
        if isinstance(val, (np.integer,)):
            return int(val)
        if isinstance(val, (np.floating,)):
            return float(val)
        return val

    def _signal_dict(self, sr: SignalResult) -> dict:
        return {"score": round(float(sr.score), 3), "detail": sr.detail,
                **{k: self._clean(v) for k, v in sr.metadata.items()}}

    def to_dict(self) -> dict:
        return {
            "signal_vector": {
                "sma_trend": self._signal_dict(self.sma_trend),
                "mean_reversion_z": self._signal_dict(self.mean_reversion_z),
                "bollinger_pctb": self._signal_dict(self.bollinger_pctb),
                "rsi": self._signal_dict(self.rsi),
                "obv_trend": self._signal_dict(self.obv_trend),
                "high_52w": self._signal_dict(self.high_52w),
                "atr_regime": self._signal_dict(self.atr_regime),
            },
            "composite_score": round(self.composite_score, 4),
            "composite_direction": self.composite_direction,
            "actionable": self.actionable,
            "flags": self.flags,
        }

    def to_enrichment_text(self) -> str:
        """Format as enrichment section text for the LLM pattern agent."""
        lines = ["=== Computed Technical Signals ==="]
        d = self.to_dict()
        sv = d["signal_vector"]
        for name, data in sv.items():
            lines.append(f"  {name}: score={data['score']:.3f} — {data.get('detail', '')}")
        lines.append(f"  COMPOSITE: {d['composite_score']:.4f} → {d['composite_direction']} (actionable={d['actionable']})")
        if d["flags"]:
            lines.append(f"  FLAGS: {', '.join(d['flags'])}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual signal computations
# ---------------------------------------------------------------------------

def compute_sma_trend(close: pd.Series) -> SignalResult:
    """SMA trend: 50d/200d crossover scoring."""
    if len(close) < 200:
        if len(close) < 50:
            return SignalResult(0.0, "insufficient data (<50 days)")
        sma50 = float(close.tail(50).mean())
        price = float(close.iloc[-1])
        score = 0.5 if price > sma50 else -0.5
        return SignalResult(score, f"price {'above' if price > sma50 else 'below'} 50d SMA (no 200d data)",
                           {"sma50": round(sma50, 2), "price": round(price, 2)})

    price = float(close.iloc[-1])
    sma50 = float(close.tail(50).mean())
    sma200 = float(close.tail(200).mean())

    if price > sma50 and sma50 > sma200:
        score = 1.0
        detail = "strong uptrend — price > 50d > 200d"
    elif price > sma200 and price <= sma50:
        score = 0.5
        detail = "uptrend with pullback — above 200d, below 50d"
    elif price < sma200 and price >= sma50:
        score = -0.5
        detail = "downtrend with bounce — below 200d, above 50d"
    else:
        score = -1.0
        detail = "strong downtrend — price < 50d < 200d"

    cross = "golden_cross" if sma50 > sma200 else "death_cross"
    return SignalResult(score, detail, {"sma50": round(sma50, 2), "sma200": round(sma200, 2),
                                        "price": round(price, 2), "cross": cross})


def compute_mean_reversion(close: pd.Series) -> SignalResult:
    """Mean reversion Z-score: suppressed on trending stocks."""
    if len(close) < 60:
        return SignalResult(0.0, "insufficient data (<60 days)")

    window = close.tail(60)
    mean_60 = float(window.mean())
    std_60 = float(window.std())
    price = float(close.iloc[-1])

    if std_60 < 1e-8:
        return SignalResult(0.0, "zero volatility")

    z = (price - mean_60) / std_60

    # Suppress on trending stocks (>30% drift over 60d)
    drift = abs(price / float(window.iloc[0]) - 1)
    if drift > 0.30:
        return SignalResult(0.0, f"suppressed — {drift*100:.0f}% drift over 60d (trending)",
                           {"z_score": round(z, 3), "drift_pct": round(drift * 100, 1), "suppressed": True})

    score = float(np.clip(-z / 2, -1.0, 1.0))
    if z < -1.5:
        detail = "deeply oversold"
    elif z < -0.5:
        detail = "moderately oversold"
    elif z > 1.5:
        detail = "deeply overbought"
    elif z > 0.5:
        detail = "moderately overbought"
    else:
        detail = "near mean"

    return SignalResult(score, detail, {"z_score": round(z, 3), "mean_60": round(mean_60, 2),
                                        "std_60": round(std_60, 2)})


def compute_bollinger(close: pd.Series) -> SignalResult:
    """Bollinger %B with squeeze detection."""
    if len(close) < 20:
        return SignalResult(0.0, "insufficient data (<20 days)")

    window = close.tail(20)
    sma20 = float(window.mean())
    std20 = float(window.std())
    price = float(close.iloc[-1])

    if std20 < 1e-8:
        return SignalResult(0.0, "zero volatility")

    upper = sma20 + 2 * std20
    lower = sma20 - 2 * std20
    bandwidth = (upper - lower) / sma20

    pct_b = (price - lower) / (upper - lower) if upper != lower else 0.5
    score = float(np.clip((0.5 - pct_b) * 2, -1.0, 1.0))

    # Squeeze detection: compare current bandwidth to 6-month history
    squeeze = False
    if len(close) >= 126:
        rolling_bw = close.rolling(20).std() * 4 / close.rolling(20).mean()
        rolling_bw = rolling_bw.dropna().tail(126)
        if len(rolling_bw) > 0 and bandwidth <= float(rolling_bw.quantile(0.1)):
            squeeze = True

    detail = f"%B={pct_b:.2f}"
    if squeeze:
        detail += " — SQUEEZE detected (low bandwidth)"

    return SignalResult(score, detail, {"pct_b": round(pct_b, 3), "bandwidth": round(bandwidth, 4),
                                        "squeeze": bool(squeeze), "upper": round(upper, 2), "lower": round(lower, 2)})


def compute_rsi(close: pd.Series, period: int = 14) -> SignalResult:
    """RSI with divergence detection."""
    if len(close) < period + 10:
        return SignalResult(0.0, f"insufficient data (<{period + 10} days)")

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi_series = 100 - (100 / (1 + rs))
    rsi_val = float(rsi_series.iloc[-1])

    score = float(np.clip((50 - rsi_val) / 50, -1.0, 1.0))

    # Divergence detection (last 20 bars)
    divergence = ""
    if len(close) >= 40:
        recent_close = close.tail(20)
        recent_rsi = rsi_series.tail(20)

        price_new_low = float(recent_close.iloc[-1]) <= float(recent_close.min()) * 1.01
        rsi_higher_low = float(recent_rsi.iloc[-1]) > float(recent_rsi.min()) + 2

        price_new_high = float(recent_close.iloc[-1]) >= float(recent_close.max()) * 0.99
        rsi_lower_high = float(recent_rsi.iloc[-1]) < float(recent_rsi.max()) - 2

        if price_new_low and rsi_higher_low:
            divergence = "bullish_divergence"
            score = float(np.clip(score + 0.3, -1.0, 1.0))
        elif price_new_high and rsi_lower_high:
            divergence = "bearish_divergence"
            score = float(np.clip(score - 0.3, -1.0, 1.0))

    detail = f"RSI={rsi_val:.1f}"
    if divergence:
        detail += f" — {divergence}"

    return SignalResult(score, detail, {"rsi_value": round(rsi_val, 1), "divergence": divergence})


def compute_obv_trend(close: pd.Series, volume: pd.Series) -> SignalResult:
    """On-Balance Volume 20-day trend with price confirmation."""
    if len(close) < 20 or len(volume) < 20:
        return SignalResult(0.0, "insufficient data (<20 days)")

    # Compute OBV
    direction = np.sign(close.diff())
    obv = (direction * volume).cumsum()

    obv_20 = obv.tail(20)
    close_20 = close.tail(20)

    # Linear regression slope for OBV
    x = np.arange(len(obv_20))
    obv_slope = float(np.polyfit(x, obv_20.values, 1)[0])
    price_slope = float(np.polyfit(x, close_20.values, 1)[0])

    obv_up = obv_slope > 0
    price_up = price_slope > 0

    if obv_up and price_up:
        score = min(1.0, 0.5 + abs(obv_slope) / (abs(obv_slope) + 1e-10) * 0.5)
        detail = "confirmed accumulation — OBV and price rising"
    elif not obv_up and not price_up:
        score = max(-1.0, -0.5 - abs(obv_slope) / (abs(obv_slope) + 1e-10) * 0.5)
        detail = "confirmed distribution — OBV and price falling"
    elif obv_up and not price_up:
        score = 0.2
        detail = "bullish divergence — OBV rising, price falling"
    else:
        score = -0.2
        detail = "bearish divergence — OBV falling, price rising"

    divergence = bool(obv_up != price_up)
    return SignalResult(score, detail, {"obv_slope": round(obv_slope, 2),
                                        "price_slope": round(price_slope, 4),
                                        "divergence": divergence})


def compute_atr_regime(close: pd.Series, high: Optional[pd.Series] = None,
                       low: Optional[pd.Series] = None, period: int = 14) -> SignalResult:
    """ATR regime classification for position sizing (non-directional)."""
    if len(close) < period + 1:
        return SignalResult(0.0, "insufficient data")

    if high is not None and low is not None and len(high) >= period + 1:
        # True Range with high/low data
        h = high.values
        l = low.values
        c = close.shift(1).values
        tr = np.maximum(h - l, np.maximum(abs(h - c), abs(l - c)))
        tr = pd.Series(tr, index=close.index)
    else:
        # Approximate TR from close-to-close
        tr = close.diff().abs()

    atr = float(tr.tail(period).mean())
    price = float(close.iloc[-1])
    atr_pct = (atr / price * 100) if price > 0 else 0.0

    # Quartile regime from 1-year history
    regime = "normal"
    if len(tr) >= 252:
        rolling_atr = tr.rolling(period).mean().dropna().tail(252)
        rolling_atr_pct = rolling_atr / close.tail(len(rolling_atr)) * 100
        if len(rolling_atr_pct) > 0:
            q25 = float(rolling_atr_pct.quantile(0.25))
            q75 = float(rolling_atr_pct.quantile(0.75))
            if atr_pct <= q25:
                regime = "low_vol"
            elif atr_pct >= q75:
                regime = "high_vol"

    detail = f"ATR%={atr_pct:.2f}%, regime={regime}"
    stop_2x = round(price - 2 * atr, 2) if price > 0 else 0.0

    return SignalResult(0.0, detail, {"atr_pct": round(atr_pct, 3),
                                      "atr_value": round(atr, 3),
                                      "volatility_regime": regime,
                                      "stop_loss_atr2x": stop_2x})


def compute_52w_high(close: pd.Series) -> SignalResult:
    """
    52-week high ratio: price / 52-week high.

    George & Hwang (2004) showed this generates ~2x the returns of standard
    12-1 month momentum with less crash exposure. Replicated through 2024.

    Score mapping:
      ratio >= 0.95 (within 5% of high) → +1.0 (strong momentum)
      ratio >= 0.85 → proportional +0.3 to +0.9
      ratio >= 0.70 → proportional -0.3 to +0.3
      ratio < 0.70 (>30% off high) → -1.0 (deep drawdown)
    """
    if len(close) < 252:
        if len(close) < 60:
            return SignalResult(0.0, "insufficient data (<60 days)")
        # Use available data for shorter histories
        high = float(close.max())
    else:
        high = float(close.tail(252).max())

    price = float(close.iloc[-1])
    if high <= 0:
        return SignalResult(0.0, "invalid high price")

    ratio = price / high

    # Map ratio to score: near high = bullish, far from high = bearish
    if ratio >= 0.95:
        score = 0.5 + (ratio - 0.95) / 0.05 * 0.5  # 0.95→+0.5, 1.0→+1.0
        score = min(1.0, score)
        detail = f"near 52w high ({ratio:.1%})"
    elif ratio >= 0.85:
        score = (ratio - 0.85) / 0.10 * 0.5  # 0.85→0.0, 0.95→+0.5
        detail = f"moderate momentum ({ratio:.1%})"
    elif ratio >= 0.70:
        score = (ratio - 0.70) / 0.15 * 0.5 - 0.5  # 0.70→-0.5, 0.85→0.0
        detail = f"pullback ({ratio:.1%})"
    else:
        score = -1.0
        detail = f"deep drawdown ({ratio:.1%} of 52w high)"

    return SignalResult(
        round(float(score), 4),
        detail,
        {"ratio": round(ratio, 4), "high_52w": round(high, 2), "price": round(price, 2)},
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_signal_vector(close: pd.Series, volume: Optional[pd.Series] = None,
                          high: Optional[pd.Series] = None,
                          low: Optional[pd.Series] = None) -> SignalVector:
    """Compute the full technical signal vector from price/volume data.

    Args:
        close: Daily close/adjClose prices, DatetimeIndex, sorted ascending.
        volume: Daily volume (optional — OBV will return 0 if missing).
        high: Daily high prices (optional — improves ATR accuracy).
        low: Daily low prices (optional — improves ATR accuracy).

    Returns:
        SignalVector with all 6 signals scored and composite computed.
    """
    sma = compute_sma_trend(close)
    mr = compute_mean_reversion(close)
    boll = compute_bollinger(close)
    rsi = compute_rsi(close)

    if volume is not None and len(volume) >= 20:
        obv = compute_obv_trend(close, volume)
    else:
        obv = SignalResult(0.0, "no volume data")

    atr = compute_atr_regime(close, high, low)
    h52 = compute_52w_high(close)

    sv = SignalVector(
        sma_trend=sma,
        mean_reversion_z=mr,
        bollinger_pctb=boll,
        rsi=rsi,
        obv_trend=obv,
        atr_regime=atr,
        high_52w=h52,
    )
    sv.compute_composite()
    return sv


def compute_signal_vector_from_provider(ticker: str, tiingo_api_key: str = "") -> Optional[SignalVector]:
    """Convenience: fetch 2-year data via price provider and compute signals.

    Args:
        tiingo_api_key: Deprecated — kept for backward compat. Uses PRICE_PROVIDER env var.
    """
    from datetime import datetime, timedelta
    try:
        from price_provider import get_price_provider
        provider = get_price_provider()
        start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        data = provider.get_eod_history(ticker, start)
        if not data or len(data) < 60:
            return None

        df = pd.DataFrame(data)
        if df["date"].dtype == "object":
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None, ambiguous="NaT", nonexistent="NaT")
        else:
            df["date"] = pd.to_datetime(df["date"]).dt.tz_convert(None)
        df = df.sort_values("date").set_index("date")

        close = df["adjClose"] if "adjClose" in df.columns else df["close"]
        volume = df["volume"] if "volume" in df.columns else None
        high = df["adjHigh"] if "adjHigh" in df.columns else None
        low = df["adjLow"] if "adjLow" in df.columns else None

        return compute_signal_vector(close, volume, high, low)
    except Exception:
        logger.debug("Failed to compute signal vector for %s", ticker, exc_info=True)
        return None


# Backward compat alias
compute_signal_vector_from_tiingo = compute_signal_vector_from_provider
