import pytest
from unittest.mock import MagicMock

from quant.kalshi_signal import compute_macro_modifier, compute_event_divergence


def _mock_client(fed_prob=0.70, cpi_prob=0.55, jobs_prob=0.50):
    client = MagicMock()

    def get_markets(series_ticker, **kwargs):
        probs = {"FED": fed_prob, "CPI": cpi_prob, "JOBS": jobs_prob, "GDP": 0.50}
        return [{"ticker": f"{series_ticker}-TEST", "yes_prob": probs.get(series_ticker, 0.5)}]

    client.get_markets.side_effect = get_markets
    return client


def test_macro_modifier_dovish_fed_is_positive():
    client = _mock_client(fed_prob=0.85)
    score = compute_macro_modifier(client)
    assert score > 0.0


def test_macro_modifier_hawkish_fed_is_negative():
    client = _mock_client(fed_prob=0.15)
    score = compute_macro_modifier(client)
    assert score < 0.0


def test_macro_modifier_neutral_is_near_zero():
    client = _mock_client(fed_prob=0.50, cpi_prob=0.50, jobs_prob=0.50)
    score = compute_macro_modifier(client)
    assert abs(score) < 0.1


def test_macro_modifier_clipped_to_unit_interval():
    client = _mock_client(fed_prob=1.0, cpi_prob=1.0, jobs_prob=1.0)
    score = compute_macro_modifier(client)
    assert -1.0 <= score <= 1.0


def test_event_divergence_no_market_returns_zero():
    client = MagicMock()
    client.get_markets.return_value = []
    score = compute_event_divergence(client, ticker="AAPL", our_prob_beat=0.75)
    assert score == 0.0


def test_event_divergence_high_confidence_long():
    client = MagicMock()
    client.get_markets.return_value = [{"ticker": "EARN-AAPL-Q126", "yes_prob": 0.45}]
    score = compute_event_divergence(client, ticker="AAPL", our_prob_beat=0.80, threshold=0.20)
    assert score > 0.3


def test_event_divergence_below_threshold_returns_zero():
    client = MagicMock()
    client.get_markets.return_value = [{"ticker": "EARN-AAPL-Q126", "yes_prob": 0.52}]
    score = compute_event_divergence(client, ticker="AAPL", our_prob_beat=0.58, threshold=0.20)
    assert score == 0.0


def test_event_divergence_clipped_to_unit_interval():
    client = MagicMock()
    client.get_markets.return_value = [{"ticker": "EARN-AAPL", "yes_prob": 0.01}]
    score = compute_event_divergence(client, ticker="AAPL", our_prob_beat=1.0, threshold=0.20)
    assert -1.0 <= score <= 1.0


def test_macro_modifier_yes_prob_none_treated_as_neutral():
    """yes_prob=None market should not crash and should use neutral 0.5."""
    client = MagicMock()
    client.get_markets.return_value = [{"ticker": "FED-TEST", "yes_prob": None}]
    # Should not raise; returns some value in [-1, 1]
    score = compute_macro_modifier(client)
    assert -1.0 <= score <= 1.0


def test_macro_modifier_client_exception_returns_zero():
    """If all series fail, macro modifier returns 0.0."""
    client = MagicMock()
    client.get_markets.side_effect = ConnectionError("network down")
    score = compute_macro_modifier(client)
    assert score == 0.0


def test_event_divergence_yes_prob_none_returns_zero():
    """yes_prob=None market → treat as no market → return 0.0."""
    client = MagicMock()
    client.get_markets.return_value = [{"ticker": "EARN-AAPL-Q126", "yes_prob": None}]
    score = compute_event_divergence(client, ticker="AAPL", our_prob_beat=0.80)
    assert score == 0.0
