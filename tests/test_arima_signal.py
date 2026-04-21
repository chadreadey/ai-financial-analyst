"""
Unit tests for quant/arima_signal.py.

Run with:
    cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
    python -m pytest tests/test_arima_signal.py -v --noconftest
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quant.arima_signal import (
    compute_arima_forecast_score,
    compute_arima_forecast_scores,
)


def test_arima_high_vol_returns_zero():
    """When 20d realized vol exceeds threshold, signal must be 0.0."""
    np.random.seed(42)
    returns = np.random.randn(80) * 0.05  # ~80% annualized vol
    prices = pd.Series(100.0 * np.exp(returns.cumsum()))
    score = compute_arima_forecast_score(prices, lookback=60, horizon=5, vol_threshold=0.25)
    assert score == 0.0, f"Expected 0.0 for high-vol regime, got {score}"


def test_arima_insufficient_data_returns_zero():
    """Fewer prices than lookback + horizon must return 0.0 without raising."""
    prices = pd.Series(np.linspace(90.0, 100.0, 50))  # 50 < 60 + 5
    score = compute_arima_forecast_score(prices, lookback=60, horizon=5, vol_threshold=0.25)
    assert score == 0.0, f"Expected 0.0 for insufficient data, got {score}"


def test_arima_stable_regime_returns_float_in_unit_interval():
    """Low-vol smooth uptrend — ARIMA should fit and return a valid float."""
    np.random.seed(42)
    daily_returns = 0.001 + np.random.randn(75) * 0.003
    prices = pd.Series(100.0 * np.exp(daily_returns.cumsum()))
    score = compute_arima_forecast_score(prices, lookback=60, horizon=5, vol_threshold=0.25)
    assert isinstance(score, float), f"Score must be float, got {type(score)}"
    assert -1.0 <= score <= 1.0, f"Score {score} out of [-1, 1]"


def test_arima_clips_to_unit_interval():
    """Score must never exceed [-1, +1] regardless of forecast magnitude."""
    np.random.seed(0)
    daily_returns = np.random.randn(75) * 0.001
    prices = pd.Series(100.0 * np.exp(daily_returns.cumsum()))
    score = compute_arima_forecast_score(prices, lookback=60, horizon=5, vol_threshold=1.0)
    assert -1.0 <= score <= 1.0, f"Score {score} out of [-1, 1]"


def test_arima_nan_prices_returns_zero():
    """Price series containing NaN must return 0.0 without raising."""
    prices = pd.Series([100.0, 101.0, np.nan] + [102.0] * 70)
    score = compute_arima_forecast_score(prices, lookback=60, horizon=5, vol_threshold=1.0)
    assert score == 0.0, f"Expected 0.0 for NaN prices, got {score}"


def test_arima_constant_prices_returns_zero_or_valid():
    """Constant price series may cause ARIMA to fail — must return 0.0, not raise."""
    prices = pd.Series([100.0] * 75)
    score = compute_arima_forecast_score(prices, lookback=60, horizon=5, vol_threshold=1.0)
    # Constant prices may pass vol gate (zero vol < 1.0) but ARIMA may fail to fit
    # Either 0.0 (fit failure) or a valid float in [-1, 1] is acceptable
    assert isinstance(score, float)
    assert -1.0 <= score <= 1.0, f"Score {score} out of bounds"


def test_arima_scores_wrapper_returns_dict():
    """Wrapper must return dict; high-vol ticker gated to 0.0."""
    import datetime

    np.random.seed(42)
    idx = pd.date_range("2024-01-01", periods=100, freq="B")

    r1 = 0.001 + np.random.randn(100) * 0.003
    df_stable = pd.DataFrame({"close": 100.0 * np.exp(r1.cumsum())}, index=idx)

    r2 = np.random.randn(100) * 0.05
    df_volatile = pd.DataFrame({"close": 100.0 * np.exp(r2.cumsum())}, index=idx)

    universe_data = {
        "AAPL": {"price_history": df_stable},
        "TSLA": {"price_history": df_volatile},
    }

    reb_date = datetime.date(2024, 6, 30)
    result = compute_arima_forecast_scores(universe_data, reb_date, vol_threshold=0.25)

    assert isinstance(result, dict)
    assert set(result.keys()) == {"AAPL", "TSLA"}
    for ticker, score in result.items():
        assert isinstance(score, float)
        assert -1.0 <= score <= 1.0, f"Score for {ticker} out of [-1, 1]: {score}"
    assert result["TSLA"] == 0.0, f"Expected TSLA=0.0 (high vol gated), got {result['TSLA']}"
