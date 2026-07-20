"""Tiingo REST client with per-run thread-safe cache."""

import logging
import threading
from typing import Any, Dict, List

import requests

logger = logging.getLogger(__name__)


_REQUIRED_EOD_FIELDS = ("adjClose", "adjHigh", "adjLow", "adjOpen", "adjVolume", "close", "date")


def _validate_eod_bar(bar: dict, symbol: str) -> dict:
    """Log warning if required EOD fields are missing. Returns bar unchanged."""
    missing = [k for k in _REQUIRED_EOD_FIELDS if k not in bar]
    if missing:
        logger.warning(
            "schema: eod_bar response for %s missing fields: %s", symbol, ", ".join(missing)
        )
    return bar


class TiingoClient:
    def __init__(self, api_key: str) -> None:
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Token {api_key}"

    def get_quote(self, symbol: str) -> dict:
        endpoint = f"tiingo/daily/{symbol}/prices"
        try:
            resp = self._session.get(
                f"https://api.tiingo.com/{endpoint}",
                timeout=(5, 15),
            )
            if resp.status_code >= 500:
                resp = self._session.get(
                    f"https://api.tiingo.com/{endpoint}",
                    timeout=(5, 15),
                )
            resp.raise_for_status()
            data = resp.json()
            return data[0] if data else {}
        except requests.ConnectionError:
            try:
                resp = self._session.get(
                    f"https://api.tiingo.com/{endpoint}",
                    timeout=(5, 15),
                )
                resp.raise_for_status()
                data = resp.json()
                return data[0] if data else {}
            except Exception as exc:
                logger.debug("tiingo %s failed: %s", endpoint, exc, exc_info=True)
                return {}
        except Exception as exc:
            logger.debug("tiingo %s failed: %s", endpoint, exc, exc_info=True)
            return {}

    def get_meta(self, symbol: str) -> dict:
        endpoint = f"tiingo/daily/{symbol}"
        try:
            resp = self._session.get(
                f"https://api.tiingo.com/{endpoint}",
                timeout=(5, 15),
            )
            if resp.status_code >= 500:
                resp = self._session.get(
                    f"https://api.tiingo.com/{endpoint}",
                    timeout=(5, 15),
                )
            resp.raise_for_status()
            return resp.json()
        except requests.ConnectionError:
            try:
                resp = self._session.get(
                    f"https://api.tiingo.com/{endpoint}",
                    timeout=(5, 15),
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                logger.debug("tiingo %s failed: %s", endpoint, exc, exc_info=True)
                return {}
        except Exception as exc:
            logger.debug("tiingo %s failed: %s", endpoint, exc, exc_info=True)
            return {}

    def get_fundamentals_statements(
        self, symbol: str, start_date: str = "2020-01-01"
    ) -> list[dict]:
        endpoint = f"tiingo/fundamentals/{symbol}/statements"
        try:
            resp = self._session.get(
                f"https://api.tiingo.com/{endpoint}",
                params={"startDate": start_date},
                timeout=(5, 30),
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.debug("tiingo %s failed: %s", endpoint, exc)
            return []

    def get_fundamentals_daily(self, symbol: str, start_date: str = "2020-01-01") -> list[dict]:
        endpoint = f"tiingo/fundamentals/{symbol}/daily"
        try:
            resp = self._session.get(
                f"https://api.tiingo.com/{endpoint}",
                params={"startDate": start_date},
                timeout=(5, 30),
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.debug("tiingo %s failed: %s", endpoint, exc)
            return []

    def get_eod_history(self, symbol: str, start_date: str) -> list[dict]:
        endpoint = f"tiingo/daily/{symbol}/prices"
        try:
            resp = self._session.get(
                f"https://api.tiingo.com/{endpoint}",
                params={"startDate": start_date},
                timeout=(5, 15),
            )
            if resp.status_code >= 500:
                resp = self._session.get(
                    f"https://api.tiingo.com/{endpoint}",
                    params={"startDate": start_date},
                    timeout=(5, 15),
                )
            resp.raise_for_status()
            bars = resp.json()
            return [_validate_eod_bar(b, symbol) for b in bars]
        except requests.ConnectionError:
            try:
                resp = self._session.get(
                    f"https://api.tiingo.com/{endpoint}",
                    params={"startDate": start_date},
                    timeout=(5, 15),
                )
                resp.raise_for_status()
                bars = resp.json()
                return [_validate_eod_bar(b, symbol) for b in bars]
            except Exception as exc:
                logger.debug("tiingo %s failed: %s", endpoint, exc, exc_info=True)
                return []
        except Exception as exc:
            logger.debug("tiingo %s failed: %s", endpoint, exc, exc_info=True)
            return []


class TiingoCache:
    """Per-run cache for Tiingo responses. Same two-lock pattern as YahooLookupCache."""

    def __init__(self, client: TiingoClient) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._quote_cache: Dict[str, dict] = {}
        self._meta_cache: Dict[str, dict] = {}
        self._history_cache: Dict[str, list] = {}

    def get_quote(self, symbol: str) -> dict:
        sym = symbol.upper()
        with self._lock:
            cached = self._quote_cache.get(sym)
            if cached is not None:
                return dict(cached)

        result = self._client.get_quote(sym)

        with self._lock:
            self._quote_cache[sym] = result
            return dict(result)

    def get_meta(self, symbol: str) -> dict:
        sym = symbol.upper()
        with self._lock:
            cached = self._meta_cache.get(sym)
            if cached is not None:
                return dict(cached)

        result = self._client.get_meta(sym)

        with self._lock:
            self._meta_cache[sym] = result
            return dict(result)

    def get_eod_history(self, symbol: str, start_date: str) -> list[dict]:
        sym = symbol.upper()
        key = f"{sym}:{start_date}"
        with self._lock:
            cached = self._history_cache.get(key)
            if cached is not None:
                return list(cached)

        result = self._client.get_eod_history(sym, start_date)

        with self._lock:
            self._history_cache[key] = result
            return list(result)
