from quant.timesfm.enrichment import format_price_signals, format_eps_signals


def _sample_signals():
    return {
        "trend_direction": "bullish",
        "momentum_score": 0.42,
        "volatility_proxy": 0.08,
        "downside_risk_pct": -4.2,
        "upside_target": 234.50,
        "confidence_band": [
            {"step": i + 1, "p10": 218 + i, "p50": 221 + i, "p90": 224 + i}
            for i in range(10)
        ],
    }


def test_price_format_header():
    output = format_price_signals("AAPL", _sample_signals())
    assert output.startswith("=== TimesFM Price Forecast")


def test_price_format_contains_trend():
    output = format_price_signals("AAPL", _sample_signals())
    assert "Trend Direction:" in output


def test_price_format_empty():
    assert format_price_signals("AAPL", {}) == ""
    assert format_price_signals("AAPL", None) == ""


def test_eps_format_header():
    output = format_eps_signals("AAPL", _sample_signals())
    assert output.startswith("=== TimesFM EPS Forecast")


def test_eps_format_empty():
    assert format_eps_signals("AAPL", {}) == ""
    assert format_eps_signals("AAPL", None) == ""
