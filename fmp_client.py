"""FMP (Financial Modeling Prep) REST client with per-run thread-safe cache."""

import logging
import threading
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class FMPClient:
    BASE = "https://financialmodelingprep.com"

    def __init__(self, api_key: str) -> None:
        self._session = requests.Session()
        self._api_key = api_key
        self._call_count = 0
        self._call_lock = threading.Lock()

    @property
    def call_count(self) -> int:
        return self._call_count

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        merged = dict(params) if params else {}
        merged["apikey"] = self._api_key
        with self._call_lock:
            self._call_count += 1
            count = self._call_count
        if count == 200:
            logger.warning("FMP call count reached %d", count)
        elif count == 250:
            logger.error("FMP call count reached %d", count)
        resp = self._session.get(
            f"{self.BASE}{path}", params=merged, timeout=(5, 15),
        )
        resp.raise_for_status()
        return resp.json()

    def get_quote(self, symbol: str) -> dict:
        try:
            data = self._get("/stable/quote", {"symbol": symbol})
            row = data[0] if data else {}
            if row:
                row["marketCap"] = int(row.get("marketCap") or 0)
                pe = row.get("pe")
                if pe is None or pe == 0 or pe < 0:
                    row["pe"] = None
            return row
        except Exception as exc:
            logger.debug("fmp quote/%s failed: %s", symbol, exc, exc_info=True)
            return {}

    def get_key_metrics(self, symbol: str) -> dict:
        try:
            data = self._get("/stable/key-metrics-ttm", {"symbol": symbol})
            return data[0] if data else {}
        except Exception as exc:
            logger.debug("fmp key-metrics-ttm/%s failed: %s", symbol, exc, exc_info=True)
            return {}

    def get_analyst_estimates(self, symbol: str, limit: int = 4) -> list[dict]:
        try:
            return self._get(
                "/stable/analyst-estimates",
                {"symbol": symbol, "period": "annual", "limit": limit},
            )
        except Exception as exc:
            logger.debug("fmp analyst-estimates/%s failed: %s", symbol, exc, exc_info=True)
            return []

    def get_price_target(self, symbol: str) -> dict:
        try:
            data = self._get("/stable/price-target-summary", {"symbol": symbol})
            return data[0] if data else {}
        except Exception as exc:
            logger.debug("fmp price-target-summary/%s failed: %s", symbol, exc, exc_info=True)
            return {}

    def get_earnings_surprises(self, symbol: str, limit: int = 4) -> list[dict]:
        try:
            return self._get(
                "/stable/earnings-calendar",
                {"symbol": symbol},
            )
        except Exception as exc:
            logger.debug("fmp earnings-calendar/%s failed: %s", symbol, exc, exc_info=True)
            return []

    def get_income_statement_quarterly(self, symbol: str, limit: int = 5) -> list[dict]:
        try:
            return self._get(
                "/stable/income-statement",
                {"symbol": symbol, "period": "quarter", "limit": limit},
            )
        except Exception as exc:
            logger.debug("fmp income-statement (Q)/%s failed: %s", symbol, exc, exc_info=True)
            return []

    def get_balance_sheet_quarterly(self, symbol: str, limit: int = 5) -> list[dict]:
        try:
            return self._get(
                "/stable/balance-sheet-statement",
                {"symbol": symbol, "period": "quarter", "limit": limit},
            )
        except Exception as exc:
            logger.debug("fmp balance-sheet (Q)/%s failed: %s", symbol, exc, exc_info=True)
            return []

    def get_cash_flow_quarterly(self, symbol: str, limit: int = 5) -> list[dict]:
        try:
            return self._get(
                "/stable/cash-flow-statement",
                {"symbol": symbol, "period": "quarter", "limit": limit},
            )
        except Exception as exc:
            logger.debug("fmp cash-flow (Q)/%s failed: %s", symbol, exc, exc_info=True)
            return []

    def get_grades_summary(self, symbol: str) -> list[dict]:
        try:
            return self._get("/stable/grades-consensus", {"symbol": symbol})
        except Exception as exc:
            logger.debug("fmp grades-consensus/%s failed: %s", symbol, exc, exc_info=True)
            return []

    def get_stock_news(self, symbol: str, limit: int = 5) -> list[dict]:
        try:
            return self._get(
                "/stable/news/stock",
                {"symbol": symbol, "limit": limit},
            )
        except Exception as exc:
            logger.debug("fmp stock-news/%s failed: %s", symbol, exc, exc_info=True)
            return []

    def get_dcf_valuation(self, symbol: str) -> dict:
        try:
            data = self._get("/stable/discounted-cash-flow", {"symbol": symbol})
            return data[0] if data else {}
        except Exception as exc:
            logger.debug("fmp dcf/%s failed: %s", symbol, exc, exc_info=True)
            return {}

    def get_institutional_holders(self, symbol: str) -> list[dict]:
        """Not available on free/starter FMP plans — returns [] gracefully."""
        return []


