"""Unified read facade for Modal CPCV backtests.

Both `backend.supabase_backtest` and `backend.cpcv_sqlite` expose the same
read-path surface — this module picks Supabase when available (the
authoritative store), falls back to SQLite when not. Callers (FastAPI router,
CLI inspection tools) use this so they don't have to care which backend is
configured.

The two stores are kept in sync by the orchestrator's dual-write path
(`modal_app/dispatcher.py`), so any drift would be a bug, not a consistency
question — we deliberately do not merge rows from both sides.

Row shape normalisation:
- Timestamps are ISO 8601 strings in both sources (Supabase returns them
  natively; SQLite floats are coerced in `_normalize_sqlite_run`).
- JSONB/TEXT columns are pre-parsed dicts in both sources.
- Array columns (`train_indices`, `test_indices`) arrive as Python lists
  from Supabase and from `_row_to_dict` in SQLite.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from backend import cpcv_sqlite, supabase_backtest


def _ts_to_iso(v) -> Optional[str]:
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(float(v), tz=timezone.utc).isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _normalize_sqlite_run(row: dict) -> dict:
    out = dict(row)
    for col in ("started_at", "finished_at", "updated_at", "created_at"):
        if col in out:
            out[col] = _ts_to_iso(out[col])
    # Match Supabase column names (SQLite uses `*_json` for array/dict columns)
    for legacy, new in (
        ("train_indices_json", "train_indices"),
        ("test_indices_json", "test_indices"),
        ("gates_json", "gates_json"),  # kept as-is for combos
        ("signals_at_entry_json", "signals_at_entry_json"),
        ("flags_json", "flags_json"),
    ):
        if legacy in out and legacy != new:
            out[new] = out.pop(legacy)
    return out


def _normalize_sqlite_rows(rows: list[dict]) -> list[dict]:
    return [_normalize_sqlite_run(r) for r in rows]


def source() -> str:
    """Which backend is currently serving reads."""
    return "supabase" if supabase_backtest.is_enabled() else "sqlite"


def list_runs(
    status: Optional[str] = None,
    config_hash: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    if supabase_backtest.is_enabled():
        r = supabase_backtest.list_runs(status=status, config_hash=config_hash,
                                         limit=limit, offset=offset)
        if r is not None:
            return r
    return _normalize_sqlite_rows(cpcv_sqlite.list_runs(
        status=status, config_hash=config_hash, limit=limit, offset=offset,
    ))


def get_run(run_id: str) -> Optional[dict]:
    if supabase_backtest.is_enabled():
        r = supabase_backtest.get_run(run_id)
        if r is not None:
            return r
    row = cpcv_sqlite.get_run(run_id)
    return _normalize_sqlite_run(row) if row else None


def find_runs_by_config_hash(config_hash: str, limit: int = 20) -> list[dict]:
    if supabase_backtest.is_enabled():
        r = supabase_backtest.find_runs_by_config_hash(config_hash, limit=limit)
        if r is not None:
            return r
    return _normalize_sqlite_rows(cpcv_sqlite.find_runs_by_config_hash(config_hash, limit=limit))


def get_combinations(
    run_id: str,
    order_by: str = "oos_sharpe",
    descending: bool = True,
    limit: Optional[int] = None,
    offset: int = 0,
) -> list[dict]:
    if supabase_backtest.is_enabled():
        r = supabase_backtest.get_combinations(run_id, order_by=order_by,
                                               descending=descending,
                                               limit=limit, offset=offset)
        if r is not None:
            return r
    return _normalize_sqlite_rows(cpcv_sqlite.get_combinations(
        run_id, order_by=order_by, descending=descending,
        limit=limit, offset=offset,
    ))


def get_trades(
    run_id: str,
    combo_idx: Optional[int] = None,
    ticker: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> list[dict]:
    if supabase_backtest.is_enabled():
        r = supabase_backtest.get_trades(run_id, combo_idx=combo_idx,
                                         ticker=ticker, limit=limit, offset=offset)
        if r is not None:
            return r
    return _normalize_sqlite_rows(cpcv_sqlite.get_trades(
        run_id, combo_idx=combo_idx, ticker=ticker, limit=limit, offset=offset,
    ))


def get_events(
    run_id: str,
    after_id: Optional[int] = None,
    limit: int = 200,
) -> list[dict]:
    if supabase_backtest.is_enabled():
        r = supabase_backtest.get_events(run_id, after_id=after_id, limit=limit)
        if r is not None:
            return r
    return _normalize_sqlite_rows(cpcv_sqlite.get_events(
        run_id, after_id=after_id, limit=limit,
    ))


__all__ = [
    "source",
    "list_runs",
    "get_run",
    "find_runs_by_config_hash",
    "get_combinations",
    "get_trades",
    "get_events",
]
