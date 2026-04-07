"""
WRDS Point-in-Time SQLite Store.

Stores Compustat quarterly fundamentals and IBES consensus estimates
with point-in-time discipline: queries filter on rdq (report date) and
statpers (consensus date) to return only data that was publicly available
at the requested as_of_date.

Separate from .fmp_cache.db — WRDS is bulk-loaded reference data,
FMP cache is ephemeral live data.

Academic use only — every table is tagged with its commercial replacement.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import date
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", ".wrds_pit.db")

# ── Commercial replacement tags ─────────────────────────────────────

COMMERCIAL_TAGS = {
    "compustat_quarterly": {
        "source": "wrds:comp.fundq",
        "replacement": "FMP /stable/income-statement + /stable/balance-sheet-statement (quarterly)",
        "cost": "$29/mo FMP Starter (250/day) or $79/mo FMP Pro (unlimited)",
        "pit_field": "rdq (report date of quarterly earnings — NO direct FMP equivalent)",
        "notes": "rdq is when the filing became public. FMP filingDate is close but not identical.",
    },
    "ibes_consensus": {
        "source": "wrds:ibes.statsumu_epsus",
        "replacement": "No direct retail equivalent. FMP /analyst-estimates lacks historical consensus snapshots.",
        "cost": "Estimize $299/mo (partial), Refinitiv IBES $20K+/yr (full)",
        "pit_field": "statpers (monthly consensus snapshot date)",
        "notes": "IBES is the primary reason for WRDS access. statpers enables point-in-time revision momentum.",
    },
    "ibes_actuals": {
        "source": "wrds:ibes.actu_epsus",
        "replacement": "FMP /stable/earnings-calendar or Compustat epspiq",
        "cost": "$29/mo FMP Starter",
        "pit_field": "anndats (earnings announcement date)",
    },
    "ticker_link": {
        "source": "wrds:crsp.ccmxpf_linktable + ibes.id",
        "replacement": "Manual ticker mapping + Tiingo metadata",
        "cost": "$0",
    },
}


class WRDSPointInTimeStore:
    """SQLite store with point-in-time query semantics for WRDS data."""

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
            CREATE TABLE IF NOT EXISTS compustat_quarterly (
                gvkey       TEXT NOT NULL,
                ticker      TEXT NOT NULL,
                datadate    TEXT NOT NULL,
                rdq         TEXT NOT NULL,
                fyearq      INTEGER,
                fqtr        INTEGER,
                atq         REAL,
                ceqq        REAL,
                ltq         REAL,
                dlcq        REAL,
                dlttq       REAL,
                cheq        REAL,
                actq        REAL,
                lctq        REAL,
                saleq       REAL,
                revtq       REAL,
                niq         REAL,
                ibq         REAL,
                oancfy      REAL,
                epsfxq      REAL,
                epspiq      REAL,
                capxy       REAL,
                cogsq       REAL,
                xsgaq       REAL,
                cshoq       REAL,
                rdq_inferred INTEGER DEFAULT 0,
                PRIMARY KEY (gvkey, datadate)
            );
            CREATE INDEX IF NOT EXISTS idx_compustat_pit
                ON compustat_quarterly(ticker, rdq);

            CREATE TABLE IF NOT EXISTS ibes_consensus (
                ticker      TEXT NOT NULL,
                statpers    TEXT NOT NULL,
                fpedats     TEXT NOT NULL,
                fpi         TEXT NOT NULL,
                meanest     REAL,
                medest      REAL,
                stdev       REAL,
                numest      REAL,
                numup       REAL,
                numdown     REAL,
                PRIMARY KEY (ticker, statpers, fpedats, fpi)
            );
            CREATE INDEX IF NOT EXISTS idx_ibes_pit
                ON ibes_consensus(ticker, statpers);

            CREATE TABLE IF NOT EXISTS ibes_actuals (
                ticker      TEXT NOT NULL,
                pends       TEXT NOT NULL,
                anndats     TEXT NOT NULL,
                value       REAL,
                pdicity     TEXT,
                PRIMARY KEY (ticker, pends)
            );
            CREATE INDEX IF NOT EXISTS idx_ibes_actuals_pit
                ON ibes_actuals(ticker, anndats);

            CREATE TABLE IF NOT EXISTS ticker_link (
                ticker      TEXT NOT NULL,
                gvkey       TEXT,
                permno      INTEGER,
                ibes_ticker TEXT,
                cusip8      TEXT,
                link_start  TEXT,
                link_end    TEXT,
                PRIMARY KEY (ticker, link_start)
            );

            CREATE TABLE IF NOT EXISTS commercial_tags (
                table_name  TEXT PRIMARY KEY,
                tag_json    TEXT NOT NULL,
                row_count   INTEGER DEFAULT 0,
                date_range  TEXT DEFAULT '',
                etl_timestamp TEXT DEFAULT ''
            );
        """)
        conn.commit()
        conn.close()

    # ── Point-in-time queries ───────────────────────────────────────

    def get_fundamentals_as_of(
        self,
        ticker: str,
        as_of_date: str,
        n_quarters: int = 8,
    ) -> list[dict]:
        """
        Return up to n_quarters of Compustat rows where rdq <= as_of_date.
        Ordered by datadate DESC (most recent available quarter first).

        Returns dicts with FMP-compatible field names for downstream compatibility.
        """
        conn = self._conn()
        rows = conn.execute("""
            SELECT * FROM compustat_quarterly
            WHERE ticker = ? AND rdq <= ?
            ORDER BY datadate DESC
            LIMIT ?
        """, (ticker.upper(), as_of_date, n_quarters)).fetchall()
        conn.close()

        return [self._compustat_to_fmp_dict(dict(r)) for r in rows]

    def get_ibes_consensus_as_of(
        self,
        ticker: str,
        as_of_date: str,
        fpi: str = "1",
        n_periods: int = 12,
    ) -> list[dict]:
        """
        Return up to n_periods IBES consensus rows where statpers <= as_of_date.
        Ordered by statpers DESC (most recent consensus first).

        Args:
            fpi: "1" = current fiscal year, "2" = next fiscal year
        """
        conn = self._conn()
        rows = conn.execute("""
            SELECT * FROM ibes_consensus
            WHERE ticker = ? AND statpers <= ? AND fpi = ?
            ORDER BY statpers DESC
            LIMIT ?
        """, (ticker.upper(), as_of_date, fpi, n_periods)).fetchall()
        conn.close()

        return [dict(r) for r in rows]

    def get_ibes_actuals_as_of(
        self,
        ticker: str,
        as_of_date: str,
        n_quarters: int = 8,
    ) -> list[dict]:
        """
        Return up to n_quarters of IBES actual EPS where anndats <= as_of_date.
        """
        conn = self._conn()
        rows = conn.execute("""
            SELECT * FROM ibes_actuals
            WHERE ticker = ? AND anndats <= ?
            ORDER BY pends DESC
            LIMIT ?
        """, (ticker.upper(), as_of_date, n_quarters)).fetchall()
        conn.close()

        return [dict(r) for r in rows]

    def get_ticker_link(self, ticker: str) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM ticker_link WHERE ticker = ? ORDER BY link_start DESC LIMIT 1",
            (ticker.upper(),),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    # ── Ingestion ───────────────────────────────────────────────────

    def ingest_compustat(self, df: pd.DataFrame) -> int:
        """Insert Compustat quarterly rows. Returns count inserted."""
        conn = self._conn()
        n = 0
        for _, row in df.iterrows():
            rdq = row.get("rdq")
            rdq_inferred = 0
            if pd.isna(rdq) or rdq is None:
                # Fallback: datadate + 45 days
                datadate = pd.to_datetime(row["datadate"])
                rdq = (datadate + pd.DateOffset(days=45)).strftime("%Y-%m-%d")
                rdq_inferred = 1
            else:
                rdq = str(rdq)[:10]

            try:
                conn.execute("""
                    INSERT OR REPLACE INTO compustat_quarterly
                    (gvkey, ticker, datadate, rdq, fyearq, fqtr,
                     atq, ceqq, ltq, dlcq, dlttq, cheq, actq, lctq,
                     saleq, revtq, niq, ibq, oancfy, epsfxq, epspiq, capxy,
                     cogsq, xsgaq, cshoq, rdq_inferred)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    str(row.get("gvkey", "")),
                    str(row.get("tic", row.get("ticker", ""))).upper(),
                    str(row["datadate"])[:10],
                    rdq,
                    int(row["fyearq"]) if pd.notna(row.get("fyearq")) else None,
                    int(row["fqtr"]) if pd.notna(row.get("fqtr")) else None,
                    self._float(row, "atq"), self._float(row, "ceqq"),
                    self._float(row, "ltq"), self._float(row, "dlcq"),
                    self._float(row, "dlttq"), self._float(row, "cheq"),
                    self._float(row, "actq"), self._float(row, "lctq"),
                    self._float(row, "saleq"), self._float(row, "revtq"),
                    self._float(row, "niq"), self._float(row, "ibq"),
                    self._float(row, "oancfy"), self._float(row, "epsfxq"),
                    self._float(row, "epspiq"), self._float(row, "capxy"),
                    self._float(row, "cogsq"), self._float(row, "xsgaq"),
                    self._float(row, "cshoq"),
                    rdq_inferred,
                ))
                n += 1
            except Exception as exc:
                logger.debug("Compustat ingest error: %s", exc)
        conn.commit()
        conn.close()
        return n

    def ingest_ibes_consensus(self, df: pd.DataFrame) -> int:
        """Insert IBES consensus rows."""
        conn = self._conn()
        n = 0
        for _, row in df.iterrows():
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO ibes_consensus
                    (ticker, statpers, fpedats, fpi, meanest, medest, stdev, numest, numup, numdown)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (
                    str(row["ticker"]).upper(),
                    str(row["statpers"])[:10],
                    str(row["fpedats"])[:10],
                    str(row.get("fpi", "1")),
                    self._float(row, "meanest"), self._float(row, "medest"),
                    self._float(row, "stdev"), self._float(row, "numest"),
                    self._float(row, "numup"), self._float(row, "numdown"),
                ))
                n += 1
            except Exception as exc:
                logger.debug("IBES consensus ingest error: %s", exc)
        conn.commit()
        conn.close()
        return n

    def ingest_ibes_actuals(self, df: pd.DataFrame) -> int:
        """Insert IBES actuals rows."""
        conn = self._conn()
        n = 0
        for _, row in df.iterrows():
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO ibes_actuals
                    (ticker, pends, anndats, value, pdicity)
                    VALUES (?,?,?,?,?)
                """, (
                    str(row["ticker"]).upper(),
                    str(row["pends"])[:10],
                    str(row["anndats"])[:10],
                    self._float(row, "value"),
                    str(row.get("pdicity", "QTR")),
                ))
                n += 1
            except Exception as exc:
                logger.debug("IBES actuals ingest error: %s", exc)
        conn.commit()
        conn.close()
        return n

    def ingest_ticker_links(self, df: pd.DataFrame) -> int:
        """Insert ticker link rows."""
        conn = self._conn()
        n = 0
        for _, row in df.iterrows():
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO ticker_link
                    (ticker, gvkey, permno, ibes_ticker, cusip8, link_start, link_end)
                    VALUES (?,?,?,?,?,?,?)
                """, (
                    str(row.get("ticker", "")).upper(),
                    str(row.get("gvkey", "")),
                    int(row["permno"]) if pd.notna(row.get("permno")) else None,
                    str(row.get("ibes_ticker", "")).upper() if pd.notna(row.get("ibes_ticker")) else None,
                    str(row.get("cusip8", "")) if pd.notna(row.get("cusip8")) else None,
                    str(row.get("link_start", ""))[:10],
                    str(row.get("link_end", ""))[:10] if pd.notna(row.get("link_end")) else "2099-12-31",
                ))
                n += 1
            except Exception as exc:
                logger.debug("Ticker link ingest error: %s", exc)
        conn.commit()
        conn.close()
        return n

    def save_commercial_tags(self) -> None:
        """Write all commercial migration tags to the database."""
        conn = self._conn()
        for table_name, tag in COMMERCIAL_TAGS.items():
            conn.execute("""
                INSERT OR REPLACE INTO commercial_tags (table_name, tag_json, etl_timestamp)
                VALUES (?, ?, ?)
            """, (table_name, json.dumps(tag), time.strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()

    # ── Summary ─────────────────────────────────────────────────────

    def summary(self) -> dict:
        conn = self._conn()
        result = {}
        for table in ["compustat_quarterly", "ibes_consensus", "ibes_actuals", "ticker_link"]:
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
            result[table] = row["cnt"]
        # Ticker counts
        result["compustat_tickers"] = conn.execute(
            "SELECT COUNT(DISTINCT ticker) FROM compustat_quarterly"
        ).fetchone()[0]
        result["ibes_tickers"] = conn.execute(
            "SELECT COUNT(DISTINCT ticker) FROM ibes_consensus"
        ).fetchone()[0]
        # Date ranges
        for table, col in [("compustat_quarterly", "datadate"), ("ibes_consensus", "statpers")]:
            r = conn.execute(f"SELECT MIN({col}) as mn, MAX({col}) as mx FROM {table}").fetchone()
            result[f"{table}_range"] = f"{r['mn']} to {r['mx']}" if r["mn"] else "empty"
        conn.close()
        return result

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _float(row, col):
        v = row.get(col)
        if v is None:
            return None
        try:
            if pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _compustat_to_fmp_dict(row: dict) -> dict:
        """Convert Compustat field names to FMP-compatible names."""
        return {
            "date": row.get("datadate", ""),
            "rdq": row.get("rdq", ""),
            "rdq_inferred": bool(row.get("rdq_inferred", 0)),
            "symbol": row.get("ticker", ""),
            "totalAssets": row.get("atq"),
            "totalStockholdersEquity": row.get("ceqq"),
            "totalLiabilities": row.get("ltq"),
            "shortTermDebt": row.get("dlcq"),
            "longTermDebt": row.get("dlttq"),
            "totalDebt": (row.get("dlcq") or 0) + (row.get("dlttq") or 0) if row.get("dlcq") is not None or row.get("dlttq") is not None else None,
            "cashAndCashEquivalents": row.get("cheq"),
            "totalCurrentAssets": row.get("actq"),
            "totalCurrentLiabilities": row.get("lctq"),
            "revenue": row.get("saleq") or row.get("revtq"),
            "netIncome": row.get("niq"),
            "incomeBeforeExtra": row.get("ibq"),
            "operatingCashFlow": row.get("oancfy"),
            "eps": row.get("epsfxq"),
            "epsDiluted": row.get("epspiq"),
            "capitalExpenditures": row.get("capxy"),
            "costOfRevenue": row.get("cogsq"),
            "sgaExpense": row.get("xsgaq"),
            "sharesOutstanding": row.get("cshoq"),
            "fiscalYear": row.get("fyearq"),
            "fiscalQuarter": row.get("fqtr"),
        }
