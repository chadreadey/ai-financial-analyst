"""
FMP fundamental data cache for backtesting.

Caches income statements, balance sheets, and analyst estimates to SQLite
so the backtest engine can compute ROA and earnings revision signals
without burning the 250 calls/day FMP free tier limit.

Usage:
    cache = FMPFundamentalCache()
    cache.prefetch(tickers=["AAPL", "MSFT", ...], fmp_client=client)

    # Later, in backtest (no API calls):
    income = cache.get_income_quarterly("AAPL")
    balance = cache.get_balance_quarterly("AAPL")
    estimates = cache.get_analyst_estimates("AAPL")
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from typing import Optional

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", ".fmp_cache.db")


class FMPFundamentalCache:
    """SQLite cache for FMP fundamental data."""

    def __init__(self, db_path: str = "") -> None:
        self._db_path = db_path or _DB_PATH
        self._ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS fmp_fundamentals (
                ticker      TEXT NOT NULL,
                data_type   TEXT NOT NULL,  -- 'income_q', 'balance_q', 'estimates', 'key_metrics'
                data_json   TEXT NOT NULL,
                updated_at  REAL NOT NULL,
                PRIMARY KEY (ticker, data_type)
            );
        """)
        conn.commit()
        conn.close()

    # Default TTL: 7 days for live analysis. Pass max_age_seconds=0 to disable (backtesting).
    DEFAULT_MAX_AGE = 7 * 24 * 3600  # 604800 seconds

    def _get(self, ticker: str, data_type: str, max_age_seconds: float = -1) -> Optional[list[dict]]:
        """Fetch cached data. Returns None if missing or stale.

        Args:
            max_age_seconds: Maximum age in seconds. 0 disables TTL (for backtests).
                             -1 (default) uses DEFAULT_MAX_AGE.
        """
        if max_age_seconds < 0:
            max_age_seconds = self.DEFAULT_MAX_AGE
        conn = self._conn()
        row = conn.execute(
            "SELECT data_json, updated_at FROM fmp_fundamentals WHERE ticker = ? AND data_type = ?",
            (ticker.upper(), data_type),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        if max_age_seconds > 0:
            age = time.time() - row["updated_at"]
            if age > max_age_seconds:
                logger.info("FMP cache stale for %s/%s (age=%.0fs, max=%.0fs)",
                            ticker, data_type, age, max_age_seconds)
                return None
        try:
            return json.loads(row["data_json"])
        except (json.JSONDecodeError, TypeError):
            return None

    def _set(self, ticker: str, data_type: str, data: list[dict]) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO fmp_fundamentals (ticker, data_type, data_json, updated_at) VALUES (?, ?, ?, ?)",
            (ticker.upper(), data_type, json.dumps(data), time.time()),
        )
        conn.commit()
        conn.close()

    # ── Public getters ───────────────────────────────────────────────

    def get_income_quarterly(self, ticker: str) -> Optional[list[dict]]:
        return self._get(ticker, "income_q")

    def get_balance_quarterly(self, ticker: str) -> Optional[list[dict]]:
        return self._get(ticker, "balance_q")

    def get_analyst_estimates(self, ticker: str) -> Optional[list[dict]]:
        return self._get(ticker, "estimates")

    def get_key_metrics(self, ticker: str) -> Optional[dict]:
        data = self._get(ticker, "key_metrics")
        if data and len(data) > 0:
            return data[0] if isinstance(data, list) else data
        return None

    def get_institutional_quarterly(self, ticker: str, max_age_seconds: float = -1) -> Optional[list[dict]]:
        """Get cached institutional ownership data."""
        return self._get(ticker, "institutional_q", max_age_seconds)

    def set_institutional_quarterly(self, ticker: str, data: list[dict]) -> None:
        """Cache institutional ownership data."""
        self._set(ticker, "institutional_q", data)

    # ── Prefetch ─────────────────────────────────────────────────────

    def prefetch(
        self,
        tickers: list[str],
        fmp_client,
        rate_limit_sleep: float = 0.5,
        force: bool = False,
    ) -> dict[str, int]:
        """
        Prefetch fundamental data for a list of tickers from FMP.

        Args:
            tickers: List of ticker symbols
            fmp_client: FMPClient instance
            rate_limit_sleep: Seconds between API calls (FMP is 250/day)
            force: Re-fetch even if cached

        Returns:
            {"api_calls": N, "cached": M, "errors": E}
        """
        stats = {"api_calls": 0, "cached": 0, "errors": 0}

        for i, ticker in enumerate(tickers):
            sym = ticker.upper()
            if (i + 1) % 10 == 0:
                logger.info("FMP prefetch: %d/%d tickers, %d API calls",
                            i + 1, len(tickers), stats["api_calls"])

            for data_type, fetch_fn, limit in [
                ("income_q", fmp_client.get_income_statement_quarterly, 8),
                ("balance_q", fmp_client.get_balance_sheet_quarterly, 4),
                ("estimates", fmp_client.get_analyst_estimates, 4),
            ]:
                # Check cache first
                if not force and self._get(sym, data_type) is not None:
                    stats["cached"] += 1
                    continue

                try:
                    data = fetch_fn(sym, limit=limit)
                    if data:
                        self._set(sym, data_type, data)
                    else:
                        self._set(sym, data_type, [])  # Cache empty too
                    stats["api_calls"] += 1
                    time.sleep(rate_limit_sleep)
                except Exception as exc:
                    logger.debug("FMP prefetch %s/%s failed: %s", sym, data_type, exc)
                    stats["errors"] += 1

        logger.info("FMP prefetch complete: %d API calls, %d cached, %d errors",
                     stats["api_calls"], stats["cached"], stats["errors"])
        return stats

    def prefetch_from_tiingo(
        self,
        tickers: list[str],
        tiingo_client,
        rate_limit_sleep: float = 0.3,
        force: bool = False,
    ) -> dict[str, int]:
        """
        Populate FMP cache from Tiingo fundamentals API.

        Converts Tiingo statement format to FMP-compatible dicts so the
        backtest engine can use the same cache regardless of source.
        """
        from fmp_client import (
            _REQUIRED_INCOME_FIELDS, _REQUIRED_BALANCE_FIELDS, _validate_fmp_record,
        )
        stats = {"api_calls": 0, "cached": 0, "errors": 0}

        for i, ticker in enumerate(tickers):
            sym = ticker.upper()
            if (i + 1) % 10 == 0:
                logger.info("Tiingo prefetch: %d/%d tickers", i + 1, len(tickers))

            # Skip if already cached (unless force)
            if not force and self._get(sym, "balance_q") is not None:
                existing = self._get(sym, "balance_q")
                if existing and len(existing) > 0:
                    stats["cached"] += 1
                    continue

            try:
                raw = tiingo_client.get_fundamentals_statements(sym, start_date="2024-01-01")
                if not raw:
                    stats["errors"] += 1
                    continue
                stats["api_calls"] += 1

                income_records = []
                balance_records = []

                for quarter in raw:
                    date = quarter.get("date", "")[:10]
                    sd = quarter.get("statementData", {})

                    # Convert income statement
                    inc = {item["dataCode"]: item["value"] for item in sd.get("incomeStatement", [])}
                    overview = {item["dataCode"]: item["value"] for item in sd.get("overview", [])}
                    income_records.append({
                        "date": date,
                        "symbol": sym,
                        "netIncome": inc.get("consolidatedIncome") or inc.get("netInc", 0),
                        "revenue": inc.get("revenue", 0),
                        "grossProfit": inc.get("grossProfit", 0),
                        "ebitda": inc.get("ebitda", 0),
                        "eps": inc.get("eps", 0),
                        "epsDil": inc.get("epsDil", 0),
                    })

                    # Convert balance sheet
                    bs = {item["dataCode"]: item["value"] for item in sd.get("balanceSheet", [])}
                    balance_records.append({
                        "date": date,
                        "symbol": sym,
                        "totalAssets": bs.get("totalAssets", 0),
                        "totalCurrentAssets": bs.get("assetsCurrent", 0),
                        "totalCurrentLiabilities": (bs.get("debtCurrent", 0) or 0) + (bs.get("payables", 0) or 0) + (bs.get("acctPay", 0) or 0),
                        "totalStockholdersEquity": bs.get("equity", 0),
                        "totalDebt": (bs.get("debtCurrent", 0) or 0) + (bs.get("debtNonCurrent", 0) or 0),
                        "cashAndCashEquivalents": bs.get("cashAndEq", 0),
                        "retainedEarnings": bs.get("retainedEarnings", 0),
                        "totalLiabilities": bs.get("totalLiabilities", 0),
                    })

                # Validate translated records before caching
                for rec in income_records:
                    _validate_fmp_record(rec, _REQUIRED_INCOME_FIELDS, "tiingo_translated_income", sym)
                for rec in balance_records:
                    _validate_fmp_record(rec, _REQUIRED_BALANCE_FIELDS, "tiingo_translated_balance", sym)

                self._set(sym, "income_q", income_records)
                self._set(sym, "balance_q", balance_records)

                # Build pseudo-estimates from EPS trend
                if len(income_records) >= 2:
                    estimates = []
                    for rec in income_records[:4]:
                        estimates.append({
                            "symbol": sym,
                            "date": rec["date"],
                            "epsAvg": rec.get("epsDil") or rec.get("eps", 0),
                            "revenueAvg": rec.get("revenue", 0),
                        })
                    self._set(sym, "estimates", estimates)

                import time as _time
                _time.sleep(rate_limit_sleep)

            except Exception as exc:
                logger.debug("Tiingo prefetch %s failed: %s", sym, exc)
                stats["errors"] += 1

        logger.info("Tiingo prefetch complete: %d API calls, %d cached, %d errors",
                     stats["api_calls"], stats["cached"], stats["errors"])
        return stats

    def ticker_count(self) -> int:
        conn = self._conn()
        count = conn.execute(
            "SELECT COUNT(DISTINCT ticker) FROM fmp_fundamentals"
        ).fetchone()[0]
        conn.close()
        return count

    def summary(self) -> dict:
        conn = self._conn()
        rows = conn.execute(
            "SELECT data_type, COUNT(*) as cnt FROM fmp_fundamentals GROUP BY data_type"
        ).fetchall()
        conn.close()
        return {row["data_type"]: row["cnt"] for row in rows}
