"""
Kalshi REST client — public market data only (no auth required).

All endpoints are read-only. Responses cached to disk keyed by
series + date so backtests and repeated intraday calls don't hit
the network.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
DEFAULT_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".kalshi_cache")

KalshiMarket = dict[str, Any]


class KalshiClient:
    def __init__(self, cache_dir: str = DEFAULT_CACHE_DIR):
        os.makedirs(cache_dir, exist_ok=True)
        self._cache_dir = cache_dir
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "ai-financial-analyst/1.0"

    def get_markets(
        self,
        series_ticker: str,
        status: str = "open",
        _date_override: Optional[str] = None,
    ) -> list[KalshiMarket]:
        """Return open markets for a series, with yes_prob (0-1) added."""
        today = _date_override or date.today().isoformat()
        cache_key = f"{series_ticker}_{today}.json"
        cache_path = os.path.join(self._cache_dir, cache_key)

        if os.path.exists(cache_path):
            with open(cache_path) as f:
                return json.load(f)

        raw = self._fetch_markets(series_ticker=series_ticker, status=status)
        markets = [self._enrich(m) for m in raw]

        with open(cache_path, "w") as f:
            json.dump(markets, f)

        return markets

    def get_event_market(
        self, event_ticker: str, _date_override: Optional[str] = None
    ) -> list[KalshiMarket]:
        """Return markets for a specific event ticker."""
        today = _date_override or date.today().isoformat()
        cache_key = f"event_{event_ticker}_{today}.json"
        cache_path = os.path.join(self._cache_dir, cache_key)

        if os.path.exists(cache_path):
            with open(cache_path) as f:
                return json.load(f)

        params = {"event_ticker": event_ticker, "status": "open", "limit": 50}
        try:
            r = self._session.get(f"{BASE_URL}/markets", params=params, timeout=10)
            r.raise_for_status()
            raw = r.json().get("markets", [])
        except Exception as exc:
            logger.warning("Kalshi event fetch failed for %s: %s", event_ticker, exc)
            return []

        markets = [self._enrich(m) for m in raw]
        with open(cache_path, "w") as f:
            json.dump(markets, f)
        return markets

    def _fetch_markets(self, series_ticker: str, status: str) -> list[dict]:
        params = {"series_ticker": series_ticker, "status": status, "limit": 200}
        try:
            r = self._session.get(f"{BASE_URL}/markets", params=params, timeout=10)
            r.raise_for_status()
            return r.json().get("markets", [])
        except Exception as exc:
            logger.warning("Kalshi fetch failed for %s: %s", series_ticker, exc)
            return []

    @staticmethod
    def _enrich(m: dict) -> KalshiMarket:
        """Add yes_prob (0-1 float) derived from yes_bid (0-100 int)."""
        m = dict(m)
        m["yes_prob"] = m.get("yes_bid", 0) / 100.0
        return m
