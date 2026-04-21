import pandas as pd
import numpy as np
import pytest
from quant.macro_signals import compute_copper_signal


def _copper_series(values: list, start="2018-01-01") -> pd.Series:
    """Monthly copper price series (PCOPPUSDM format)."""
    dates = pd.date_range(start, periods=len(values), freq="MS")
    return pd.Series(values, index=dates)


def test_near_high_bullish():
    """Copper within 5% of 12M high → bullish."""
    vals = [8000.0] * 12 + [7900.0]
    s = _copper_series(vals)
    price, dd, regime, score = compute_copper_signal(s, s.index[-1])
    assert regime == "bullish"
    assert score > 0


def test_new_12m_high():
    """Copper at new 12M high → score = +1.0."""
    vals = [7000.0] * 12 + [8500.0]
    s = _copper_series(vals)
    _, _, regime, score = compute_copper_signal(s, s.index[-1])
    assert regime == "bullish"
    assert score == pytest.approx(1.0)


def test_neutral_zone():
    """10% below 12M high → neutral."""
    vals = [8000.0] * 12 + [7200.0]
    s = _copper_series(vals)
    _, _, regime, score = compute_copper_signal(s, s.index[-1])
    assert regime == "neutral"
    assert score == pytest.approx(0.0)


def test_bearish_not_persistent():
    """17% below 12M high but prior month only 8% below → not yet bearish."""
    prior_vals = [8000.0] * 11 + [7360.0]   # prior: 8% below 8000
    current = 6640.0                          # current: 17% below 8000
    s = _copper_series(prior_vals + [current])
    _, _, regime, score = compute_copper_signal(s, s.index[-1])
    assert regime == "neutral"
    assert score > -0.5


def test_bearish_persistent():
    """17% below 12M high, prior month also 17% below → bearish."""
    vals = [8000.0] * 11 + [6640.0, 6640.0]
    s = _copper_series(vals)
    _, _, regime, score = compute_copper_signal(s, s.index[-1])
    assert regime == "bearish"
    assert score == pytest.approx(-0.5)


def test_crisis():
    """28% below 12M high, prior month also below → crisis."""
    vals = [8000.0] * 11 + [5800.0, 5760.0]
    s = _copper_series(vals)
    _, _, regime, score = compute_copper_signal(s, s.index[-1])
    assert regime == "crisis"
    assert score == pytest.approx(-1.0)


def test_insufficient_data():
    """Fewer than 13 observations → unknown, score 0."""
    s = _copper_series([8000.0] * 10)
    price, dd, regime, score = compute_copper_signal(s, s.index[-1])
    assert regime == "unknown"
    assert score == 0.0
    assert price is None
