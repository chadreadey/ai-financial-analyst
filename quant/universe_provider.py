"""
Dynamic stock universe provider backed by FMP and SQLite cache.

Pulls S&P 500 constituents with GICS sector classification from FMP,
caches to a local SQLite database, and serves filtered universes
(top N by market cap, sector-balanced, etc.) to the backtest engine.

Fallback: Wikipedia S&P 500 table (free, no API key required).

Usage:
    from quant.universe_provider import UniverseProvider

    provider = UniverseProvider()  # reads FMP_API_KEY from env
    top50 = provider.get_top_n(50)  # [{ticker, name, sector, sub_sector, weight}, ...]
    sector = provider.get_sector("AAPL")  # "Technology"
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", ".universe_cache.db")
_CACHE_TTL_HOURS = 24  # refresh constituents daily


@dataclass
class Constituent:
    ticker: str
    name: str
    sector: str
    sub_sector: str
    market_cap: float = 0.0
    weight: float = 0.0  # SPY weight if available
    date_first_added: str = ""


class UniverseProvider:
    """
    Dynamic universe provider with SQLite caching.

    Data flow:
    1. Check SQLite cache (< 24h old?)
    2. If stale → try FMP sp500_constituent endpoint
    3. If FMP fails → fallback to Wikipedia scrape
    4. Cache result to SQLite
    5. Serve filtered universes from cache
    """

    FMP_BASE = "https://financialmodelingprep.com"

    def __init__(self, fmp_api_key: str = "", db_path: str = "") -> None:
        self._api_key = fmp_api_key or os.getenv("FMP_API_KEY", "").strip()
        self._db_path = db_path or _DB_PATH
        self._ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sp500_constituents (
                ticker      TEXT PRIMARY KEY,
                name        TEXT NOT NULL DEFAULT '',
                sector      TEXT NOT NULL DEFAULT '',
                sub_sector  TEXT NOT NULL DEFAULT '',
                market_cap  REAL DEFAULT 0,
                weight      REAL DEFAULT 0,
                date_first_added TEXT DEFAULT '',
                updated_at  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sp500_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_constituents_sector
                ON sp500_constituents(sector);
            CREATE INDEX IF NOT EXISTS idx_constituents_mcap
                ON sp500_constituents(market_cap DESC);
        """)
        conn.commit()
        conn.close()

    # ── Cache freshness ──────────────────────────────────────────────

    def _cache_age_hours(self) -> float:
        conn = self._conn()
        row = conn.execute("SELECT value FROM sp500_meta WHERE key = 'last_refresh'").fetchone()
        conn.close()
        if row is None:
            return float("inf")
        try:
            last = float(row["value"])
            return (time.time() - last) / 3600
        except (ValueError, TypeError):
            return float("inf")

    def _set_refreshed(self) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO sp500_meta (key, value) VALUES ('last_refresh', ?)",
            (str(time.time()),),
        )
        conn.commit()
        conn.close()

    # ── FMP data fetch ───────────────────────────────────────────────

    def _fetch_fmp_constituents(self) -> list[dict]:
        """Fetch S&P 500 constituents from FMP. Returns raw dicts."""
        if not self._api_key:
            logger.info("No FMP_API_KEY — skipping FMP fetch")
            return []
        try:
            resp = requests.get(
                f"{self.FMP_BASE}/api/v3/sp500_constituent",
                params={"apikey": self._api_key},
                timeout=(5, 15),
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and len(data) > 100:
                logger.info("FMP returned %d S&P 500 constituents", len(data))
                return data
            logger.warning(
                "FMP sp500_constituent returned unexpected data: %d items",
                len(data) if isinstance(data, list) else 0,
            )
            return []
        except Exception as exc:
            logger.warning("FMP sp500_constituent failed: %s", exc)
            return []

    def _fetch_fmp_etf_holdings(self) -> dict[str, float]:
        """Fetch SPY holdings with weights from FMP. Returns {ticker: weight_pct}."""
        if not self._api_key:
            return {}
        try:
            resp = requests.get(
                f"{self.FMP_BASE}/stable/etf/holdings",
                params={"symbol": "SPY", "apikey": self._api_key},
                timeout=(5, 15),
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return {
                    row.get("asset", ""): float(row.get("weightPercentage", 0) or 0)
                    for row in data
                    if row.get("asset")
                }
            return {}
        except Exception as exc:
            logger.debug("FMP ETF holdings failed (may require paid tier): %s", exc)
            return {}

    # ── Wikipedia fallback ───────────────────────────────────────────

    def _fetch_wikipedia(self) -> list[dict]:
        """Scrape S&P 500 list from Wikipedia. No API key needed."""
        try:
            import pandas as pd
            import io

            # Wikipedia blocks default urllib User-Agent; use requests instead
            resp = requests.get(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                headers={"User-Agent": "AIFinancialAnalyst/1.0 (research)"},
                timeout=15,
            )
            resp.raise_for_status()
            tables = pd.read_html(io.StringIO(resp.text), attrs={"id": "constituents"})
            if not tables:
                return []
            df = tables[0]
            results = []
            for _, row in df.iterrows():
                results.append(
                    {
                        "symbol": str(row.get("Symbol", "")).replace(".", "-"),  # BRK.B → BRK-B
                        "name": str(row.get("Security", "")),
                        "sector": str(row.get("GICS Sector", "")),
                        "subSector": str(row.get("GICS Sub-Industry", "")),
                        "dateFirstAdded": str(row.get("Date added", "")),
                    }
                )
            logger.info("Wikipedia returned %d S&P 500 constituents", len(results))
            return results
        except Exception as exc:
            logger.warning("Wikipedia S&P 500 scrape failed: %s", exc)
            return []

    # ── Refresh logic ────────────────────────────────────────────────

    def refresh(self, force: bool = False) -> int:
        """
        Refresh the constituents cache if stale (> 24h) or forced.
        Returns number of constituents stored.
        """
        if not force and self._cache_age_hours() < _CACHE_TTL_HOURS:
            conn = self._conn()
            count = conn.execute("SELECT COUNT(*) FROM sp500_constituents").fetchone()[0]
            conn.close()
            if count > 400:
                logger.debug(
                    "Universe cache fresh (%d constituents, %.1fh old)",
                    count,
                    self._cache_age_hours(),
                )
                return count

        # Try FMP first, fallback to Wikipedia
        raw = self._fetch_fmp_constituents()
        source = "fmp"
        if not raw:
            raw = self._fetch_wikipedia()
            source = "wikipedia"
        if not raw:
            logger.error("Failed to fetch S&P 500 constituents from any source")
            return 0

        # Optionally enrich with SPY weights (FMP paid tier)
        weights = {}
        if source == "fmp":
            weights = self._fetch_fmp_etf_holdings()

        # Upsert to SQLite
        now = time.time()
        conn = self._conn()
        for item in raw:
            ticker = item.get("symbol", "").strip().upper()
            if not ticker or len(ticker) > 10:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO sp500_constituents
                    (ticker, name, sector, sub_sector, market_cap, weight, date_first_added, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    ticker,
                    item.get("name", item.get("Security", "")),
                    item.get("sector", item.get("GICS Sector", "")),
                    item.get("subSector", item.get("GICS Sub-Industry", "")),
                    float(item.get("marketCap", 0) or 0),
                    weights.get(ticker, 0.0),
                    item.get("dateFirstAdded", item.get("Date added", "")),
                    now,
                ),
            )
        conn.commit()

        count = conn.execute("SELECT COUNT(*) FROM sp500_constituents").fetchone()[0]
        conn.close()
        self._set_refreshed()
        logger.info("Universe cache refreshed from %s: %d constituents", source, count)
        return count

    # ── Query methods ────────────────────────────────────────────────

    def get_all(self) -> list[Constituent]:
        """Return all S&P 500 constituents."""
        self.refresh()
        conn = self._conn()
        rows = conn.execute("SELECT * FROM sp500_constituents ORDER BY market_cap DESC").fetchall()
        conn.close()
        return [self._row_to_constituent(r) for r in rows]

    def get_top_n(self, n: int = 50) -> list[Constituent]:
        """
        Return top N constituents by SPY weight (if available) or market cap.
        Ensures the result is automatically refreshed from FMP/Wikipedia.
        """
        self.refresh()
        conn = self._conn()
        # Prefer weight (from ETF holdings), fall back to market_cap
        rows = conn.execute(
            """
            SELECT * FROM sp500_constituents
            ORDER BY
                CASE WHEN weight > 0 THEN weight ELSE 0 END DESC,
                market_cap DESC
            LIMIT ?
        """,
            (n,),
        ).fetchall()
        conn.close()
        return [self._row_to_constituent(r) for r in rows]

    def get_top_n_tickers(self, n: int = 50) -> list[str]:
        """Convenience: return just ticker symbols for top N."""
        return [c.ticker for c in self.get_top_n(n)]

    def get_sector(self, ticker: str) -> str:
        """Return GICS sector for a ticker, or 'Unknown'."""
        self.refresh()
        conn = self._conn()
        row = conn.execute(
            "SELECT sector FROM sp500_constituents WHERE ticker = ?",
            (ticker.upper(),),
        ).fetchone()
        conn.close()
        return row["sector"] if row else "Unknown"

    def get_sectors_bulk(self, tickers: list[str]) -> dict[str, str]:
        """Return {ticker: sector} for a list of tickers."""
        self.refresh()
        conn = self._conn()
        placeholders = ",".join("?" * len(tickers))
        rows = conn.execute(
            f"SELECT ticker, sector FROM sp500_constituents WHERE ticker IN ({placeholders})",
            [t.upper() for t in tickers],
        ).fetchall()
        conn.close()
        result = {row["ticker"]: row["sector"] for row in rows}
        # Fill in Unknown for any missing
        for t in tickers:
            if t.upper() not in result:
                result[t.upper()] = "Unknown"
        return result

    def get_by_sector(self, sector: str, limit: int = 20) -> list[Constituent]:
        """Return constituents in a specific sector, ordered by market cap."""
        self.refresh()
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM sp500_constituents WHERE sector = ? ORDER BY market_cap DESC LIMIT ?",
            (sector, limit),
        ).fetchall()
        conn.close()
        return [self._row_to_constituent(r) for r in rows]

    def get_sector_counts(self) -> dict[str, int]:
        """Return {sector: count} for all sectors in the universe."""
        self.refresh()
        conn = self._conn()
        rows = conn.execute(
            "SELECT sector, COUNT(*) as cnt FROM sp500_constituents GROUP BY sector ORDER BY cnt DESC"
        ).fetchall()
        conn.close()
        return {row["sector"]: row["cnt"] for row in rows}

    @staticmethod
    def _row_to_constituent(row: sqlite3.Row) -> Constituent:
        return Constituent(
            ticker=row["ticker"],
            name=row["name"],
            sector=row["sector"],
            sub_sector=row["sub_sector"],
            market_cap=row["market_cap"],
            weight=row["weight"],
            date_first_added=row["date_first_added"],
        )


# ── Module-level convenience ─────────────────────────────────────────

_provider: Optional[UniverseProvider] = None


def get_universe_provider() -> UniverseProvider:
    """Get or create the singleton UniverseProvider."""
    global _provider
    if _provider is None:
        _provider = UniverseProvider()
    return _provider
