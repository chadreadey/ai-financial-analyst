"""
SQLite-based caching layer for SEC data.

Avoids redundant API calls across agents and across runs.
Each cache entry has a TTL (default 24 hours) so stale data
is automatically refreshed.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional


DEFAULT_TTL_SECONDS = 86400  # 24 hours


class SECCache:
    """Simple SQLite cache keyed by namespace + key, with TTL expiration."""

    def __init__(self, db_path: str = ".sec_cache.db"):
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self.db_path))
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
                ticker          TEXT NOT NULL,
                run_at          REAL NOT NULL,
                verdict         TEXT,
                conviction      TEXT,
                time_horizon    TEXT,
                composite_score REAL,
                health_scores   TEXT,
                PRIMARY KEY (ticker, run_at)
            )
            """
        )
        self._conn.commit()

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

    def set(
        self, namespace: str, key: str, value: Any, ttl: int = DEFAULT_TTL_SECONDS
    ) -> None:
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
    ) -> None:
        """Persist a structured analysis result for drift tracking."""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO analysis_history
                (ticker, run_at, verdict, conviction, time_horizon,
                 composite_score, health_scores)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker.upper(),
                time.time(),
                verdict,
                conviction,
                time_horizon,
                composite_score,
                json.dumps(health_scores) if health_scores else None,
            ),
        )
        self._conn.commit()

    def get_analysis_history(
        self, ticker: str, limit: int = 10
    ) -> list[dict]:
        """Return recent analysis history for a ticker, newest first."""
        rows = self._conn.execute(
            """
            SELECT run_at, verdict, conviction, time_horizon,
                   composite_score, health_scores
            FROM analysis_history
            WHERE ticker = ?
            ORDER BY run_at DESC
            LIMIT ?
            """,
            (ticker.upper(), limit),
        ).fetchall()

        results = []
        for row in rows:
            run_at, verdict, conviction, time_horizon, score, hs_json = row
            results.append({
                "run_at": run_at,
                "verdict": verdict,
                "conviction": conviction,
                "time_horizon": time_horizon,
                "composite_score": score,
                "health_scores": json.loads(hs_json) if hs_json else {},
            })
        return results

    def close(self) -> None:
        self._conn.close()
