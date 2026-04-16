"""
ARIMA Forecast Signal — short-term price forecast gated to stable vol regimes.

Fits ARIMA(1,1,1) on log-prices over a lookback window, forecasts `horizon`
days ahead, converts predicted return to a score in [-1, +1].

Gates: only fires when 20d realized volatility (annualized) < vol_threshold (default 0.25).
Above that threshold, ARIMA autocorrelation assumptions break down.

Returns 0.0 on any failure. Never raises.
statsmodels is already installed (used in quant/factor_attribution.py).

Integration: enters cross-sectional normalization pipeline (SIGNAL_FIELDS
in cross_sectional.py), not post-normalization blending.
"""

from __future__ import annotations

import logging
import warnings
from datetime import date

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_arima_forecast_score(
    prices: pd.Series,
    lookback: int = 60,
    horizon: int = 5,
    vol_threshold: float = 0.25,
    order: tuple = (1, 1, 1),
) -> float:
    """
    Returns a signal in [-1, +1] based on ARIMA(1,1,1) price forecast,
    or 0.0 if vol is too high or fit fails.

    Signal = tanh(forecast_return * 20):
      5% predicted move → tanh(1) ≈ 0.76
      10% predicted move → tanh(2) ≈ 0.96
    """
    from statsmodels.tsa.arima.model import ARIMA

    if len(prices) < lookback + horizon:
        return 0.0

    recent = prices.iloc[-(lookback + horizon):-horizon]
    raw = recent.values.astype(float)
    if np.any(np.isnan(raw)) or np.any(raw <= 0):
        return 0.0
    log_prices = np.log(raw)

    vol_window = log_prices[-20:]
    if len(vol_window) < 2:
        return 0.0
    returns = np.diff(vol_window)
    realized_vol = returns.std() * np.sqrt(252)
    if realized_vol >= vol_threshold:
        return 0.0

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = ARIMA(log_prices, order=order)
            fit = model.fit()
            forecast = fit.forecast(steps=horizon)
        predicted_log_price = forecast[-1]
        current_log_price = log_prices[-1]
        predicted_return = predicted_log_price - current_log_price
        raw = np.tanh(predicted_return * 20.0)
        return float(np.clip(raw, -1.0, 1.0))
    except Exception as exc:
        logger.debug("ARIMA fit failed: %s", exc)
        return 0.0


def compute_arima_forecast_scores(
    universe_data: dict,
    reb_date: date,
    lookback: int = 60,
    horizon: int = 5,
    vol_threshold: float = 0.25,
    order: tuple = (1, 1, 1),
) -> dict[str, float]:
    """
    Compute ARIMA forecast scores for all tickers in universe_data.

    Args:
        universe_data: dict keyed by ticker. Each value is either:
                       - a dict with a 'price_history' key → pd.DataFrame with 'close' column
                       - a pd.DataFrame directly with a 'close' column
        reb_date:      rebalance date — only prices on or before this date are used.
        lookback:      ARIMA training window in trading days (default: 60).
        horizon:       forecast horizon in days (default: 5).
        vol_threshold: max annualized realized vol to allow signal (default: 0.25).
        order:         ARIMA order tuple (default: (1, 1, 1)).

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
            scores[ticker] = compute_arima_forecast_score(
                prices,
                lookback=lookback,
                horizon=horizon,
                vol_threshold=vol_threshold,
                order=order,
            )
        except Exception as exc:
            logger.warning("ARIMA score failed for %s: %s", ticker, exc)
            scores[ticker] = 0.0

    return scores
