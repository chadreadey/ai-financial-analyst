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
