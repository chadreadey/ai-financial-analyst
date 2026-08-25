"""
Unit tests for quant/regression_signal.py.

Run with:
    cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
    python -m pytest tests/test_regression_signal.py -v --noconftest
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quant.regression_signal import (
    compute_price_regression_score,
    compute_price_regression_scores,
)


def test_regression_low_r2_returns_zero():
    """Random walk prices have R² near zero — signal must be suppressed."""
    np.random.seed(42)
    prices = pd.Series(100 + np.random.randn(100).cumsum())
    score = compute_price_regression_score(prices, window=60, r2_threshold=0.6)
    assert score == 0.0, f"Expected 0.0 for random walk, got {score}"


def test_regression_strong_uptrend_returns_positive():
    """Perfect linear uptrend → R²=1.0 → score should be well above 0.3."""
    prices = pd.Series(np.linspace(90.0, 110.0, 60))
    score = compute_price_regression_score(prices, window=60, r2_threshold=0.6)
    assert score > 0.3, f"Expected score > 0.3 for linear uptrend, got {score}"


def test_regression_strong_downtrend_returns_negative():
    """Perfect linear downtrend → R²=1.0 → score should be well below -0.3."""
    prices = pd.Series(np.linspace(110.0, 90.0, 60))
    score = compute_price_regression_score(prices, window=60, r2_threshold=0.6)
    assert score < -0.3, f"Expected score < -0.3 for linear downtrend, got {score}"


def test_regression_clips_to_unit_interval():
    """Score must always stay within [-1.0, +1.0] regardless of slope magnitude."""
    prices = pd.Series(np.linspace(1.0, 1_000_000.0, 60))
    score = compute_price_regression_score(prices, window=60, r2_threshold=0.0)
    assert -1.0 <= score <= 1.0, f"Score {score} out of [-1, 1]"

    prices_down = pd.Series(np.linspace(1_000_000.0, 1.0, 60))
    score_down = compute_price_regression_score(prices_down, window=60, r2_threshold=0.0)
    assert -1.0 <= score_down <= 1.0, f"Score {score_down} out of [-1, 1]"


def test_regression_insufficient_data_returns_zero():
    """Fewer prices than window → must return 0.0 without raising."""
    prices = pd.Series(np.linspace(90.0, 100.0, 30))
    score = compute_price_regression_score(prices, window=60, r2_threshold=0.6)
    assert score == 0.0, f"Expected 0.0 for insufficient data, got {score}"


def test_regression_scores_wrapper_returns_dict():
    """Wrapper must return a dict keyed by ticker with float values in [-1, 1]."""
    import datetime

    prices_up = pd.Series(
        np.linspace(90.0, 110.0, 120),
        index=pd.date_range("2024-01-01", periods=120, freq="B"),
    )
    df_up = pd.DataFrame({"close": prices_up})

    prices_flat = pd.Series(
        np.ones(120) * 100.0,
        index=pd.date_range("2024-01-01", periods=120, freq="B"),
    )
    df_flat = pd.DataFrame({"close": prices_flat})

    universe_data = {
        "AAPL": {"price_history": df_up},
        "MSFT": {"price_history": df_flat},
    }

    reb_date = datetime.date(2024, 6, 30)
    result = compute_price_regression_scores(universe_data, reb_date, window=60, r2_threshold=0.6)

    assert isinstance(result, dict)
    assert set(result.keys()) == {"AAPL", "MSFT"}
    for ticker, score in result.items():
        assert isinstance(score, float)
        assert -1.0 <= score <= 1.0, f"Score for {ticker} out of [-1, 1]: {score}"


def test_regression_scores_wrapper_handles_raw_dataframe():
    """Wrapper must also accept a raw DataFrame (not dict-wrapped) as ticker value."""
    import datetime

    prices_up = pd.Series(
        np.linspace(90.0, 110.0, 120),
        index=pd.date_range("2024-01-01", periods=120, freq="B"),
    )
    df_up = pd.DataFrame({"close": prices_up})

    # Pass the DataFrame directly, not wrapped in {"price_history": df}
    universe_data = {"AAPL": df_up}

    reb_date = datetime.date(2024, 6, 30)
    result = compute_price_regression_scores(universe_data, reb_date, window=60, r2_threshold=0.6)

    assert isinstance(result, dict)
    assert "AAPL" in result
    assert isinstance(result["AAPL"], float)
    assert -1.0 <= result["AAPL"] <= 1.0
