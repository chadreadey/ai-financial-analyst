"""
Price Regression Signal — R²-filtered OLS trend.

Fits log(price) ~ time-index via OLS over a rolling window.
Only emits a signal when R² >= r2_threshold (default 0.6), indicating
the trend is statistically reliable. Slope converted to [-1, +1] via tanh.

Returns 0.0 when trend is not reliable or data is insufficient.
Pattern: mirrors compute_price_momentum_scores() in additional_signals.py.

Integration: this signal enters the cross-sectional normalization pipeline
(SIGNAL_FIELDS in cross_sectional.py), NOT post-normalization blending.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import linregress

logger = logging.getLogger(__name__)


def compute_price_regression_score(
    prices: pd.Series,
    window: int = 60,
    r2_threshold: float = 0.6,
) -> float:
    """
    Returns a signal in [-1, +1] if price trend is statistically significant
    (R² >= r2_threshold), else 0.0.

    Uses log(price) regression so slope is daily % return.
    Scaling: tanh(slope * window * 5) — a 1%/day trend over 60 days maps to ~tanh(3) = 0.99.
    """
    if len(prices) < window:
        return 0.0
    raw = prices.iloc[-window:].values.astype(float)
    if np.any(np.isnan(raw)) or np.any(raw <= 0):
        return 0.0
    series = np.log(raw)
    x = np.arange(len(series), dtype=float)
    slope, _, r_value, _, _ = linregress(x, series)
    r2 = r_value**2
    if r2 < r2_threshold:
        return 0.0
    raw = np.tanh(slope * window * 5.0)
    return float(np.clip(raw, -1.0, 1.0))


def compute_price_regression_scores(
    universe_data: dict,
    reb_date: date,
    window: int = 60,
    r2_threshold: float = 0.6,
) -> dict[str, float]:
    """
    Compute price regression scores for all tickers in universe_data.

    Args:
        universe_data: dict keyed by ticker. Each value is either:
                       - a dict with a 'price_history' key → pd.DataFrame with 'close' column
                       - a pd.DataFrame directly with a 'close' column
        reb_date:      rebalance date — only prices on or before this date are used.
        window:        rolling window in trading days (default: 60).
        r2_threshold:  minimum R² to emit a non-zero signal (default: 0.6).

    Returns:
        dict mapping ticker -> float score in [-1, +1].
    """
    scores: dict[str, float] = {}

    for ticker, data in universe_data.items():
        try:
            if isinstance(data, dict):
                df = data.get("price_history")
            else:
                df = data

            if df is None or not isinstance(df, pd.DataFrame):
                scores[ticker] = 0.0
                continue

            available = df[df.index <= pd.Timestamp(reb_date)]
            if "close" not in available.columns:
                scores[ticker] = 0.0
                continue

            prices = available["close"].dropna()
            scores[ticker] = compute_price_regression_score(
                prices, window=window, r2_threshold=r2_threshold
            )
        except Exception as exc:
            logger.warning("Regression score failed for %s: %s", ticker, exc)
            scores[ticker] = 0.0

    return scores
