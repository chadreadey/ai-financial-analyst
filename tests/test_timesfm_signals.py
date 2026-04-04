import pytest
from quant.timesfm.signals import extract_signals


def _make_quantiles(p50_vals):
    p10 = [v * 0.95 for v in p50_vals]
    p90 = [v * 1.05 for v in p50_vals]
    return {"p10": p10, "p50": p50_vals, "p90": p90}


def test_bullish_trend():
    p50 = [100 + i for i in range(10)]
    signals = extract_signals(100.0, p50, _make_quantiles(p50))
    assert signals["trend_direction"] == "bullish"
    assert signals["momentum_score"] > 0


def test_neutral_trend():
    p50 = [100.0] * 10
    signals = extract_signals(100.0, p50, _make_quantiles(p50))
    assert signals["trend_direction"] == "neutral"
    assert abs(signals["momentum_score"]) < 0.001


def test_bearish_trend():
    p50 = [100 - i for i in range(10)]
    signals = extract_signals(100.0, p50, _make_quantiles(p50))
    assert signals["trend_direction"] == "bearish"
    assert signals["downside_risk_pct"] < 0


def test_confidence_band_length():
    p50 = list(range(100, 110))
    signals = extract_signals(100.0, p50, _make_quantiles(p50))
    assert len(signals["confidence_band"]) == 10
    assert signals["confidence_band"][0]["step"] == 1
