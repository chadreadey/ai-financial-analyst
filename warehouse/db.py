"""
Persistent filing warehouse — SQLite (local dev) or PostgreSQL (production).

Backend is selected at init time from the environment:
    DATABASE_URL set   → psycopg2 / PostgreSQL (Supabase)
    DATABASE_URL unset → sqlite3  (.warehouse.db)

All public methods open their own connection and close before returning.
Timestamp values are always returned as unix floats regardless of backend,
so all callers (change_detector, reader, etc.) need no changes.
"""

import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional


def _default_db_path() -> str:
    return os.environ.get("WAREHOUSE_DB_PATH", ".warehouse.db")


class WarehouseDB:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = _default_db_path()
        self._dsn = os.environ.get("DATABASE_URL", "").strip()
        self._pg = bool(self._dsn)
        if self._pg:
            self._db_path = None
        else:
            self._db_path = db_path
            self._init_schema()

    # ── backend helpers ───────────────────────────────────────────────────────

    def _connect(self):
        if self._pg:
            import psycopg2
            return psycopg2.connect(self._dsn)
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _cursor(self, conn):
        if self._pg:
            from psycopg2.extras import RealDictCursor
            return conn.cursor(cursor_factory=RealDictCursor)
        return conn.cursor()

    @property
    def _ph(self) -> str:
        """Positional placeholder: %s for PostgreSQL, ? for SQLite."""
        return "%s" if self._pg else "?"

    def _now(self):
        """Current timestamp in the type expected by the active backend."""
        return datetime.now(timezone.utc) if self._pg else time.time()

    def _to_float(self, val) -> Optional[float]:
        """Normalize a timestamp to a unix float (datetime or float or None)."""
        if val is None:
            return None
        if isinstance(val, datetime):
            return val.timestamp()
        return float(val)

    def _row_to_dict(self, row) -> Optional[dict]:
        """Convert a DB row to a plain dict with all timestamps as unix floats."""
        if row is None:
            return None
        d = dict(row)
        for key in ("bootstrapped_at", "last_checked_at", "ingested_at"):
            if key in d:
                d[key] = self._to_float(d[key])
        return d

    def _execute(self, conn, sql: str, params=()):
        """
        Execute SQL against the active connection.

        Translates %s → ? for SQLite so all SQL can be written in
        PostgreSQL placeholder style.
        """
        if not self._pg:
            sql = sql.replace("%s", "?")
        cur = self._cursor(conn)
        cur.execute(sql, params)
        return cur

    def _executemany(self, conn, sql: str, params_seq):
        """
        Execute SQL for multiple rows efficiently.

        For PostgreSQL uses psycopg2.extras.execute_batch which sends rows
        in batches of page_size — far fewer network round-trips than
        individual execute() calls, and compatible with standard %s placeholders.
        For SQLite uses cursor.executemany.
        """
        if self._pg:
            from psycopg2.extras import execute_batch
            cur = conn.cursor()
            execute_batch(cur, sql, params_seq, page_size=500)
        else:
            sql = sql.replace("%s", "?")
            cur = conn.cursor()
            cur.executemany(sql, params_seq)
        return cur

    # ── schema init (SQLite only — PostgreSQL schema managed by migration) ────

    def _init_schema(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
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

    # ── writes ────────────────────────────────────────────────────────────────

    def upsert_company(
        self,
        ticker: str,
        cik: str,
        name: str,
        last_accession: Optional[str] = None,
    ) -> None:
        conn = self._connect()
        try:
            self._execute(
                conn,
                """
                INSERT INTO companies (ticker, cik, name, last_accession, bootstrapped_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE SET
                    cik            = EXCLUDED.cik,
                    name           = EXCLUDED.name,
                    last_accession = COALESCE(EXCLUDED.last_accession, companies.last_accession),
                    bootstrapped_at = COALESCE(companies.bootstrapped_at, EXCLUDED.bootstrapped_at)
                """,
                (ticker.upper(), cik, name, last_accession, self._now()),
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
            self._execute(
                conn,
                """
                INSERT INTO filings (ticker, accession, form, filing_date, primary_doc, ingested_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, accession) DO UPDATE SET
                    form        = EXCLUDED.form,
                    filing_date = EXCLUDED.filing_date,
                    primary_doc = EXCLUDED.primary_doc,
                    ingested_at = EXCLUDED.ingested_at
                """,
                (ticker.upper(), accession, form, filing_date, primary_doc, self._now()),
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
            self._execute(
                conn,
                """
                INSERT INTO xbrl_facts
                    (ticker, concept, unit, period_end, value, form,
                     fiscal_year, fiscal_period, ingested_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, concept, unit, period_end, form) DO UPDATE SET
                    value         = EXCLUDED.value,
                    fiscal_year   = EXCLUDED.fiscal_year,
                    fiscal_period = EXCLUDED.fiscal_period,
                    ingested_at   = EXCLUDED.ingested_at
                """,
                (
                    ticker.upper(), concept, unit, period_end, value,
                    form, fiscal_year, fiscal_period, self._now(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_filings_bulk(self, rows: list[dict]) -> None:
        """
        Insert/update multiple filings in a single round-trip.

        Each dict must have keys: ticker, accession, form, filing_date,
        primary_doc (optional).
        """
        if not rows:
            return
        now = self._now()
        params = [
            (
                r["ticker"].upper(),
                r["accession"],
                r["form"],
                r["filing_date"],
                r.get("primary_doc", ""),
                now,
            )
            for r in rows
        ]
        sql = """
            INSERT INTO filings (ticker, accession, form, filing_date, primary_doc, ingested_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker, accession) DO UPDATE SET
                form        = EXCLUDED.form,
                filing_date = EXCLUDED.filing_date,
                primary_doc = EXCLUDED.primary_doc,
                ingested_at = EXCLUDED.ingested_at
        """
        conn = self._connect()
        try:
            self._executemany(conn, sql, params)
            conn.commit()
        finally:
            conn.close()

    def upsert_xbrl_facts_bulk(self, rows: list[dict]) -> None:
        """
        Insert/update multiple XBRL facts in a single round-trip.

        Each dict must have keys: ticker, concept, unit, period_end, value
        and optionally: form, fiscal_year, fiscal_period.
        """
        if not rows:
            return
        now = self._now()
        params = [
            (
                r["ticker"].upper(),
                r["concept"],
                r["unit"],
                r["period_end"],
                r["value"],
                r.get("form"),
                r.get("fiscal_year"),
                r.get("fiscal_period"),
                now,
            )
            for r in rows
        ]
        sql = """
            INSERT INTO xbrl_facts
                (ticker, concept, unit, period_end, value, form,
                 fiscal_year, fiscal_period, ingested_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker, concept, unit, period_end, form) DO UPDATE SET
                value         = EXCLUDED.value,
                fiscal_year   = EXCLUDED.fiscal_year,
                fiscal_period = EXCLUDED.fiscal_period,
                ingested_at   = EXCLUDED.ingested_at
        """
        conn = self._connect()
        try:
            self._executemany(conn, sql, params)
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
            self._execute(
                conn,
                """
                INSERT INTO market_snapshots
                    (ticker, as_of_date, price, market_cap, pe_ttm, forward_pe,
                     ps_ttm, ev_ebitda, beta, week52_high, week52_low,
                     target_mean, recommendation, ingested_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, as_of_date) DO UPDATE SET
                    price          = EXCLUDED.price,
                    market_cap     = EXCLUDED.market_cap,
                    pe_ttm         = EXCLUDED.pe_ttm,
                    forward_pe     = EXCLUDED.forward_pe,
                    ps_ttm         = EXCLUDED.ps_ttm,
                    ev_ebitda      = EXCLUDED.ev_ebitda,
                    beta           = EXCLUDED.beta,
                    week52_high    = EXCLUDED.week52_high,
                    week52_low     = EXCLUDED.week52_low,
                    target_mean    = EXCLUDED.target_mean,
                    recommendation = EXCLUDED.recommendation,
                    ingested_at    = EXCLUDED.ingested_at
                """,
                (
                    ticker.upper(), as_of_date, price, market_cap, pe_ttm,
                    forward_pe, ps_ttm, ev_ebitda, beta, week52_high,
                    week52_low, target_mean, recommendation, self._now(),
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
            self._execute(
                conn,
                """
                INSERT INTO macro_series (series_id, label, as_of_date, value, ingested_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (series_id, as_of_date) DO UPDATE SET
                    label       = EXCLUDED.label,
                    value       = EXCLUDED.value,
                    ingested_at = EXCLUDED.ingested_at
                """,
                (series_id, label, as_of_date, value, self._now()),
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
            self._execute(
                conn,
                """
                INSERT INTO filing_sections (ticker, accession, section_key, text, ingested_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ticker, accession, section_key) DO UPDATE SET
                    text        = EXCLUDED.text,
                    ingested_at = EXCLUDED.ingested_at
                """,
                (ticker.upper(), accession, section_key, text, self._now()),
            )
            conn.commit()
        finally:
            conn.close()

    def update_last_checked(self, ticker: str, accession: str) -> None:
        now = self._now()
        conn = self._connect()
        try:
            self._execute(
                conn,
                "UPDATE companies SET last_checked_at = %s WHERE ticker = %s",
                (now, ticker.upper()),
            )
            self._execute(
                conn,
                """
                UPDATE companies SET last_accession = %s
                WHERE ticker = %s
                  AND (last_accession IS NULL OR last_accession < %s)
                """,
                (accession, ticker.upper(), accession),
            )
            conn.commit()
        finally:
            conn.close()

    # ── reads ─────────────────────────────────────────────────────────────────

    def get_company(self, ticker: str) -> Optional[dict]:
        conn = self._connect()
        try:
            cur = self._execute(
                conn,
                "SELECT * FROM companies WHERE ticker = %s",
                (ticker.upper(),),
            )
            return self._row_to_dict(cur.fetchone())
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
                placeholders = ", ".join(["%s"] * len(form_types))
                cur = self._execute(
                    conn,
                    f"SELECT * FROM filings WHERE ticker = %s AND form IN ({placeholders}) "
                    f"ORDER BY filing_date DESC LIMIT %s",
                    [ticker.upper(), *form_types, limit],
                )
            else:
                cur = self._execute(
                    conn,
                    "SELECT * FROM filings WHERE ticker = %s ORDER BY filing_date DESC LIMIT %s",
                    (ticker.upper(), limit),
                )
            return [self._row_to_dict(r) for r in cur.fetchall()]
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
                placeholders = ", ".join(["%s"] * len(concepts))
                cur = self._execute(
                    conn,
                    f"SELECT * FROM xbrl_facts WHERE ticker = %s AND concept IN ({placeholders}) "
                    f"ORDER BY period_end DESC",
                    [ticker.upper(), *concepts],
                )
            else:
                cur = self._execute(
                    conn,
                    "SELECT * FROM xbrl_facts WHERE ticker = %s ORDER BY period_end DESC",
                    (ticker.upper(),),
                )
            return [self._row_to_dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def get_market_snapshot(self, ticker: str) -> Optional[dict]:
        conn = self._connect()
        try:
            cur = self._execute(
                conn,
                "SELECT * FROM market_snapshots WHERE ticker = %s ORDER BY as_of_date DESC LIMIT 1",
                (ticker.upper(),),
            )
            return self._row_to_dict(cur.fetchone())
        finally:
            conn.close()

    def get_macro_series(
        self,
        series_ids: Optional[list[str]] = None,
    ) -> list[dict]:
        conn = self._connect()
        try:
            if series_ids:
                placeholders = ", ".join(["%s"] * len(series_ids))
                cur = self._execute(
                    conn,
                    f"SELECT * FROM macro_series WHERE series_id IN ({placeholders}) "
                    f"ORDER BY as_of_date DESC",
                    series_ids,
                )
            else:
                cur = self._execute(
                    conn,
                    "SELECT * FROM macro_series ORDER BY as_of_date DESC",
                )
            return [self._row_to_dict(r) for r in cur.fetchall()]
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
            cur = self._execute(
                conn,
                "SELECT text FROM filing_sections WHERE ticker = %s AND accession = %s AND section_key = %s",
                (ticker.upper(), accession, section_key),
            )
            row = cur.fetchone()
            return row["text"] if row else None
        finally:
            conn.close()

    def get_latest_accession(self, ticker: str) -> Optional[str]:
        conn = self._connect()
        try:
            cur = self._execute(
                conn,
                "SELECT accession FROM filings WHERE ticker = %s ORDER BY filing_date DESC LIMIT 1",
                (ticker.upper(),),
            )
            row = cur.fetchone()
            return row["accession"] if row else None
        finally:
            conn.close()

    def list_tracked_tickers(self) -> list[str]:
        conn = self._connect()
        try:
            cur = self._execute(conn, "SELECT ticker FROM companies ORDER BY ticker")
            return [row["ticker"] for row in cur.fetchall()]
        finally:
            conn.close()

    def count_filing_sections(self, ticker: str) -> int:
        """Return the number of filing_sections rows for a ticker."""
        conn = self._connect()
        try:
            cur = self._execute(
                conn,
                "SELECT COUNT(*) AS n FROM filing_sections WHERE ticker = %s",
                (ticker.upper(),),
            )
            row = cur.fetchone()
            return int(row["n"]) if row else 0
        finally:
            conn.close()

    def list_filing_sections(
        self,
        tickers: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Return all filing_sections rows, optionally filtered to a list of tickers.

        Used by the embedder to fetch text for Pinecone upsert — replaces the
        raw sqlite3 query in embedder._fetch_sections().
        """
        conn = self._connect()
        try:
            if tickers:
                upper = [t.upper() for t in tickers]
                placeholders = ", ".join(["%s"] * len(upper))
                cur = self._execute(
                    conn,
                    f"""
                    SELECT
                        fs.ticker,
                        fs.accession,
                        fs.section_key,
                        fs.text,
                        COALESCE(f.form, '10-K')   AS form_type,
                        COALESCE(CAST(f.filing_date AS TEXT), '') AS filing_date
                    FROM filing_sections fs
                    LEFT JOIN filings f
                      ON fs.ticker = f.ticker AND fs.accession = f.accession
                    WHERE fs.ticker IN ({placeholders})
                    ORDER BY fs.ticker, fs.accession, fs.section_key
                    """,
                    upper,
                )
            else:
                cur = self._execute(
                    conn,
                    """
                    SELECT
                        fs.ticker,
                        fs.accession,
                        fs.section_key,
                        fs.text,
                        COALESCE(f.form, '10-K')   AS form_type,
                        COALESCE(CAST(f.filing_date AS TEXT), '') AS filing_date
                    FROM filing_sections fs
                    LEFT JOIN filings f
                      ON fs.ticker = f.ticker AND fs.accession = f.accession
                    ORDER BY fs.ticker, fs.accession, fs.section_key
                    """,
                )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
