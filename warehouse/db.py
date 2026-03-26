"""
Persistent filing warehouse backed by SQLite.

Every public method opens its own connection and closes it before returning.
No connection is ever stored as an instance attribute.
"""

import sqlite3
import time
from typing import Optional


class WarehouseDB:
    def __init__(self, db_path: str = ".warehouse.db"):
        self._db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS companies (
                    ticker          TEXT PRIMARY KEY,
                    cik             TEXT NOT NULL,
                    name            TEXT NOT NULL,
                    last_accession  TEXT,
                    bootstrapped_at REAL,
                    last_checked_at REAL
                );

                CREATE TABLE IF NOT EXISTS filings (
                    ticker          TEXT NOT NULL,
                    accession       TEXT NOT NULL,
                    form            TEXT NOT NULL,
                    filing_date     TEXT NOT NULL,
                    primary_doc     TEXT NOT NULL DEFAULT '',
                    ingested_at     REAL NOT NULL,
                    PRIMARY KEY (ticker, accession)
                );

                CREATE TABLE IF NOT EXISTS xbrl_facts (
                    ticker          TEXT NOT NULL,
                    concept         TEXT NOT NULL,
                    unit            TEXT NOT NULL,
                    period_end      TEXT NOT NULL,
                    value           REAL NOT NULL,
                    form            TEXT,
                    fiscal_year     INTEGER,
                    fiscal_period   TEXT,
                    filed_date      TEXT,
                    ingested_at     REAL NOT NULL,
                    PRIMARY KEY (ticker, concept, unit, period_end, form)
                );

                CREATE TABLE IF NOT EXISTS market_snapshots (
                    ticker          TEXT NOT NULL,
                    as_of_date      TEXT NOT NULL,
                    price           REAL,
                    market_cap      REAL,
                    pe_ttm          REAL,
                    forward_pe      REAL,
                    ps_ttm          REAL,
                    ev_ebitda       REAL,
                    beta            REAL,
                    week52_high     REAL,
                    week52_low      REAL,
                    target_mean     REAL,
                    recommendation  TEXT,
                    ingested_at     REAL NOT NULL,
                    PRIMARY KEY (ticker, as_of_date)
                );

                CREATE TABLE IF NOT EXISTS macro_series (
                    series_id       TEXT NOT NULL,
                    label           TEXT NOT NULL,
                    as_of_date      TEXT NOT NULL,
                    value           REAL NOT NULL,
                    ingested_at     REAL NOT NULL,
                    PRIMARY KEY (series_id, as_of_date)
                );

                CREATE TABLE IF NOT EXISTS filing_sections (
                    ticker          TEXT NOT NULL,
                    accession       TEXT NOT NULL,
                    section_key     TEXT NOT NULL,
                    text            TEXT NOT NULL,
                    ingested_at     REAL NOT NULL,
                    PRIMARY KEY (ticker, accession, section_key)
                );
                """
            )
        finally:
            conn.close()

    # ── writes ───────────────────────────────────────────────────────

    def upsert_company(
        self,
        ticker: str,
        cik: str,
        name: str,
        last_accession: Optional[str] = None,
    ) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO companies (ticker, cik, name, last_accession, bootstrapped_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    cik            = excluded.cik,
                    name           = excluded.name,
                    last_accession = COALESCE(excluded.last_accession, companies.last_accession),
                    bootstrapped_at = COALESCE(companies.bootstrapped_at, excluded.bootstrapped_at)
                """,
                (ticker.upper(), cik, name, last_accession, time.time()),
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_filing(
        self,
        ticker: str,
        accession: str,
        form: str,
        filing_date: str,
        primary_doc: str = "",
    ) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO filings (ticker, accession, form, filing_date, primary_doc, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, accession) DO UPDATE SET
                    form        = excluded.form,
                    filing_date = excluded.filing_date,
                    primary_doc = excluded.primary_doc,
                    ingested_at = excluded.ingested_at
                """,
                (ticker.upper(), accession, form, filing_date, primary_doc, time.time()),
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_xbrl_fact(
        self,
        ticker: str,
        concept: str,
        unit: str,
        period_end: str,
        value: float,
        form: Optional[str] = None,
        fiscal_year: Optional[int] = None,
        fiscal_period: Optional[str] = None,
    ) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO xbrl_facts
                    (ticker, concept, unit, period_end, value, form,
                     fiscal_year, fiscal_period, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, concept, unit, period_end, form) DO UPDATE SET
                    value         = excluded.value,
                    fiscal_year   = excluded.fiscal_year,
                    fiscal_period = excluded.fiscal_period,
                    ingested_at   = excluded.ingested_at
                """,
                (
                    ticker.upper(), concept, unit, period_end, value,
                    form, fiscal_year, fiscal_period, time.time(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_market_snapshot(
        self,
        ticker: str,
        as_of_date: str,
        price: Optional[float] = None,
        market_cap: Optional[float] = None,
        pe_ttm: Optional[float] = None,
        forward_pe: Optional[float] = None,
        ps_ttm: Optional[float] = None,
        ev_ebitda: Optional[float] = None,
        beta: Optional[float] = None,
        week52_high: Optional[float] = None,
        week52_low: Optional[float] = None,
        target_mean: Optional[float] = None,
        recommendation: Optional[str] = None,
    ) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO market_snapshots
                    (ticker, as_of_date, price, market_cap, pe_ttm, forward_pe,
                     ps_ttm, ev_ebitda, beta, week52_high, week52_low,
                     target_mean, recommendation, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, as_of_date) DO UPDATE SET
                    price          = excluded.price,
                    market_cap     = excluded.market_cap,
                    pe_ttm         = excluded.pe_ttm,
                    forward_pe     = excluded.forward_pe,
                    ps_ttm         = excluded.ps_ttm,
                    ev_ebitda      = excluded.ev_ebitda,
                    beta           = excluded.beta,
                    week52_high    = excluded.week52_high,
                    week52_low     = excluded.week52_low,
                    target_mean    = excluded.target_mean,
                    recommendation = excluded.recommendation,
                    ingested_at    = excluded.ingested_at
                """,
                (
                    ticker.upper(), as_of_date, price, market_cap, pe_ttm,
                    forward_pe, ps_ttm, ev_ebitda, beta, week52_high,
                    week52_low, target_mean, recommendation, time.time(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_macro_series(
        self,
        series_id: str,
        label: str,
        as_of_date: str,
        value: float,
    ) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO macro_series (series_id, label, as_of_date, value, ingested_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(series_id, as_of_date) DO UPDATE SET
                    label       = excluded.label,
                    value       = excluded.value,
                    ingested_at = excluded.ingested_at
                """,
                (series_id, label, as_of_date, value, time.time()),
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_filing_section(
        self,
        ticker: str,
        accession: str,
        section_key: str,
        text: str,
    ) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO filing_sections (ticker, accession, section_key, text, ingested_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(ticker, accession, section_key) DO UPDATE SET
                    text        = excluded.text,
                    ingested_at = excluded.ingested_at
                """,
                (ticker.upper(), accession, section_key, text, time.time()),
            )
            conn.commit()
        finally:
            conn.close()

    def update_last_checked(self, ticker: str, accession: str) -> None:
        now = time.time()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE companies SET last_checked_at = ? WHERE ticker = ?",
                (now, ticker.upper()),
            )
            conn.execute(
                "UPDATE companies SET last_accession = ? WHERE ticker = ? AND (last_accession IS NULL OR last_accession < ?)",
                (accession, ticker.upper(), accession),
            )
            conn.commit()
        finally:
            conn.close()

    # ── reads ────────────────────────────────────────────────────────

    def get_company(self, ticker: str) -> Optional[dict]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM companies WHERE ticker = ?",
                (ticker.upper(),),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_filings(
        self,
        ticker: str,
        form_types: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[dict]:
        conn = self._connect()
        try:
            if form_types:
                placeholders = ",".join("?" for _ in form_types)
                rows = conn.execute(
                    f"SELECT * FROM filings WHERE ticker = ? AND form IN ({placeholders}) "
                    f"ORDER BY filing_date DESC LIMIT ?",
                    [ticker.upper(), *form_types, limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM filings WHERE ticker = ? ORDER BY filing_date DESC LIMIT ?",
                    (ticker.upper(), limit),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_xbrl_facts(
        self,
        ticker: str,
        concepts: Optional[list[str]] = None,
    ) -> list[dict]:
        conn = self._connect()
        try:
            if concepts:
                placeholders = ",".join("?" for _ in concepts)
                rows = conn.execute(
                    f"SELECT * FROM xbrl_facts WHERE ticker = ? AND concept IN ({placeholders}) "
                    f"ORDER BY period_end DESC",
                    [ticker.upper(), *concepts],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM xbrl_facts WHERE ticker = ? ORDER BY period_end DESC",
                    (ticker.upper(),),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_market_snapshot(self, ticker: str) -> Optional[dict]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM market_snapshots WHERE ticker = ? ORDER BY as_of_date DESC LIMIT 1",
                (ticker.upper(),),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_macro_series(
        self,
        series_ids: Optional[list[str]] = None,
    ) -> list[dict]:
        conn = self._connect()
        try:
            if series_ids:
                placeholders = ",".join("?" for _ in series_ids)
                rows = conn.execute(
                    f"SELECT * FROM macro_series WHERE series_id IN ({placeholders}) "
                    f"ORDER BY as_of_date DESC",
                    series_ids,
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM macro_series ORDER BY as_of_date DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_filing_section(
        self,
        ticker: str,
        accession: str,
        section_key: str,
    ) -> Optional[str]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT text FROM filing_sections WHERE ticker = ? AND accession = ? AND section_key = ?",
                (ticker.upper(), accession, section_key),
            ).fetchone()
            return row["text"] if row else None
        finally:
            conn.close()

    def get_latest_accession(self, ticker: str) -> Optional[str]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT accession FROM filings WHERE ticker = ? ORDER BY filing_date DESC LIMIT 1",
                (ticker.upper(),),
            ).fetchone()
            return row["accession"] if row else None
        finally:
            conn.close()

    def list_tracked_tickers(self) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT ticker FROM companies ORDER BY ticker"
            ).fetchall()
            return [row["ticker"] for row in rows]
        finally:
            conn.close()
