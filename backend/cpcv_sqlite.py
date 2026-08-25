"""SQLite persistence for Modal CPCV backtests.

Mirrors the table shapes of `supabase/migrations/0001_backtest_tables.sql`
but uses SQLite-native types (JSON stored as TEXT). Lives in
`settings.warehouse_db_path` — same database as the legacy `backtest_runs`
and `analysis_history` tables. We intentionally use NEW table names
(`cpcv_runs`, `cpcv_combinations`, `cpcv_trades`, `cpcv_events`) so we
don't clobber the legacy `backtest_runs` schema in backend/routers/backtest.py.

Every public function is safe to call repeatedly — tables are created on
first write.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from typing import Any, Optional

from config import settings


logger = logging.getLogger(__name__)


_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False


def _connect() -> sqlite3.Connection:
    db_path = settings.warehouse_db_path or ".sec_cache.db"
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cpcv_runs (
                run_id              TEXT PRIMARY KEY,
                config_hash         TEXT NOT NULL,
                git_sha             TEXT NOT NULL,
                status              TEXT NOT NULL DEFAULT 'queued',
                universe            TEXT,
                n_groups            INTEGER,
                n_test_groups       INTEGER,
                n_combinations      INTEGER,
                n_completed         INTEGER DEFAULT 0,
                n_skipped           INTEGER DEFAULT 0,
                n_failed            INTEGER DEFAULT 0,
                median_oos_sharpe   REAL,
                oos_sharpe_min      REAL,
                oos_sharpe_max      REAL,
                pbo                 REAL,
                deflated_sharpe     REAL,
                config_json         TEXT NOT NULL,
                metrics_json        TEXT,
                error               TEXT,
                modal_call_id       TEXT,
                started_at          REAL NOT NULL,
                finished_at         REAL,
                updated_at          REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cpcv_runs_config_hash
                ON cpcv_runs (config_hash, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_cpcv_runs_status
                ON cpcv_runs (status, started_at DESC);

            CREATE TABLE IF NOT EXISTS cpcv_combinations (
                run_id              TEXT NOT NULL,
                combo_idx           INTEGER NOT NULL,
                status              TEXT NOT NULL DEFAULT 'complete',
                train_indices_json  TEXT,
                test_indices_json   TEXT,
                oos_sharpe          REAL,
                return_pct          REAL,
                n_trades            INTEGER,
                n_test_dates        INTEGER,
                elapsed_seconds     REAL,
                git_sha             TEXT,
                error               TEXT,
                gates_json          TEXT,
                created_at          REAL NOT NULL,
                PRIMARY KEY (run_id, combo_idx)
            );
            CREATE INDEX IF NOT EXISTS idx_cpcv_combinations_run_sharpe
                ON cpcv_combinations (run_id, oos_sharpe DESC);

            CREATE TABLE IF NOT EXISTS cpcv_trades (
                run_id                  TEXT NOT NULL,
                combo_idx               INTEGER NOT NULL,
                trade_idx               INTEGER NOT NULL,
                ticker                  TEXT NOT NULL,
                direction               TEXT NOT NULL,
                entry_date              TEXT NOT NULL,
                exit_date               TEXT,
                entry_price             REAL,
                exit_price              REAL,
                pnl_dollar              REAL,
                pnl_pct                 REAL,
                holding_days            INTEGER,
                exit_reason             TEXT,
                composite_score         REAL,
                regime_at_entry         TEXT,
                signals_at_entry_json   TEXT,
                flags_json              TEXT,
                created_at              REAL NOT NULL,
                PRIMARY KEY (run_id, combo_idx, trade_idx)
            );
            CREATE INDEX IF NOT EXISTS idx_cpcv_trades_run_ticker
                ON cpcv_trades (run_id, ticker);
            CREATE INDEX IF NOT EXISTS idx_cpcv_trades_run_combo
                ON cpcv_trades (run_id, combo_idx);

            CREATE TABLE IF NOT EXISTS cpcv_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT NOT NULL,
                kind        TEXT NOT NULL,
                combo_idx   INTEGER,
                payload     TEXT,
                created_at  REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cpcv_events_run_id
                ON cpcv_events (run_id, id);
            """
        )
        conn.commit()
        _SCHEMA_READY = True


def _jdump(v: Any) -> Optional[str]:
    if v is None:
        return None
    try:
        return json.dumps(v, default=_json_default)
    except Exception:
        return None


def _json_default(v):
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "item"):
        return v.item()
    return str(v)


# ── cpcv_runs ────────────────────────────────────────────────────────────


