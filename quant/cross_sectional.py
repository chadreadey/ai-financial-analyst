"""
Cross-sectional signal normalization.

Converts raw signal scores to sector-adjusted winsorized z-scores
so that signals generalize across any universe size. A utility stock's
exceptional OBV reading outranks a tech stock's average OBV reading.

Algorithm per signal per rebalance date:
1. Collect raw scores across all tickers
2. Subtract sector mean (sector-relative adjustment)
3. Winsorize at 2.5th / 97.5th percentile
4. Z-score (mean=0, std=1)
5. Scale to [-1, +1] via clip(z / 3.0)
"""

from __future__ import annotations

import logging
from typing import Callable

import numpy as np

from quant.signals import SignalResult, SignalVector

logger = logging.getLogger(__name__)

MIN_CROSS_SECTION = 10
WINSORIZE_LOW = 2.5
WINSORIZE_HIGH = 97.5

SIGNAL_FIELDS = [
    ("obv_trend", "score"),
    ("earnings_rank_score", None),
    ("institutional_flow_score", None),
    ("sentiment_score", None),
]

DEFAULT_COMPOSITE_WEIGHTS = {
    "obv_trend": 0.40,
    "earnings_rank_score": 0.30,
    "institutional_flow_score": 0.15,
    "sentiment_score": 0.10,
}


def _get_signal_score(sv: SignalVector, field_name: str, sub_attr: str | None) -> float:
    val = getattr(sv, field_name, 0.0)
    if sub_attr is not None and isinstance(val, SignalResult):
        return val.score
    if isinstance(val, (int, float)):
        return float(val)
    return 0.0


def _set_signal_score(sv: SignalVector, field_name: str, sub_attr: str | None, value: float) -> None:
    if sub_attr is not None:
        sr = getattr(sv, field_name)
        if isinstance(sr, SignalResult):
            sr.score = value
    else:
        setattr(sv, field_name, value)


def _winsorize(arr: np.ndarray, low_pct: float = 2.5, high_pct: float = 97.5) -> np.ndarray:
    low = np.percentile(arr, low_pct)
    high = np.percentile(arr, high_pct)
    return np.clip(arr, low, high)


def normalize_signals_cross_sectionally(
    signals: dict[str, SignalVector],
    sector_fn: Callable[[str], str],
) -> dict[str, SignalVector]:
    """
    Normalize all active signals cross-sectionally with sector adjustment.

    Modifies SignalVectors in-place and returns the same dict.
    Skips normalization if fewer than MIN_CROSS_SECTION tickers.
    """
    tickers = list(signals.keys())
    n = len(tickers)

    if n < MIN_CROSS_SECTION:
        logger.debug("Cross-section too small (%d < %d) — skipping normalization", n, MIN_CROSS_SECTION)
        return signals

    sectors = {t: sector_fn(t) for t in tickers}

    for field_name, sub_attr in SIGNAL_FIELDS:
        raw_scores = np.array([_get_signal_score(signals[t], field_name, sub_attr) for t in tickers])

        if np.all(raw_scores == 0.0):
            continue

        # Subtract sector mean
        sector_means = {}
        for i, t in enumerate(tickers):
            sec = sectors[t]
            if sec not in sector_means:
                sec_mask = np.array([sectors[tt] == sec for tt in tickers])
                sector_means[sec] = np.mean(raw_scores[sec_mask])

        adjusted = np.array([raw_scores[i] - sector_means[sectors[t]] for i, t in enumerate(tickers)])

        # Winsorize
        adjusted = _winsorize(adjusted, WINSORIZE_LOW, WINSORIZE_HIGH)

        # Z-score
        std = np.std(adjusted)
        if std < 1e-8:
            normalized = np.zeros(n)
        else:
            mean = np.mean(adjusted)
            normalized = (adjusted - mean) / std

        # Scale to [-1, +1]
        normalized = np.clip(normalized / 3.0, -1.0, 1.0)

        # Write back
        for i, t in enumerate(tickers):
            _set_signal_score(signals[t], field_name, sub_attr, float(normalized[i]))

    return signals


def compute_normalized_composite(
    sv: SignalVector,
    weights: dict[str, float] | None = None,
) -> float:
    """
    Build composite score from (normalized) signal fields.
    Uses weighted average of available signals.
    """
    if weights is None:
        weights = DEFAULT_COMPOSITE_WEIGHTS

    total = 0.0
    total_w = 0.0

    for signal_name, weight in weights.items():
        val = getattr(sv, signal_name, 0.0)
        if isinstance(val, SignalResult):
            score = val.score
        elif isinstance(val, (int, float)):
            score = float(val)
        else:
            score = 0.0

        total += score * weight
        total_w += weight

    if total_w > 0:
        return float(np.clip(total / total_w, -1.0, 1.0))
    return 0.0
