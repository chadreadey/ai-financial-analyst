"""Tests for YahooLookupCache."""

from unittest.mock import MagicMock, patch

from yahoo_cache import YahooLookupCache


def test_get_info_fetches_once_per_symbol():
    cache = YahooLookupCache()
    fake_info = {"marketCap": 100, "shortName": "TestCo"}

    mock_ticker = MagicMock()
    mock_ticker.info = fake_info

    with patch("yfinance.Ticker", return_value=mock_ticker) as yt:
        a = cache.get_info("abc")
        b = cache.get_info("abc")
        assert a == fake_info
        assert b == fake_info
        assert yt.call_count == 1


def test_get_info_uppercases_symbol():
    cache = YahooLookupCache()
    with patch("yfinance.Ticker") as yt:
        mock_ticker = MagicMock()
        mock_ticker.info = {"marketCap": 1}
        yt.return_value = mock_ticker
        cache.get_info("msft")
        cache.get_info("MSFT")
        assert yt.call_count == 1


def test_get_info_returns_empty_when_fallback_disabled(monkeypatch):
    """get_info() returns {} immediately when ENABLE_YAHOO_FALLBACK=false."""
    monkeypatch.setenv("ENABLE_YAHOO_FALLBACK", "false")
    from yahoo_cache import YahooLookupCache

    cache = YahooLookupCache()
    result = cache.get_info("AAPL")
    assert result == {}


# ── Bounded yfinance calls: a dead connection must not hang the run ─────────

import threading
import time

import pytest

import yahoo_cache
from yahoo_cache import YahooTimeout, call_with_timeout


class _HangingTicker:
    """Stands in for yf.Ticker whose network call never returns."""

    def __init__(self, release: threading.Event) -> None:
        self._release = release

    @property
    def info(self):
        self._release.wait()  # blocks until the test tears down
        return {"marketCap": 1}

    def history(self, *args, **kwargs):
        self._release.wait()
        raise RuntimeError("released")


@pytest.fixture
def hanging_ticker(monkeypatch):
    monkeypatch.setenv("YAHOO_TIMEOUT_SECONDS", "0.2")
    release = threading.Event()
    with patch("yfinance.Ticker", side_effect=lambda *a, **k: _HangingTicker(release)) as yt:
        yield yt
    release.set()  # let the abandoned worker threads finish


def test_call_with_timeout_returns_value_and_reraises():
    assert call_with_timeout(lambda: 42, timeout=1) == 42
    with pytest.raises(ValueError):
        call_with_timeout(lambda: (_ for _ in ()).throw(ValueError("boom")), timeout=1)


def test_hanging_info_times_out_and_frees_lock(hanging_ticker):
    cache = YahooLookupCache()
    start = time.monotonic()
    assert cache.get_info("KO") == {}
    assert time.monotonic() - start < 2.0
    assert not yahoo_cache._YF_GLOBAL_LOCK.locked()

    # A later lookup for another symbol is not stuck behind the dead one.
    start = time.monotonic()
    assert cache.get_info("PEP") == {}
    assert time.monotonic() - start < 2.0
    assert not yahoo_cache._YF_GLOBAL_LOCK.locked()

    # The timed-out symbol is cached as "no data", like other failures.
    calls = hanging_ticker.call_count
    assert cache.get_info("KO") == {}
    assert hanging_ticker.call_count == calls


def test_call_with_timeout_raises_on_hang():
    release = threading.Event()
    try:
        start = time.monotonic()
        with pytest.raises(YahooTimeout):
            call_with_timeout(release.wait, timeout=0.2, label="hang")
        assert time.monotonic() - start < 2.0
    finally:
        release.set()


def test_pattern_risk_metrics_degrade_on_hang(hanging_ticker, monkeypatch):
    from agents import pattern

    monkeypatch.setenv("ENABLE_TIINGO", "false")
    start = time.monotonic()
    assert pattern._compute_risk_metrics("KO") is None
    assert time.monotonic() - start < 2.0


def test_price_history_section_degrades_on_hang(hanging_ticker):
    import market_enrichment

    start = time.monotonic()
    assert market_enrichment._price_history_section("KO", YahooLookupCache()) == ("", [])
    assert time.monotonic() - start < 3.0
    assert not yahoo_cache._YF_GLOBAL_LOCK.locked()