def upsert_run(row: dict[str, Any]) -> bool:
    """Insert or update a cpcv_runs row (keyed by run_id)."""
    try:
        conn = _connect()
        try:
            _ensure_schema(conn)
            now = time.time()
            payload = {
                "run_id": row["run_id"],
                "config_hash": row["config_hash"],
                "git_sha": row["git_sha"],
                "status": row.get("status", "queued"),
                "universe": row.get("universe"),
                "n_groups": row.get("n_groups"),
                "n_test_groups": row.get("n_test_groups"),
                "n_combinations": row.get("n_combinations"),
                "n_completed": row.get("n_completed", 0),
                "n_skipped": row.get("n_skipped", 0),
                "n_failed": row.get("n_failed", 0),
                "median_oos_sharpe": row.get("median_oos_sharpe"),
                "oos_sharpe_min": row.get("oos_sharpe_min"),
                "oos_sharpe_max": row.get("oos_sharpe_max"),
                "pbo": row.get("pbo"),
                "deflated_sharpe": row.get("deflated_sharpe"),
                "config_json": _jdump(row.get("config_json", {})) or "{}",
                "metrics_json": _jdump(row.get("metrics_json")),
                "error": row.get("error"),
                "modal_call_id": row.get("modal_call_id"),
                "started_at": row.get("started_at", now),
                "finished_at": row.get("finished_at"),
                "updated_at": now,
            }
            cols = ", ".join(payload.keys())
            placeholders = ", ".join(f":{k}" for k in payload)
            updates = ", ".join(
                f"{k}=excluded.{k}" for k in payload if k not in ("run_id", "started_at")
            )
            conn.execute(
                f"""
                INSERT INTO cpcv_runs ({cols}) VALUES ({placeholders})
                ON CONFLICT(run_id) DO UPDATE SET {updates}
                """,
                payload,
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("sqlite upsert_run failed: %s", exc)
        return False


# Columns patch_run is allowed to touch. Excludes run_id (primary key)
# and created_at (immutable). Derived from the schema at
# `_ensure_schema` — update together when adding new columns.
_PATCHABLE_RUN_COLS: frozenset[str] = frozenset(
    {
        "config_hash",
        "git_sha",
        "status",
        "universe",
        "n_groups",
        "n_test_groups",
        "n_combinations",
        "n_completed",
        "n_skipped",
        "n_failed",
        "median_oos_sharpe",
        "oos_sharpe_min",
        "oos_sharpe_max",
        "pbo",
        "deflated_sharpe",
        "config_json",
        "metrics_json",
        "error",
        "modal_call_id",
        "started_at",
        "finished_at",
    }
)


def patch_run(run_id: str, patch: dict[str, Any]) -> bool:
    """Targeted UPDATE of specific columns on a cpcv_runs row."""
    if not patch:
        return False
    unknown = set(patch.keys()) - _PATCHABLE_RUN_COLS
    if unknown:
        raise ValueError(
            f"patch_run: unknown columns {sorted(unknown)} (allowed: {sorted(_PATCHABLE_RUN_COLS)})"
        )
    try:
        conn = _connect()
        try:
            _ensure_schema(conn)
            cols = ", ".join(f"{k}=?" for k in patch)
            params = list(patch.values()) + [time.time(), run_id]
            conn.execute(
                f"UPDATE cpcv_runs SET {cols}, updated_at=? WHERE run_id=?",
                params,
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("sqlite patch_run failed: %s", exc)
        return False


# ── cpcv_combinations ────────────────────────────────────────────────────


def insert_combinations_batch(rows: list[dict[str, Any]]) -> tuple[int, int]:
    if not rows:
        return (0, 0)
    try:
        conn = _connect()
        try:
            _ensure_schema(conn)
            now = time.time()
            payloads = [
                (
                    r["run_id"],
                    r["combo_idx"],
                    r.get("status", "complete"),
                    _jdump(r.get("train_indices")),
                    _jdump(r.get("test_indices")),
                    r.get("oos_sharpe"),
                    r.get("return_pct"),
                    r.get("n_trades"),
                    r.get("n_test_dates"),
                    r.get("elapsed_seconds"),
                    r.get("git_sha"),
                    r.get("error"),
                    _jdump(r.get("gates_json")),
                    now,
                )
                for r in rows
            ]
            conn.executemany(
                """
                INSERT OR REPLACE INTO cpcv_combinations (
                    run_id, combo_idx, status, train_indices_json, test_indices_json,
                    oos_sharpe, return_pct, n_trades, n_test_dates, elapsed_seconds,
                    git_sha, error, gates_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payloads,
            )
            conn.commit()
            return (len(rows), 0)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("sqlite insert_combinations_batch failed: %s", exc)
        return (0, len(rows))


# ── cpcv_trades ──────────────────────────────────────────────────────────


def insert_trades_batch(rows: list[dict[str, Any]]) -> tuple[int, int]:
    if not rows:
        return (0, 0)
    try:
        conn = _connect()
        try:
            _ensure_schema(conn)
            now = time.time()
            payloads = [
                (
                    r["run_id"],
                    r["combo_idx"],
                    r["trade_idx"],
                    r["ticker"],
                    r["direction"],
                    r["entry_date"],
                    r.get("exit_date"),
                    r.get("entry_price"),
                    r.get("exit_price"),
                    r.get("pnl_dollar"),
                    r.get("pnl_pct"),
                    r.get("holding_days"),
                    r.get("exit_reason"),
                    r.get("composite_score"),
                    r.get("regime_at_entry"),
                    _jdump(r.get("signals_at_entry_json")),
                    _jdump(r.get("flags_json")),
                    now,
                )
                for r in rows
            ]
            conn.executemany(
                """
                INSERT OR REPLACE INTO cpcv_trades (
                    run_id, combo_idx, trade_idx, ticker, direction,
                    entry_date, exit_date, entry_price, exit_price,
                    pnl_dollar, pnl_pct, holding_days, exit_reason,
                    composite_score, regime_at_entry, signals_at_entry_json,
                    flags_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payloads,
            )
            conn.commit()
            return (len(rows), 0)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("sqlite insert_trades_batch failed: %s", exc)
        return (0, len(rows))


# ── cpcv_events ──────────────────────────────────────────────────────────


def insert_event(row: dict[str, Any]) -> bool:
    try:
        conn = _connect()
        try:
            _ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO cpcv_events (run_id, kind, combo_idx, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["run_id"],
                    row["kind"],
                    row.get("combo_idx"),
                    _jdump(row.get("payload")),
                    row.get("created_at", time.time()),
                ),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("sqlite insert_event failed: %s", exc)
        return False


# ── read-path helpers (Session 2b) ──────────────────────────────────────
#
# All return plain dicts (JSON columns pre-parsed). Safe to call before any
# write has happened — tables are created on first access.
#
# NB: these power the FastAPI `/api/backtest/modal/*` endpoints as a fallback
# when Supabase is disabled, and are also used by the stale-run sweeper.

_RUN_COLS = [
    "run_id",
    "config_hash",
    "git_sha",
    "status",
    "universe",
    "n_groups",
    "n_test_groups",
    "n_combinations",
    "n_completed",
    "n_skipped",
    "n_failed",
    "median_oos_sharpe",
    "oos_sharpe_min",
    "oos_sharpe_max",
    "pbo",
    "deflated_sharpe",
    "config_json",
    "metrics_json",
    "error",
    "modal_call_id",
    "started_at",
    "finished_at",
    "updated_at",
]

_COMBO_COLS = [
    "run_id",
    "combo_idx",
    "status",
    "train_indices_json",
    "test_indices_json",
    "oos_sharpe",
    "return_pct",
    "n_trades",
    "n_test_dates",
    "elapsed_seconds",
    "git_sha",
    "error",
    "gates_json",
    "created_at",
]

_TRADE_COLS = [
    "run_id",
    "combo_idx",
    "trade_idx",
    "ticker",
    "direction",
    "entry_date",
    "exit_date",
    "entry_price",
    "exit_price",
    "pnl_dollar",
    "pnl_pct",
    "holding_days",
    "exit_reason",
    "composite_score",
    "regime_at_entry",
    "signals_at_entry_json",
    "flags_json",
    "created_at",
]

_EVENT_COLS = ["id", "run_id", "kind", "combo_idx", "payload", "created_at"]

_JSON_RUN_COLS = {"config_json", "metrics_json"}
_JSON_COMBO_COLS = {"train_indices_json", "test_indices_json", "gates_json"}
_JSON_TRADE_COLS = {"signals_at_entry_json", "flags_json"}
_JSON_EVENT_COLS = {"payload"}


# Map SQLite _json suffix column names to their Supabase equivalents so
# all callers (not just the reader facade) get consistent key names.
_SQLITE_COL_ALIASES = {
    "train_indices_json": "train_indices",
    "test_indices_json": "test_indices",
}


def _row_to_dict(row: sqlite3.Row, json_cols: set[str]) -> dict:
    out = dict(row)
    for col in json_cols & out.keys():
        v = out[col]
        if isinstance(v, str) and v:
            try:
                out[col] = json.loads(v)
            except Exception:
                pass
    # Rename _json-suffixed cols to match Supabase column names.
    for old, new in _SQLITE_COL_ALIASES.items():
        if old in out:
            out[new] = out.pop(old)
    return out


def _query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    try:
        conn = _connect()
        try:
            _ensure_schema(conn)
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql, params)
            return cur.fetchall()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("sqlite query failed (%s): %s", sql.split()[0], exc)
        return []


def list_runs(
    status: Optional[str] = None,
    config_hash: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Most recent runs first, optionally filtered by status/config_hash."""
    where = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status)
    if config_hash:
        where.append("config_hash = ?")
        params.append(config_hash)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = (
        f"SELECT {', '.join(_RUN_COLS)} FROM cpcv_runs "
        f"{where_sql} ORDER BY started_at DESC LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])
    return [_row_to_dict(r, _JSON_RUN_COLS) for r in _query(sql, tuple(params))]


def get_run(run_id: str) -> Optional[dict]:
    rows = _query(
        f"SELECT {', '.join(_RUN_COLS)} FROM cpcv_runs WHERE run_id = ? LIMIT 1",
        (run_id,),
    )
    return _row_to_dict(rows[0], _JSON_RUN_COLS) if rows else None


def find_runs_by_config_hash(config_hash: str, limit: int = 20) -> list[dict]:
    return list_runs(config_hash=config_hash, limit=limit)


def get_combinations(
    run_id: str,
    order_by: str = "oos_sharpe",
    descending: bool = True,
    limit: Optional[int] = None,
    offset: int = 0,
) -> list[dict]:
    allowed = {"oos_sharpe", "combo_idx", "return_pct", "n_trades"}
    col = order_by if order_by in allowed else "oos_sharpe"
    direction = "DESC" if descending else "ASC"
    sql = (
        f"SELECT {', '.join(_COMBO_COLS)} FROM cpcv_combinations "
        f"WHERE run_id = ? ORDER BY {col} {direction} NULLS LAST"
    )
    params: list[Any] = [run_id]
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return [_row_to_dict(r, _JSON_COMBO_COLS) for r in _query(sql, tuple(params))]


def get_trades(
    run_id: str,
    combo_idx: Optional[int] = None,
    ticker: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> list[dict]:
    where = ["run_id = ?"]
    params: list[Any] = [run_id]
    if combo_idx is not None:
        where.append("combo_idx = ?")
        params.append(combo_idx)
    if ticker:
        where.append("ticker = ?")
        params.append(ticker)
    sql = (
        f"SELECT {', '.join(_TRADE_COLS)} FROM cpcv_trades "
        f"WHERE {' AND '.join(where)} "
        f"ORDER BY combo_idx ASC, trade_idx ASC"
    )
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return [_row_to_dict(r, _JSON_TRADE_COLS) for r in _query(sql, tuple(params))]


def get_events(
    run_id: str,
    after_id: Optional[int] = None,
    limit: int = 200,
) -> list[dict]:
    where = ["run_id = ?"]
    params: list[Any] = [run_id]
    if after_id is not None:
        where.append("id > ?")
        params.append(after_id)
    sql = (
        f"SELECT {', '.join(_EVENT_COLS)} FROM cpcv_events "
        f"WHERE {' AND '.join(where)} ORDER BY id ASC LIMIT ?"
    )
    params.append(limit)
    return [_row_to_dict(r, _JSON_EVENT_COLS) for r in _query(sql, tuple(params))]


def sweep_stale_runs(max_age_seconds: Optional[float] = None) -> int:
    """Mark any run whose `updated_at` heartbeat is older than the cutoff failed.

    Returns the number of rows marked. Called by a simple cron/sweeper or on
    FastAPI startup. Matches the same cutoff used for Supabase (orchestrator
    is responsible for mirroring the final state when it can).
    """
    if max_age_seconds is None:
        max_age_seconds = float(getattr(settings, "cpcv_stale_sweep_seconds", 30 * 60))
    try:
        conn = _connect()
        try:
            _ensure_schema(conn)
            cutoff = time.time() - max_age_seconds
            cur = conn.execute(
                """
                UPDATE cpcv_runs
                   SET status = 'failed',
                       error = COALESCE(error, 'stale run: no terminal event within timeout'),
                       finished_at = COALESCE(finished_at, ?),
                       updated_at = ?
                 WHERE status = 'running'
                   AND COALESCE(updated_at, started_at) < ?
                """,
                (time.time(), time.time(), cutoff),
            )
            conn.commit()
            return cur.rowcount or 0
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("sqlite sweep_stale_runs failed: %s", exc)
        return 0


__all__ = [
    "upsert_run",
    "patch_run",
    "insert_combinations_batch",
    "insert_trades_batch",
    "insert_event",
    "list_runs",
    "get_run",
    "find_runs_by_config_hash",
    "get_combinations",
    "get_trades",
    "get_events",
    "sweep_stale_runs",
]
