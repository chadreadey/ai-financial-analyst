"""
Tests for extended XGBoost feature columns: price_regression and arima_forecast.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.xgb_ranker import FEATURE_COLS


def test_feature_cols_include_regression_arima():
    assert "price_regression" in FEATURE_COLS
    assert "arima_forecast" in FEATURE_COLS
    assert len(FEATURE_COLS) == 12


def test_build_feature_matrix_has_new_cols():
    """build_feature_matrix sets price_regression and arima_forecast to 0.0."""
    from quant.xgb_features import build_feature_matrix

    # Minimal mock: 2 tickers, 65 daily rows (>60 required for signals)
    dates = pd.date_range("2023-01-01", periods=65, freq="B")
    np.random.seed(42)

    def make_df():
        close = 100 + np.cumsum(np.random.randn(65) * 0.5)
        return pd.DataFrame(
            {
                "close": close,
                "open": close * 0.999,
                "high": close * 1.005,
                "low": close * 0.995,
                "volume": np.random.randint(100_000, 500_000, size=65).astype(float),
            },
            index=dates,
        )

    tickers = [
        "AAPL",
        "MSFT",
        "GOOG",
        "AMZN",
        "META",
        "NVDA",
        "TSLA",
        "JPM",
        "BAC",
        "GS",
        "WMT",
    ]
    universe_data = {t: make_df() for t in tickers}
    # Use a single rebalance date (after 60 rows are available, with 1 future row)
    rebalance_dates = [dates[63]]

    fm = build_feature_matrix(
        universe_data=universe_data,
        rebalance_dates=rebalance_dates,
        forward_days=1,
    )

    assert "price_regression" in fm.columns, "price_regression column missing from feature matrix"
    assert "arima_forecast" in fm.columns, "arima_forecast column missing from feature matrix"
    assert (fm["price_regression"] == 0.0).all(), "price_regression should be 0.0 in offline build"
    assert (fm["arima_forecast"] == 0.0).all(), "arima_forecast should be 0.0 in offline build"


def test_feature_rows_include_regression_arima():
    """Feature dict built from SignalVector includes correct price_regression and arima_forecast values."""
    from quant.signals import SignalResult, SignalVector

    sv = SignalVector(
        sma_trend=SignalResult(0.0),
        mean_reversion_z=SignalResult(0.0),
        bollinger_pctb=SignalResult(0.0),
        rsi=SignalResult(0.0),
        obv_trend=SignalResult(0.0),
        atr_regime=SignalResult(0.0, metadata={"atr_pct": 0.01}),
        price_regression_score=0.42,
        arima_forecast_score=-0.15,
    )

    feature_dict = {
        "obv_trend": sv.obv_trend.score,
        "earnings": sv.earnings_rank_score,
        "inst_flow": sv.institutional_flow_score,
        "sentiment": sv.sentiment_score,
        "quality": sv.quality_score,
        "price_mom": sv.price_momentum_score,
        "insider": sv.insider_score,
        "event_timing": sv.event_timing_score,
        "atr_pct": sv.atr_regime.metadata.get("atr_pct", 0.0),
        "vix_level": 0.0,
        "price_regression": sv.price_regression_score,
        "arima_forecast": sv.arima_forecast_score,
    }

    assert feature_dict["price_regression"] == pytest.approx(0.42)
    assert feature_dict["arima_forecast"] == pytest.approx(-0.15)
    assert set(FEATURE_COLS) == set(feature_dict.keys()), (
        f"Feature dict keys {set(feature_dict.keys())} don't match FEATURE_COLS {set(FEATURE_COLS)}"
    )
