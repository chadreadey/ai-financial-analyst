"""
Finnhub REST client with thread-safe cache and disk persistence.

Provides company news, insider sentiment (MSPR), and earnings surprise data.
Free tier: 60 req/min, 1yr news history, 10+ yr insider/earnings history.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


# ── Schema Validation ────────────────────────────────────────────────

_REQUIRED_NEWS_FIELDS = ("headline", "datetime", "source")


def _validate_news_item(item: dict, symbol: str) -> dict:
    """Log warning if required news fields are missing. Returns item unchanged."""
    missing = [k for k in _REQUIRED_NEWS_FIELDS if k not in item]
    if missing:
        logger.warning("schema: news_item response for %s missing fields: %s", symbol, ", ".join(missing))
    return item


# ── REST Client ───────────────────────────────────────────────────────

class FinnhubClient:
    """Finnhub REST client. Uses query-param auth (avoids header casing issues)."""

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str) -> None:
        self._session = requests.Session()
        self._api_key = api_key

    def _get(self, endpoint: str, params: dict, timeout: tuple = (5, 15)) -> dict | list:
        params["token"] = self._api_key
        resp = self._session.get(
            f"{self.BASE_URL}/{endpoint}",
            params=params,
            timeout=timeout,
        )
        if resp.status_code == 429:
            logger.debug("Finnhub rate limit hit, sleeping 2s")
            time.sleep(2)
            resp = self._session.get(
                f"{self.BASE_URL}/{endpoint}",
                params=params,
                timeout=timeout,
            )
        resp.raise_for_status()
        return resp.json()

    def get_company_news(
        self, symbol: str, from_date: str, to_date: str,
    ) -> list[dict]:
        """
        Fetch company news articles.

        Args:
            symbol: Ticker (e.g. 'AAPL')
            from_date: 'YYYY-MM-DD'
            to_date: 'YYYY-MM-DD'

        Returns list of dicts with keys:
            id, category, datetime (unix), headline, summary, source, url, related
        """
        try:
            data = self._get("company-news", {
                "symbol": symbol,
                "from": from_date,
                "to": to_date,
            })
            return [_validate_news_item(item, symbol) for item in data]
        except Exception as exc:
            logger.debug("finnhub company-news %s failed: %s", symbol, exc, exc_info=True)
            return []

    def get_insider_sentiment(
        self, symbol: str, from_date: str, to_date: str,
    ) -> list[dict]:
        """
        Fetch monthly insider sentiment (MSPR).

        Returns list of dicts with keys: symbol, year, month, change, mspr
        MSPR in [-1, +1]: +1 = pure buying, -1 = pure selling.
        """
        try:
            data = self._get("stock/insider-sentiment", {
                "symbol": symbol,
                "from": from_date,
                "to": to_date,
            })
            return data.get("data", []) if isinstance(data, dict) else []
        except Exception as exc:
            logger.debug("finnhub insider-sentiment %s failed: %s", symbol, exc, exc_info=True)
            return []

    def get_economic_calendar(
        self, from_date: str, to_date: str,
    ) -> list[dict]:
        """
        Fetch economic calendar events (FOMC, CPI, NFP, GDP, etc.).

        Returns list of dicts with keys:
            country, event, estimate, actual, prev, time, unit, impact
        Impact: 'high', 'medium', 'low'.
        Historical depth: several years back.
        """
        try:
            data = self._get("calendar/economic", {
                "from": from_date,
                "to": to_date,
            })
            return data.get("economicCalendar", []) if isinstance(data, dict) else []
        except Exception as exc:
            logger.debug("finnhub economic-calendar failed: %s", exc, exc_info=True)
            return []

    def get_earnings_calendar(
        self, from_date: str, to_date: str,
    ) -> list[dict]:
        """
        Fetch earnings calendar (upcoming and past).

        Returns list of dicts with keys:
            date, epsActual, epsEstimate, hour, quarter, revenueActual,
            revenueEstimate, symbol, year
        """
        try:
            data = self._get("calendar/earnings", {
                "from": from_date,
                "to": to_date,
            })
            return data.get("earningsCalendar", []) if isinstance(data, dict) else []
        except Exception as exc:
            logger.debug("finnhub earnings-calendar failed: %s", exc, exc_info=True)
            return []

    def get_earnings_surprises(self, symbol: str, limit: int = 40) -> list[dict]:
        """
        Fetch earnings surprise history (~10 years at limit=40).

        Returns list of dicts with keys:
            actual, estimate, period, quarter, year, surprise, surprisePercent, symbol
        """
        try:
            return self._get("stock/earnings", {
                "symbol": symbol,
                "limit": limit,
            })
        except Exception as exc:
            logger.debug("finnhub earnings %s failed: %s", symbol, exc, exc_info=True)
            return []


# ── In-Memory Cache ───────────────────────────────────────────────────

class FinnhubCache:
    """Per-run thread-safe cache. Same two-lock pattern as TiingoCache."""

    def __init__(self, client: FinnhubClient) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._news_cache: Dict[str, list] = {}
        self._insider_cache: Dict[str, list] = {}
        self._earnings_cache: Dict[str, list] = {}

    def get_company_news(
        self, symbol: str, from_date: str, to_date: str,
    ) -> list[dict]:
        sym = symbol.upper()
        key = f"{sym}:{from_date}:{to_date}"
        with self._lock:
            cached = self._news_cache.get(key)
            if cached is not None:
                return list(cached)

        result = self._client.get_company_news(sym, from_date, to_date)

        with self._lock:
            self._news_cache[key] = result
            return list(result)

    def get_insider_sentiment(
        self, symbol: str, from_date: str, to_date: str,
    ) -> list[dict]:
        sym = symbol.upper()
        key = f"{sym}:{from_date}:{to_date}"
        with self._lock:
            cached = self._insider_cache.get(key)
            if cached is not None:
                return list(cached)

        result = self._client.get_insider_sentiment(sym, from_date, to_date)

        with self._lock:
            self._insider_cache[key] = result
            return list(result)

    def get_earnings_surprises(self, symbol: str, limit: int = 40) -> list[dict]:
        sym = symbol.upper()
        with self._lock:
            cached = self._earnings_cache.get(sym)
            if cached is not None:
                return list(cached)

        result = self._client.get_earnings_surprises(sym, limit)

        with self._lock:
            self._earnings_cache[sym] = result
            return list(result)


# ── Disk Cache ────────────────────────────────────────────────────────

class SentimentDiskCache:
    """
    Persistent JSON cache for Finnhub data, keyed by (ticker, from, to).

    Historical data is immutable (old news never changes), so cached files
    are valid forever. Only windows ending within 3 days of today are
    considered potentially stale and re-fetched.
    """

    def __init__(self, cache_dir: str = "") -> None:
        if not cache_dir:
            cache_dir = os.getenv(
                "SENTIMENT_CACHE_DIR",
                os.path.join(os.path.dirname(__file__), ".sentiment_cache"),
            )
        self._dir = cache_dir
        os.makedirs(self._dir, exist_ok=True)

    def _path(self, prefix: str, ticker: str, from_date: str, to_date: str) -> str:
        safe = f"{prefix}_{ticker}_{from_date}_{to_date}.json"
        return os.path.join(self._dir, safe)

    def _is_stale(self, to_date: str) -> bool:
        try:
            end = datetime.strptime(to_date, "%Y-%m-%d")
            return (datetime.now() - end).days <= 3
        except ValueError:
            return True

    # ── News ──

    def load_news(self, ticker: str, from_date: str, to_date: str) -> Optional[list[dict]]:
        path = self._path("news", ticker, from_date, to_date)
        if not os.path.exists(path):
            return None
        if self._is_stale(to_date):
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None

    def save_news(self, ticker: str, from_date: str, to_date: str, records: list[dict]) -> None:
        path = self._path("news", ticker, from_date, to_date)
        with open(path, "w") as f:
            json.dump(records, f)

    # ── Insider Sentiment ──

    def load_insider(self, ticker: str, from_date: str, to_date: str) -> Optional[list[dict]]:
        path = self._path("insider", ticker, from_date, to_date)
        if not os.path.exists(path):
            return None
        if self._is_stale(to_date):
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None

    def save_insider(self, ticker: str, from_date: str, to_date: str, records: list[dict]) -> None:
        path = self._path("insider", ticker, from_date, to_date)
        with open(path, "w") as f:
            json.dump(records, f)

    # ── Earnings ──

    def load_earnings(self, ticker: str) -> Optional[list[dict]]:
        path = os.path.join(self._dir, f"earnings_{ticker}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None

    def save_earnings(self, ticker: str, records: list[dict]) -> None:
        path = os.path.join(self._dir, f"earnings_{ticker}.json")
        with open(path, "w") as f:
            json.dump(records, f)


# ── Pre-fetch Helper ──────────────────────────────────────────────────

def prefetch_sentiment_cache(
    tickers: list[str],
    rebalance_dates: list,
    window_days: int = 30,
    client: Optional[FinnhubClient] = None,
    disk_cache: Optional[SentimentDiskCache] = None,
    rate_limit_sleep: float = 1.1,
) -> int:
    """
    Pre-populate sentiment disk cache for all (ticker, window) pairs.

    Call once before a full backtest to avoid rate-limit pauses during
    the main loop. Returns the number of API calls made.

    At 60 req/min with 1.1s sleep: 50 tickers x 120 months = ~110 minutes.
    """
    import pandas as pd

    if client is None:
        api_key = os.getenv("FINNHUB_API_KEY", "").strip()
        if not api_key:
            logger.warning("FINNHUB_API_KEY not set — skipping prefetch")
            return 0
        client = FinnhubClient(api_key)

    if disk_cache is None:
        disk_cache = SentimentDiskCache()

    # Deduplicate windows
    windows: set[tuple[str, str, str]] = set()
    for reb_date in rebalance_dates:
        if isinstance(reb_date, str):
            reb_date = pd.Timestamp(reb_date)
        from_date = (reb_date - timedelta(days=window_days)).strftime("%Y-%m-%d")
        to_date = reb_date.strftime("%Y-%m-%d")
        for ticker in tickers:
            windows.add((ticker.upper(), from_date, to_date))

    api_calls = 0
    total = len(windows)
    for i, (ticker, from_d, to_d) in enumerate(sorted(windows)):
        # Check disk cache
        cached = disk_cache.load_news(ticker, from_d, to_d)
        if cached is not None:
            continue

        if api_calls > 0 and api_calls % 50 == 0:
            logger.info("Prefetch progress: %d/%d windows, %d API calls", i, total, api_calls)

        news = client.get_company_news(ticker, from_d, to_d)
        disk_cache.save_news(ticker, from_d, to_d, news)
        api_calls += 1
        time.sleep(rate_limit_sleep)

    logger.info("Prefetch complete: %d API calls for %d windows", api_calls, total)
    return api_calls
