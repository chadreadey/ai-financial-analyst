import pandas as pd
import numpy as np
import pytest
from quant.backtest import BacktestConfig, RegimeState


def _make_vix_series(values: list, start="2023-01-01") -> pd.Series:
    dates = pd.date_range(start, periods=len(values), freq="B")
    return pd.Series(values, index=dates, name="close")


def test_backtest_config_has_vix_smoothing_fields():
    c = BacktestConfig()
    assert hasattr(c, "vix_smoothing")
    assert c.vix_smoothing is False
    assert c.vix_sma_window == 50
    assert c.vix_ratio_threshold == 1.5
    assert c.vix_reentry_threshold == 1.2
    assert c.vix_persistence_periods == 2


def test_regime_state_has_vix_ratio():
    s = RegimeState()
    assert hasattr(s, "vix_ratio")
    assert s.vix_ratio is None
    assert s.vix_persistence_count == 0
    assert s.copper_bearish is False


def test_vix_ratio_above_threshold_with_persistence():
    """VIX at 1.6x its 50d SMA for 2+ periods → risk_off should activate."""
    from quant.backtest import _compute_vix_regime

    sma_vals = [20.0] * 49
    vix_series = _make_vix_series(sma_vals + [32.0])
    ratio, risk_off, cautious = _compute_vix_regime(
        vix_series,
        current_vix=32.0,
        config=BacktestConfig(vix_smoothing=True),
        prev_persistence_count=1,
    )
    assert ratio == pytest.approx(1.6, rel=0.05)
    assert risk_off is True
    assert cautious is True


def test_vix_ratio_below_persistence_threshold():
    """Ratio above threshold but only 1 period (need 2) → not yet risk_off."""
    from quant.backtest import _compute_vix_regime

    sma_vals = [20.0] * 49
    vix_series = _make_vix_series(sma_vals + [32.0])
    ratio, risk_off, cautious = _compute_vix_regime(
        vix_series,
        current_vix=32.0,
        config=BacktestConfig(vix_smoothing=True),
        prev_persistence_count=0,
    )
    assert ratio == pytest.approx(1.6, rel=0.05)
    assert risk_off is False
    assert cautious is True


def test_vix_hysteresis_reentry():
    """Once in risk-off, ratio must drop below 1.2 to re-enter risk-on."""
    from quant.backtest import _compute_vix_regime

    sma_vals = [20.0] * 49
    vix_series = _make_vix_series(sma_vals + [26.0])  # ratio=1.3, between thresholds
    ratio, risk_off, cautious = _compute_vix_regime(
        vix_series,
        current_vix=26.0,
        config=BacktestConfig(vix_smoothing=True),
        prev_persistence_count=2,  # was in risk-off
    )
    assert ratio == pytest.approx(1.3, rel=0.05)
    assert risk_off is False
    assert cautious is True  # still cautious (between 1.2 and 1.5)


def test_raw_mode_unchanged():
    """vix_smoothing=False → raw threshold logic, ratio=None."""
    from quant.backtest import _compute_vix_regime

    vix_series = _make_vix_series([20.0] * 50)
    ratio, risk_off, cautious = _compute_vix_regime(
        vix_series,
        current_vix=36.0,
        config=BacktestConfig(vix_smoothing=False, vix_risk_off_threshold=35),
        prev_persistence_count=0,
    )
    assert ratio is None
    assert risk_off is True


def test_insufficient_vix_data_falls_back():
    """Fewer than 25 VIX observations → ratio=None, uses raw threshold."""
    from quant.backtest import _compute_vix_regime

    vix_series = _make_vix_series([20.0] * 10)
    ratio, risk_off, cautious = _compute_vix_regime(
        vix_series,
        current_vix=36.0,
        config=BacktestConfig(vix_smoothing=True, vix_risk_off_threshold=35),
        prev_persistence_count=0,
    )
    assert ratio is None
    assert risk_off is True
