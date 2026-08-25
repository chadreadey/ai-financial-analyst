"""
SQLite-based caching layer for SEC data.

Avoids redundant API calls across agents and across runs.
Each cache entry has a TTL (default 24 hours) so stale data
is automatically refreshed.
"""

import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from config import settings


DEFAULT_TTL_SECONDS = 86400  # 24 hours
logger = logging.getLogger(__name__)


class SECCache:
    """Simple SQLite cache keyed by namespace + key, with TTL expiration."""

    def __init__(self, db_path: str = ""):
        resolved = (db_path or settings.warehouse_db_path or ".sec_cache.db").strip()
        self.db_path = Path(resolved)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                namespace TEXT NOT NULL,
                key       TEXT NOT NULL,
                value     TEXT NOT NULL,
                expires   REAL NOT NULL,
                PRIMARY KEY (namespace, key)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_history (
                analysis_id       TEXT PRIMARY KEY,
                ticker            TEXT NOT NULL,
                run_at            REAL NOT NULL,
                company_name      TEXT,
                verdict           TEXT,
                conviction        TEXT,
                time_horizon      TEXT,
                composite_score   REAL,
                health_scores     TEXT,
                price_target      REAL,
                stop_loss_value   REAL,
                stop_loss_unit    TEXT,
                entry_price_at_run REAL,
                result_json       TEXT
            )
            """
        )
        self._migrate_analysis_history_schema()
        self._conn.commit()

    def _column_exists(self, table: str, column: str) -> bool:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r[1] == column for r in rows)

    def _migrate_analysis_history_schema(self) -> None:
        migration_columns = [
            ("analysis_id", "TEXT"),
            ("company_name", "TEXT"),
            ("price_target", "REAL"),
            ("stop_loss_value", "REAL"),
            ("stop_loss_unit", "TEXT"),
            ("entry_price_at_run", "REAL"),
            ("result_json", "TEXT"),
            ("conviction_score", "REAL"),
            ("bull_probability", "REAL"),
            ("bear_probability", "REAL"),
            ("weighted_score", "REAL"),
            ("sizing_guidance", "TEXT"),
        ]
        for column, col_type in migration_columns:
            if not self._column_exists("analysis_history", column):
                self._conn.execute(f"ALTER TABLE analysis_history ADD COLUMN {column} {col_type}")

        if not self._column_exists("analysis_history", "analysis_id"):
            return

        self._conn.execute(
            """
            UPDATE analysis_history
            SET analysis_id = lower(hex(randomblob(16)))
            WHERE analysis_id IS NULL OR analysis_id = ''
            """
        )
        self._conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_history_analysis_id
            ON analysis_history(analysis_id)
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_analysis_history_ticker_run_at
            ON analysis_history(ticker, run_at DESC)
            """
        )

    def get(self, namespace: str, key: str) -> Optional[Any]:
        """Return cached value or None if missing / expired."""
        row = self._conn.execute(
            "SELECT value, expires FROM cache WHERE namespace = ? AND key = ?",
            (namespace, key),
        ).fetchone()
        if row is None:
            return None
        value, expires = row
        if time.time() > expires:
            self.delete(namespace, key)
            return None
        return json.loads(value)

    def set(self, namespace: str, key: str, value: Any, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        """Store a value with a TTL."""
        expires = time.time() + ttl
        self._conn.execute(
            """
            INSERT INTO cache (namespace, key, value, expires)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace, key)
            DO UPDATE SET value = excluded.value, expires = excluded.expires
            """,
            (namespace, key, json.dumps(value), expires),
        )
        self._conn.commit()

    def delete(self, namespace: str, key: str) -> None:
        self._conn.execute(
            "DELETE FROM cache WHERE namespace = ? AND key = ?",
            (namespace, key),
        )
        self._conn.commit()

    def clear(self) -> None:
        """Remove all cached data."""
        self._conn.execute("DELETE FROM cache")
        self._conn.commit()

    # ── analysis history ─────────────────────────────────────────

    def save_analysis(
        self,
        ticker: str,
        verdict: str,
        conviction: str = "",
        time_horizon: str = "",
        composite_score: Optional[float] = None,
        health_scores: Optional[dict] = None,
        company_name: str = "",
        price_target: Optional[float] = None,
        stop_loss_value: Optional[float] = None,
        stop_loss_unit: str = "",
        entry_price_at_run: Optional[float] = None,
        result_json: Optional[dict] = None,
        run_at: Optional[float] = None,
        analysis_id: str = "",
        conviction_score: Optional[float] = None,
        bull_probability: Optional[float] = None,
        bear_probability: Optional[float] = None,
        weighted_score: Optional[float] = None,
        sizing_guidance: str = "",
    ) -> str:
        """Persist a structured analysis result for drift tracking."""
        analysis_id = analysis_id or str(uuid.uuid4())
        run_at = run_at or time.time()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO analysis_history (
                analysis_id, ticker, run_at, company_name, verdict, conviction,
                time_horizon, composite_score, health_scores, price_target,
                stop_loss_value, stop_loss_unit, entry_price_at_run, result_json,
                conviction_score, bull_probability, bear_probability,
                weighted_score, sizing_guidance
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_id,
                ticker.upper(),
                run_at,
                company_name,
                verdict,
                conviction,
                time_horizon,
                composite_score,
                json.dumps(health_scores) if health_scores else None,
                price_target,
                stop_loss_value,
                stop_loss_unit,
                entry_price_at_run,
                json.dumps(result_json) if result_json else None,
                conviction_score,
                bull_probability,
                bear_probability,
                weighted_score,
                sizing_guidance,
            ),
        )
        self._conn.commit()
        if settings.enable_supabase_history:
            try:
                from sec.supabase_history import upsert_record

                upsert_record(
                    {
                        "analysis_id": analysis_id,
                        "ticker": ticker.upper(),
                        "run_at": run_at,
                        "company_name": company_name,
                        "verdict": verdict,
                        "conviction": conviction,
                        "time_horizon": time_horizon,
                        "composite_score": composite_score,
                        "health_scores": health_scores or {},
                        "price_target": price_target,
                        "stop_loss_value": stop_loss_value,
                        "stop_loss_unit": stop_loss_unit,
                        "entry_price_at_run": entry_price_at_run,
                        "result_json": result_json or {},
                    }
                )
            except Exception as exc:
                logger.debug("Supabase upsert failed: %s", exc)
        return analysis_id

    def get_analysis_history(
        self, ticker: str = "", limit: int = 10, offset: int = 0
    ) -> list[dict]:
        """Return recent analysis history, optionally filtered by ticker."""
        if settings.enable_supabase_history:
            try:
                from sec.supabase_history import fetch_history

                remote = fetch_history(ticker=ticker, limit=limit, offset=offset)
                if remote is not None:
                    return [
                        {
                            "analysis_id": str(row.get("analysis_id") or ""),
                            "ticker": str(row.get("ticker") or ""),
                            "run_at": float(row.get("run_at") or 0),
                            "company_name": str(row.get("company_name") or ""),
                            "verdict": row.get("verdict"),
                            "conviction": row.get("conviction"),
                            "time_horizon": row.get("time_horizon"),
                            "composite_score": row.get("composite_score"),
                            "health_scores": row.get("health_scores") or {},
                            "price_target": row.get("price_target"),
                            "stop_loss_value": row.get("stop_loss_value"),
                            "stop_loss_unit": str(row.get("stop_loss_unit") or ""),
                            "entry_price_at_run": row.get("entry_price_at_run"),
                        }
                        for row in remote
                    ]
            except Exception as exc:
                logger.debug("Supabase history read failed: %s", exc)

        if ticker:
            rows = self._conn.execute(
                """
                SELECT analysis_id, ticker, run_at, company_name, verdict, conviction,
                       time_horizon, composite_score, health_scores, price_target,
                       stop_loss_value, stop_loss_unit, entry_price_at_run
                FROM analysis_history
                WHERE ticker = ?
                ORDER BY run_at DESC
                LIMIT ? OFFSET ?
                """,
                (ticker.upper(), limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT analysis_id, ticker, run_at, company_name, verdict, conviction,
                       time_horizon, composite_score, health_scores, price_target,
                       stop_loss_value, stop_loss_unit, entry_price_at_run
                FROM analysis_history
                ORDER BY run_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        results = []
        for row in rows:
            (
                analysis_id,
                ticker_val,
                run_at,
                company_name,
                verdict,
                conviction,
                time_horizon,
                score,
                hs_json,
                price_target,
                stop_loss_value,
                stop_loss_unit,
                entry_price_at_run,
            ) = row
            results.append(
                {
                    "analysis_id": analysis_id or "",
                    "ticker": ticker_val,
                    "run_at": run_at,
                    "company_name": company_name or "",
                    "verdict": verdict,
                    "conviction": conviction,
                    "time_horizon": time_horizon,
                    "composite_score": score,
                    "health_scores": json.loads(hs_json) if hs_json else {},
                    "price_target": price_target,
                    "stop_loss_value": stop_loss_value,
                    "stop_loss_unit": stop_loss_unit or "",
                    "entry_price_at_run": entry_price_at_run,
                }
            )
        return results

    def get_analysis_detail(self, analysis_id: str) -> Optional[dict]:
        if settings.enable_supabase_history:
            try:
                from sec.supabase_history import fetch_detail

                remote = fetch_detail(analysis_id)
                if remote:
                    return {
                        "analysis_id": str(remote.get("analysis_id") or ""),
                        "ticker": str(remote.get("ticker") or ""),
                        "run_at": float(remote.get("run_at") or 0),
                        "company_name": str(remote.get("company_name") or ""),
                        "verdict": remote.get("verdict"),
                        "conviction": remote.get("conviction"),
                        "time_horizon": remote.get("time_horizon"),
                        "composite_score": remote.get("composite_score"),
                        "health_scores": remote.get("health_scores") or {},
                        "price_target": remote.get("price_target"),
                        "stop_loss_value": remote.get("stop_loss_value"),
                        "stop_loss_unit": str(remote.get("stop_loss_unit") or ""),
                        "entry_price_at_run": remote.get("entry_price_at_run"),
                        "result_json": remote.get("result_json"),
                    }
            except Exception as exc:
                logger.debug("Supabase detail read failed: %s", exc)

        row = self._conn.execute(
            """
            SELECT analysis_id, ticker, run_at, company_name, verdict, conviction,
                   time_horizon, composite_score, health_scores, price_target,
                   stop_loss_value, stop_loss_unit, entry_price_at_run, result_json
            FROM analysis_history
            WHERE analysis_id = ?
            """,
            (analysis_id,),
        ).fetchone()
        if row is None:
            return None

        (
            analysis_id_val,
            ticker,
            run_at,
            company_name,
            verdict,
            conviction,
            time_horizon,
            score,
            hs_json,
            price_target,
            stop_loss_value,
            stop_loss_unit,
            entry_price_at_run,
            result_json,
        ) = row
        return {
            "analysis_id": analysis_id_val,
            "ticker": ticker,
            "run_at": run_at,
            "company_name": company_name or "",
            "verdict": verdict,
            "conviction": conviction,
            "time_horizon": time_horizon,
            "composite_score": score,
            "health_scores": json.loads(hs_json) if hs_json else {},
            "price_target": price_target,
            "stop_loss_value": stop_loss_value,
            "stop_loss_unit": stop_loss_unit or "",
            "entry_price_at_run": entry_price_at_run,
            "result_json": json.loads(result_json) if result_json else None,
        }

    def close(self) -> None:
        self._conn.close()