class FMPCache:
    """Per-run cache for FMP responses. Two-lock pattern like YahooLookupCache."""

    def __init__(self, client: FMPClient) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._quote_cache: Dict[str, dict] = {}
        self._metrics_cache: Dict[str, dict] = {}
        self._estimates_cache: Dict[str, list] = {}
        self._target_cache: Dict[str, dict] = {}
        self._surprises_cache: Dict[str, list] = {}
        self._income_q_cache: Dict[str, list] = {}
        self._balance_q_cache: Dict[str, list] = {}
        self._cashflow_q_cache: Dict[str, list] = {}
        self._grades_cache: Dict[str, list] = {}
        self._news_cache: Dict[str, list] = {}
        self._dcf_cache: Dict[str, dict] = {}
        self._holders_cache: Dict[str, list] = {}

    @property
    def call_count(self) -> int:
        return self._client.call_count

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

    def get_key_metrics(self, symbol: str) -> dict:
        sym = symbol.upper()
        with self._lock:
            cached = self._metrics_cache.get(sym)
            if cached is not None:
                return dict(cached)

        result = self._client.get_key_metrics(sym)

        with self._lock:
            self._metrics_cache[sym] = result
            return dict(result)

    def get_analyst_estimates(self, symbol: str, limit: int = 4) -> list[dict]:
        sym = symbol.upper()
        key = f"{sym}:{limit}"
        with self._lock:
            cached = self._estimates_cache.get(key)
            if cached is not None:
                return list(cached)

        result = self._client.get_analyst_estimates(sym, limit)

        with self._lock:
            self._estimates_cache[key] = result
            return list(result)

    def get_price_target(self, symbol: str) -> dict:
        sym = symbol.upper()
        with self._lock:
            cached = self._target_cache.get(sym)
            if cached is not None:
                return dict(cached)

        result = self._client.get_price_target(sym)

        with self._lock:
            self._target_cache[sym] = result
            return dict(result)

    def get_earnings_surprises(self, symbol: str, limit: int = 4) -> list[dict]:
        sym = symbol.upper()
        key = f"{sym}:{limit}"
        with self._lock:
            cached = self._surprises_cache.get(key)
            if cached is not None:
                return list(cached)

        result = self._client.get_earnings_surprises(sym, limit)

        with self._lock:
            self._surprises_cache[key] = result
            return list(result)

    def get_income_statement_quarterly(self, symbol: str, limit: int = 100) -> list[dict]:
        sym = symbol.upper()
        key = f"{sym}:{limit}"
        with self._lock:
            cached = self._income_q_cache.get(key)
            if cached is not None:
                return list(cached)

        result = self._client.get_income_statement_quarterly(sym, limit)

        with self._lock:
            self._income_q_cache[key] = result
            return list(result)

    def get_balance_sheet_quarterly(self, symbol: str, limit: int = 100) -> list[dict]:
        sym = symbol.upper()
        key = f"{sym}:{limit}"
        with self._lock:
            cached = self._balance_q_cache.get(key)
            if cached is not None:
                return list(cached)

        result = self._client.get_balance_sheet_quarterly(sym, limit)

        with self._lock:
            self._balance_q_cache[key] = result
            return list(result)

    def get_cash_flow_quarterly(self, symbol: str, limit: int = 100) -> list[dict]:
        sym = symbol.upper()
        key = f"{sym}:{limit}"
        with self._lock:
            cached = self._cashflow_q_cache.get(key)
            if cached is not None:
                return list(cached)

        result = self._client.get_cash_flow_quarterly(sym, limit)

        with self._lock:
            self._cashflow_q_cache[key] = result
            return list(result)

    def get_grades_summary(self, symbol: str) -> list[dict]:
        sym = symbol.upper()
        with self._lock:
            cached = self._grades_cache.get(sym)
            if cached is not None:
                return list(cached)
        result = self._client.get_grades_summary(sym)
        with self._lock:
            self._grades_cache[sym] = result
            return list(result)

    def get_stock_news(self, symbol: str, limit: int = 5) -> list[dict]:
        sym = symbol.upper()
        key = f"{sym}:{limit}"
        with self._lock:
            cached = self._news_cache.get(key)
            if cached is not None:
                return list(cached)
        result = self._client.get_stock_news(sym, limit)
        with self._lock:
            self._news_cache[key] = result
            return list(result)

    def get_dcf_valuation(self, symbol: str) -> dict:
        sym = symbol.upper()
        with self._lock:
            cached = self._dcf_cache.get(sym)
            if cached is not None:
                return dict(cached)
        result = self._client.get_dcf_valuation(sym)
        with self._lock:
            self._dcf_cache[sym] = result
            return dict(result)

    def get_institutional_holders(self, symbol: str) -> list[dict]:
        sym = symbol.upper()
        with self._lock:
            cached = self._holders_cache.get(sym)
            if cached is not None:
                return list(cached)
        result = self._client.get_institutional_holders(sym)
        with self._lock:
            self._holders_cache[sym] = result
            return list(result)
