import json
import os
import pytest
import responses as resp_mock

from quant.kalshi_client import KalshiClient, KalshiMarket

BASE = "https://api.elections.kalshi.com/trade-api/v2"


@pytest.fixture
def client(tmp_path):
    return KalshiClient(cache_dir=str(tmp_path))


@resp_mock.activate
def test_get_markets_by_series_parses_yes_bid(client):
    resp_mock.add(
        resp_mock.GET,
        f"{BASE}/markets",
        json={
            "markets": [
                {
                    "ticker": "FED-25MAY-B525",
                    "event_ticker": "FED-25MAY",
                    "title": "Fed Funds 5.25% at May meeting",
                    "yes_bid": 72,
                    "yes_ask": 74,
                    "volume": 15000,
                    "open_interest": 42000,
                    "close_time": "2026-05-07T18:00:00Z",
                    "status": "open",
                }
            ],
            "cursor": "",
        },
        status=200,
    )
    markets = client.get_markets(series_ticker="FED")
    assert len(markets) == 1
    m = markets[0]
    assert m["ticker"] == "FED-25MAY-B525"
    assert m["yes_prob"] == pytest.approx(0.72)


@resp_mock.activate
def test_get_markets_caches_to_disk(client, tmp_path):
    resp_mock.add(
        resp_mock.GET,
        f"{BASE}/markets",
        json={"markets": [], "cursor": ""},
        status=200,
    )
    client.get_markets(series_ticker="FED")
    # Second call must NOT hit network (responses would raise ConnectionError)
    resp_mock.reset()
    result = client.get_markets(series_ticker="FED")
    assert result == []


import requests as _requests

@resp_mock.activate
def test_get_markets_returns_empty_on_network_error(client):
    resp_mock.add(
        resp_mock.GET,
        f"{BASE}/markets",
        body=_requests.exceptions.ConnectionError(),
    )
    result = client.get_markets(series_ticker="FED")
    assert result == []


def test_get_series_for_equity_returns_earn_markets(client, tmp_path):
    # Preload cache with a fake EARN-AAPL market
    cache_file = tmp_path / "EARN_2026-04-15.json"
    cache_file.write_text(
        json.dumps([{"ticker": "EARN-AAPL-Q1", "yes_prob": 0.61, "series": "EARN"}])
    )
    markets = client.get_markets(series_ticker="EARN", _date_override="2026-04-15")
    assert markets[0]["ticker"] == "EARN-AAPL-Q1"
