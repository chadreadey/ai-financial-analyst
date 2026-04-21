"""
Macro regime signals from FRED data.

Time-series regime filters (not cross-sectional stock selectors):
  - HY OAS percentile rank + rate-of-change
  - Yield curve (10Y-3M) inversion signal
  - Composite recession probability (simplified probit-inspired)

These feed into detect_regime() as additional inputs for position sizing
and into agent prompts as macro context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class MacroRegimeSignal:
    """Composite macro regime assessment."""
    # HY Credit Spread
    hy_oas: Optional[float] = None          # current spread in %
    hy_oas_percentile: Optional[float] = None  # 0-100, vs 5-year history
    hy_oas_3m_change: Optional[float] = None   # 3-month change in bps
    hy_oas_regime: str = "unknown"           # calm / elevated / stress / crisis

    # Yield Curve
    t10y3m: Optional[float] = None           # 10Y-3M spread
    curve_inverted: bool = False
    curve_regime: str = "unknown"            # steep / normal / flat / inverted

    # Recession
    recession_score: float = 0.0             # 0.0-1.0 composite probability
    recession_regime: str = "unknown"        # low / moderate / elevated / high

    # Copper (PCOPPUSDM)
    copper_price: Optional[float] = None
    copper_drawdown_12m: Optional[float] = None
    copper_regime: str = "unknown"
    copper_score: float = 0.0

    # Composite
    regime_multiplier: float = 1.0           # sizing multiplier (0.25-1.0)
    regime_label: str = "unknown"            # risk_on / cautious / risk_off

    def to_dict(self) -> dict:
        return {
            "hy_oas": self.hy_oas,
            "hy_oas_percentile": self.hy_oas_percentile,
            "hy_oas_3m_change": self.hy_oas_3m_change,
            "hy_oas_regime": self.hy_oas_regime,
            "t10y3m": self.t10y3m,
            "curve_inverted": self.curve_inverted,
            "curve_regime": self.curve_regime,
            "recession_score": round(self.recession_score, 3),
            "recession_regime": self.recession_regime,
            "copper_price": self.copper_price,
            "copper_drawdown_12m": self.copper_drawdown_12m,
            "copper_regime": self.copper_regime,
            "copper_score": self.copper_score,
            "regime_multiplier": self.regime_multiplier,
            "regime_label": self.regime_label,
        }

    def to_context_text(self) -> str:
        """Format as context string for LLM agent prompts."""
        lines = ["=== Macro Regime Context ==="]
        if self.hy_oas is not None:
            lines.append(f"  HY OAS: {self.hy_oas:.2f}% ({self.hy_oas_regime}) "
                         f"| Percentile: {self.hy_oas_percentile:.0f}th "
                         f"| 3mo change: {self.hy_oas_3m_change:+.0f}bps")
        if self.t10y3m is not None:
            lines.append(f"  Yield curve (10Y-3M): {self.t10y3m:+.2f}% ({self.curve_regime})")
        lines.append(f"  Recession probability: {self.recession_score:.0%} ({self.recession_regime})")
        if self.copper_regime != "unknown":
            lines.append(f"  Copper: {self.copper_regime} (drawdown {self.copper_drawdown_12m:.1%} from 12M high, score {self.copper_score:+.2f})")
        lines.append(f"  Regime: {self.regime_label} | Sizing multiplier: {self.regime_multiplier:.2f}")
        return "\n".join(lines)


# ── HY OAS Signal ─────────────────────────────────────────────────────

def compute_hy_oas_signal(
    hy_oas_series: pd.Series,
    as_of_date: pd.Timestamp,
    lookback_years: int = 5,
) -> tuple[Optional[float], Optional[float], Optional[float], str]:
    """
    Compute HY OAS percentile rank and rate-of-change.

    Returns: (current_oas, percentile_rank, 3m_change_bps, regime_label)

    Regime thresholds (from credit-spreads-equity-market-returns.md):
      < 300 bps  = extreme_complacency (bottom decile historically)
      300-450    = calm
      450-600    = elevated
      600-800    = stress (strong equity buying signal historically)
      > 800      = crisis (once-in-a-decade buying opportunity)
    """
    available = hy_oas_series[hy_oas_series.index <= as_of_date].dropna()
    if len(available) < 60:
        return None, None, None, "unknown"

    current = float(available.iloc[-1])

    # Percentile vs lookback history
    lookback_start = as_of_date - pd.DateOffset(years=lookback_years)
    history = available[available.index >= lookback_start]
    if len(history) > 20:
        percentile = float((history < current).mean() * 100)
    else:
        percentile = 50.0

    # 3-month rate of change (bps)
    three_months_ago = as_of_date - pd.DateOffset(months=3)
    prior = available[available.index <= three_months_ago]
    if len(prior) > 0:
        change_bps = (current - float(prior.iloc[-1])) * 100  # convert % to bps
    else:
        change_bps = 0.0

    # Regime classification
    if current >= 8.0:
        regime = "crisis"
    elif current >= 6.0:
        regime = "stress"
    elif current >= 4.5:
        regime = "elevated"
    elif current >= 3.0:
        regime = "calm"
    else:
        regime = "extreme_complacency"

    return current, percentile, change_bps, regime


# ── Yield Curve Signal ─────────────────────────────────────────────────

def compute_yield_curve_signal(
    t10y3m_series: pd.Series,
    as_of_date: pd.Timestamp,
) -> tuple[Optional[float], bool, str]:
    """
    Compute yield curve signal from 10Y-3M spread.

    Returns: (spread, inverted, regime_label)

    Curve regimes:
      > 2.0%  = steep (early expansion)
      0.5-2.0 = normal
      0-0.5   = flat (late cycle warning)
      < 0     = inverted (recession signal, 12-24mo lead)
    """
    available = t10y3m_series[t10y3m_series.index <= as_of_date].dropna()
    if len(available) < 5:
        return None, False, "unknown"

    spread = float(available.iloc[-1])
    inverted = spread < 0

    if spread > 2.0:
        regime = "steep"
    elif spread > 0.5:
        regime = "normal"
    elif spread > 0:
        regime = "flat"
    else:
        regime = "inverted"

    return spread, inverted, regime


# ── Simplified Recession Score ─────────────────────────────────────────

def compute_recession_score(
    hy_oas: Optional[float],
    hy_oas_percentile: Optional[float],
    hy_oas_3m_change: Optional[float],
    t10y3m: Optional[float],
    curve_inverted: bool,
    vix: Optional[float] = None,
) -> tuple[float, str]:
    """
    Simplified recession probability composite.

    This is a rules-based approximation of the probit model from
    recession_probability_model_guide.md. Uses available real-time
    indicators without requiring the full FRED model infrastructure.

    Each indicator contributes 0-0.25 to a 0-1.0 composite score.
    Thresholds calibrated from historical recession episodes.

    Returns: (recession_score 0-1, regime_label)
    """
    score = 0.0
    n_signals = 0

    # 1. Yield curve (weight: 0.30) — strongest single predictor
    if t10y3m is not None:
        n_signals += 1
        if t10y3m < -0.5:
            score += 0.30  # deeply inverted
        elif t10y3m < 0:
            score += 0.20  # inverted
        elif t10y3m < 0.3:
            score += 0.10  # flat (warning)
        # positive spread = no recession signal

    # 2. HY OAS level (weight: 0.25) — onset proximity signal
    if hy_oas is not None:
        n_signals += 1
        if hy_oas >= 8.0:
            score += 0.25  # crisis
        elif hy_oas >= 6.0:
            score += 0.20  # stress
        elif hy_oas >= 5.0:
            score += 0.10  # elevated
        elif hy_oas < 3.0:
            score += 0.02  # complacency risk (not recession, but fragile)

    # 3. HY OAS rate of change (weight: 0.25) — more actionable than level
    if hy_oas_3m_change is not None:
        n_signals += 1
        if hy_oas_3m_change > 200:  # >200bps widening in 3mo
            score += 0.25
        elif hy_oas_3m_change > 100:  # >100bps widening
            score += 0.15
        elif hy_oas_3m_change > 50:
            score += 0.05

    # 4. VIX (weight: 0.20) — confirming signal
    if vix is not None:
        n_signals += 1
        if vix >= 35:
            score += 0.20
        elif vix >= 28:
            score += 0.12
        elif vix >= 22:
            score += 0.05

    # Normalize if we're missing signals
    if n_signals > 0 and n_signals < 4:
        score = score * (4 / n_signals) * 0.7  # scale up but discount for missing data

    score = min(1.0, score)

    # Classify — thresholds recalibrated from 2014-2026 empirical distribution.
    # Old thresholds (0.15/0.30/0.50) caught 99% of months as "moderate" or worse.
    # New thresholds reserve sizing reduction for genuine stress periods.
    if score >= 0.65:
        regime = "high"
    elif score >= 0.50:
        regime = "elevated"
    elif score >= 0.35:
        regime = "moderate"
    else:
        regime = "low"

    return round(score, 3), regime


# ── Copper Signal ─────────────────────────────────────────────────────

def compute_copper_signal(
    copper_series: pd.Series,
    as_of_date: pd.Timestamp,
) -> tuple:
    """
    Compute copper regime signal from PCOPPUSDM (monthly, USD/MT).

    Thresholds (IMF WP/12/278, BoC 2016-17):
      >= -5% of 12M high  : bullish (score +0.5 to +1.0)
      -5% to -15%         : neutral (score 0.0)
      -15% to -25%, persistent 2+ months: bearish (score -0.5)
      < -25%, persistent  : crisis (score -1.0)
      Non-persistent below -15%: neutral with partial negative score

    China confound: treat as confirming filter only, not standalone trigger.
    Returns: (current_price, drawdown_from_12m_high, regime_label, score)
    """
    available = copper_series[copper_series.index <= as_of_date].dropna()
    if len(available) < 13:
        return None, None, "unknown", 0.0

    current = float(available.iloc[-1])
    prior = available.iloc[:-1]

    # Point-in-time 12M trailing high (excludes current month)
    high_12m = float(prior.iloc[-12:].max())
    drawdown = (current - high_12m) / high_12m  # <= 0 if below high

    # New 12M high
    if current >= high_12m:
        return current, round(drawdown, 4), "bullish", 1.0

    # Persistence: check if prior month was also below -15% threshold
    persistent = False
    if len(prior) >= 2:
        prior_current = float(prior.iloc[-1])
        # Use same high_12m as point-in-time for prior month (conservative)
        prior_high = float(prior.iloc[-12:].max()) if len(prior) >= 12 else float(prior.max())
        prior_drawdown = (prior_current - prior_high) / prior_high
        persistent = prior_drawdown <= -0.15

    if drawdown >= -0.05:
        regime, score = "bullish", 0.5
    elif drawdown >= -0.15:
        regime, score = "neutral", 0.0
    elif drawdown >= -0.25:
        if persistent:
            regime, score = "bearish", -0.5
        else:
            regime, score = "neutral", -0.2
    else:
        if persistent:
            regime, score = "crisis", -1.0
        else:
            regime, score = "neutral", -0.3

    return current, round(drawdown, 4), regime, round(score, 3)


# ── Composite Regime Assessment ────────────────────────────────────────

def compute_macro_regime(
    hy_oas_series: Optional[pd.Series],
    t10y3m_series: Optional[pd.Series],
    as_of_date: pd.Timestamp,
    vix: Optional[float] = None,
    copper_series: Optional[pd.Series] = None,
) -> MacroRegimeSignal:
    """
    Compute full macro regime signal from FRED data.

    Returns MacroRegimeSignal with regime_multiplier for position sizing.
    """
    signal = MacroRegimeSignal()

    # HY OAS
    if hy_oas_series is not None and not hy_oas_series.empty:
        oas, pct, chg, regime = compute_hy_oas_signal(hy_oas_series, as_of_date)
        signal.hy_oas = oas
        signal.hy_oas_percentile = pct
        signal.hy_oas_3m_change = chg
        signal.hy_oas_regime = regime

    # Yield curve
    if t10y3m_series is not None and not t10y3m_series.empty:
        spread, inv, regime = compute_yield_curve_signal(t10y3m_series, as_of_date)
        signal.t10y3m = spread
        signal.curve_inverted = inv
        signal.curve_regime = regime

    # Recession score
    score, regime = compute_recession_score(
        signal.hy_oas, signal.hy_oas_percentile, signal.hy_oas_3m_change,
        signal.t10y3m, signal.curve_inverted, vix,
    )
    signal.recession_score = score
    signal.recession_regime = regime

    # Determine regime multiplier for position sizing
    # This combines with the existing VIX/SMA/turbulence regime
    if signal.recession_regime == "high":
        signal.regime_multiplier = 0.25
        signal.regime_label = "risk_off"
    elif signal.recession_regime == "elevated":
        signal.regime_multiplier = 0.50
        signal.regime_label = "cautious"
    elif signal.hy_oas_regime in ("stress", "crisis"):
        # Wide spreads = contrarian buy signal, but reduce sizing during widening
        if signal.hy_oas_3m_change is not None and signal.hy_oas_3m_change > 100:
            signal.regime_multiplier = 0.50  # still widening — stay cautious
            signal.regime_label = "cautious"
        else:
            signal.regime_multiplier = 1.0  # wide but stabilizing — buy signal
            signal.regime_label = "risk_on"
    elif signal.recession_regime == "moderate":
        signal.regime_multiplier = 0.75
        signal.regime_label = "cautious"
    else:
        signal.regime_multiplier = 1.0
        signal.regime_label = "risk_on"

    # Copper signal
    if copper_series is not None and not copper_series.empty:
        _cu_price, _cu_dd, _cu_regime, _cu_score = compute_copper_signal(copper_series, as_of_date)
        signal.copper_price = _cu_price
        signal.copper_drawdown_12m = _cu_dd
        signal.copper_regime = _cu_regime
        signal.copper_score = _cu_score

    return signal


# ── FRED Data Loading for Backtest ─────────────────────────────────────

_hy_oas_cache: Optional[pd.Series] = None
_t10y3m_cache: Optional[pd.Series] = None
_copper_cache: Optional[pd.Series] = None


def load_fred_macro_data(start_date: str = "2010-01-01") -> tuple[Optional[pd.Series], Optional[pd.Series], Optional[pd.Series]]:
    """
    Load HY OAS, 10Y-3M yield curve spread, and copper price from FRED.

    Returns (hy_oas_series, t10y3m_series, copper_series) — all as pd.Series with DatetimeIndex.
    Returns cached data on subsequent calls.
    """
    global _hy_oas_cache, _t10y3m_cache, _copper_cache

    if _hy_oas_cache is not None and _t10y3m_cache is not None and _copper_cache is not None:
        return _hy_oas_cache, _t10y3m_cache, _copper_cache

    try:
        from fred_client import get_fred_client
        client = get_fred_client()
        if client is None:
            logger.warning("No FRED API key — macro signals disabled")
            return None, None, None

        logger.info("Loading FRED macro data for backtest...")
        hy = client.get_series("BAMLH0A0HYM2", observation_start=start_date)
        t10y3m = client.get_series("T10Y3M", observation_start=start_date)

        if not hy.empty:
            _hy_oas_cache = hy
            logger.info("HY OAS: %d obs, %s to %s", len(hy), hy.index[0].date(), hy.index[-1].date())
        if not t10y3m.empty:
            _t10y3m_cache = t10y3m
            logger.info("T10Y3M: %d obs, %s to %s", len(t10y3m), t10y3m.index[0].date(), t10y3m.index[-1].date())

        copper = pd.Series(dtype=float)
        try:
            raw = client.get_series("PCOPPUSDM", observation_start=start_date)
            if raw is not None and not raw.empty:
                copper = raw.resample("MS").last().ffill()
                _copper_cache = copper
                logger.info("Copper: %d obs, %s to %s", len(copper), copper.index[0].date(), copper.index[-1].date())
        except Exception as exc:
            logger.warning("Failed to load PCOPPUSDM: %s", exc)

        return _hy_oas_cache, _t10y3m_cache, _copper_cache

    except Exception as e:
        logger.warning("Failed to load FRED data: %s", e)
        return None, None, None
