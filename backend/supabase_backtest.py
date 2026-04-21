"""Supabase write-path client for Modal CPCV backtests.

Mirrors the urllib/PostgREST idiom from `sec/supabase_history.py` — no
`supabase-py` dependency. Graceful no-op when credentials are absent: every
write returns (ok: bool, written: int) and silently swallows HTTP errors so
the orchestrator's streaming loop never crashes mid-run.

Writes: `backtest_runs`, `backtest_combinations`, `backtest_trades`,
`backtest_events`. See `supabase/migrations/0001_backtest_tables.sql`.

Gated by the existing `ENABLE_SUPABASE_HISTORY` flag. We reuse the single
flag instead of adding another — if a user wants only backtest sync or only
analysis sync, we can split in a follow-up.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import settings


logger = logging.getLogger(__name__)


# PostgREST payload cap on Supabase free tier is ~1 MB. 500 combo rows fit
# comfortably (~200 B each); 2000 trade rows fit (~1 KB each with full JSONB).
_COMBO_CHUNK = 500
_TRADE_CHUNK = 2000
_HTTP_TIMEOUT = 15.0

# Explicit column projections — never use select=* in bulk reads.
_RUNS_COLS = (
    "run_id,config_hash,git_sha,status,universe,"
    "n_groups,n_test_groups,n_combinations,"
    "n_completed,n_skipped,n_failed,"
    "median_oos_sharpe,oos_sharpe_min,oos_sharpe_max,"
    "pbo,deflated_sharpe,config_json,metrics_json,"
    "error,modal_call_id,started_at,finished_at,updated_at"
)
_COMBO_COLS = (
    "run_id,combo_idx,status,train_indices,test_indices,"
    "oos_sharpe,return_pct,n_trades,n_test_dates,"
    "elapsed_seconds,git_sha,error,gates_json,created_at"
)
# signals_at_entry_json intentionally excluded — use get_trade_detail for drill-down.
_TRADE_COLS_LIST = (
    "run_id,combo_idx,trade_idx,ticker,direction,"
    "entry_date,exit_date,entry_price,exit_price,"
    "pnl_dollar,pnl_pct,holding_days,exit_reason,"
    "composite_score,regime_at_entry,flags_json,created_at"
)
_TRADE_COLS_DETAIL = _TRADE_COLS_LIST + ",signals_at_entry_json"
_EVENT_COLS = "id,run_id,kind,combo_idx,payload,created_at"

import os
import pathlib

_FAILED_BATCH_LOG = pathlib.Path(
    os.environ.get("SUPABASE_FAILED_BATCH_LOG", "/tmp/supabase_failed_batches.jsonl")
)


def _append_failed_batch(table: str, rows: list[dict]) -> None:
    """Append a failed batch to a local JSONL for manual replay."""
    try:
        with _FAILED_BATCH_LOG.open("a") as fh:
            fh.write(json.dumps({"table": table, "rows": rows,
                                 "ts": datetime.now(timezone.utc).isoformat()},
                                default=_json_default) + "\n")
    except Exception as exc:
        logger.error("Could not write failed batch to %s: %s", _FAILED_BATCH_LOG, exc)


def is_enabled() -> bool:
    return (
        settings.enable_supabase_history
        and bool(settings.supabase_url.strip())
        and bool(settings.supabase_service_key.strip())
    )


def _rest_url(table: str, path: str = "") -> str:
    base = settings.supabase_url.rstrip("/")
    suffix = f"/{path.lstrip('/')}" if path else ""
    return f"{base}/rest/v1/{table}{suffix}"


def _headers(prefer: str = "") -> dict[str, str]:
    h = {
        "apikey": settings.supabase_service_key,
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def _post(table: str, rows: list[dict], prefer: str = "return=minimal") -> bool:
    """POST a batch to PostgREST; returns True on 2xx, False otherwise.

    Never raises — network/auth failures are logged at WARNING.
    """
    if not rows:
        return True
    rows = [_coerce_timestamps(r) for r in rows]
    data = json.dumps(rows, default=_json_default).encode("utf-8")
    req = Request(_rest_url(table), data=data, headers=_headers(prefer), method="POST")
    try:
        with urlopen(req, timeout=_HTTP_TIMEOUT):
            return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("supabase POST %s failed (%d rows): %s", table, len(rows), exc)
        _append_failed_batch(table, rows)
        return False


def _patch(table: str, filter_query: dict, patch: dict) -> bool:
    """PATCH with PostgREST filters (e.g. {'run_id': 'eq.abc123'})."""
    if not is_enabled() or not patch:
        return False
    qs = urlencode(filter_query)
    patch = _coerce_timestamps(patch)
    data = json.dumps(patch, default=_json_default).encode("utf-8")
    req = Request(
        f"{_rest_url(table)}?{qs}",
        data=data,
        headers=_headers("return=minimal"),
        method="PATCH",
    )
    try:
        with urlopen(req, timeout=_HTTP_TIMEOUT):
            return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("supabase PATCH %s failed: %s", table, exc)
        return False


def _json_default(v):
    """Best-effort JSON coercion for Pandas/NumPy scalars that might sneak in."""
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "item"):
        return v.item()
    return str(v)


# Column names that Postgres stores as TIMESTAMPTZ. Callers often pass Unix
# floats (convenient for SQLite) which PostgREST rejects with HTTP 400. We
# coerce them at the client boundary so every writer stays simple.
_TIMESTAMP_COLUMNS = frozenset({"started_at", "finished_at", "updated_at", "created_at"})


def _coerce_timestamps(row: dict) -> dict:
    """Return a copy of `row` with known TIMESTAMPTZ columns as ISO 8601 strings."""
    out = dict(row)
    for col in _TIMESTAMP_COLUMNS:
        v = out.get(col)
        if v is None or isinstance(v, str):
            continue
        if isinstance(v, (int, float)):
            out[col] = datetime.fromtimestamp(float(v), tz=timezone.utc).isoformat()
        elif hasattr(v, "isoformat"):
            out[col] = v.isoformat()
    return out


# ── backtest_runs ─────────────────────────────────────────────────────────

def upsert_run(row: dict) -> bool:
    """Insert-or-update a single backtest_runs row (by run_id).

    Uses `Prefer: resolution=merge-duplicates` so dispatcher can call this at
    queued → running → complete transitions.
    """
    if not is_enabled():
        return False
    return _post("backtest_runs", [row], prefer="resolution=merge-duplicates,return=minimal")


# Columns patch_run is allowed to touch. Matches the allowlist enforced by
# `backend.cpcv_sqlite.patch_run` so both stores accept the same writes.
_PATCHABLE_RUN_COLS: frozenset[str] = frozenset({
    "config_hash", "git_sha", "status", "universe",
    "n_groups", "n_test_groups", "n_combinations",
    "n_completed", "n_skipped", "n_failed",
    "median_oos_sharpe", "oos_sharpe_min", "oos_sharpe_max",
    "pbo", "deflated_sharpe",
    "config_json", "metrics_json", "error", "modal_call_id",
    "started_at", "finished_at",
})


def patch_run(run_id: str, patch: dict) -> bool:
    """Targeted PATCH of specific columns on a backtest_runs row."""
    if not patch:
        return False
    unknown = set(patch.keys()) - _PATCHABLE_RUN_COLS
    if unknown:
        raise ValueError(
            f"patch_run: unknown columns {sorted(unknown)} "
            f"(allowed: {sorted(_PATCHABLE_RUN_COLS)})"
        )
    return _patch("backtest_runs", {"run_id": f"eq.{run_id}"}, patch)


# ── backtest_combinations ────────────────────────────────────────────────

def insert_combinations_batch(rows: list[dict], chunk: int = _COMBO_CHUNK) -> tuple[int, int]:
    """Batch-insert combo rows. Returns (inserted, failed)."""
    if not is_enabled() or not rows:
        return (0, 0)
    inserted = 0
    failed = 0
    for i in range(0, len(rows), chunk):
        batch = rows[i:i + chunk]
        if _post("backtest_combinations", batch, prefer="resolution=merge-duplicates,return=minimal"):
            inserted += len(batch)
        else:
            failed += len(batch)
    return (inserted, failed)


# ── backtest_trades ──────────────────────────────────────────────────────

def insert_trades_batch(rows: list[dict], chunk: int = _TRADE_CHUNK) -> tuple[int, int]:
    """Batch-insert trade rows. Returns (inserted, failed).

    Callers should pre-chunk at the combo level — a single combo is typically
    <200 trades, well under the 2000-row chunk cap.
    """
    if not is_enabled() or not rows:
        return (0, 0)
    inserted = 0
    failed = 0
    for i in range(0, len(rows), chunk):
        batch = rows[i:i + chunk]
        if _post("backtest_trades", batch, prefer="return=minimal"):
            inserted += len(batch)
        else:
            failed += len(batch)
    return (inserted, failed)


# ── backtest_events ──────────────────────────────────────────────────────

def insert_event(row: dict) -> bool:
    """Fire-and-forget event write. Used by `modal_app.events.emit_event`."""
    if not is_enabled():
        return False
    return _post("backtest_events", [row], prefer="return=minimal")


# ── read-path helpers (Session 2b) ──────────────────────────────────────
#
# Thin PostgREST GETs. Returns `None`/[] when Supabase is disabled so callers
# can transparently fall back to SQLite via `backend.backtest_reader`.

def _get(path: str, params: Optional[dict] = None) -> Optional[list[dict]]:
    if not is_enabled():
        return None
    url = _rest_url(path.split("?", 1)[0])
    query_bits: list[str] = []
    if "?" in path:
        query_bits.append(path.split("?", 1)[1])
    if params:
        query_bits.append(urlencode(params, safe=".,:()*"))
    if query_bits:
        url = f"{url}?{'&'.join(query_bits)}"
    req = Request(url, headers=_headers(), method="GET")
    try:
        with urlopen(req, timeout=_HTTP_TIMEOUT) as r:
            body = r.read()
            return json.loads(body) if body else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("supabase GET %s failed: %s", path, exc)
        return None


def list_runs(
    status: Optional[str] = None,
    config_hash: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Optional[list[dict]]:
    params = {
        "select": _RUNS_COLS,
        "order": "started_at.desc",
        "limit": limit,
        "offset": offset,
    }
    if status:
        params["status"] = f"eq.{status}"
    if config_hash:
        params["config_hash"] = f"eq.{config_hash}"
    return _get("backtest_runs", params)


def get_run(run_id: str) -> Optional[dict]:
    rows = _get("backtest_runs", {"run_id": f"eq.{run_id}", "select": _RUNS_COLS, "limit": 1})
    if rows is None:
        return None
    return rows[0] if rows else None


def find_runs_by_config_hash(config_hash: str, limit: int = 20) -> Optional[list[dict]]:
    return list_runs(config_hash=config_hash, limit=limit)


def get_combinations(
    run_id: str,
    order_by: str = "oos_sharpe",
    descending: bool = True,
    limit: Optional[int] = None,
    offset: int = 0,
) -> Optional[list[dict]]:
    allowed = {"oos_sharpe", "combo_idx", "return_pct", "n_trades"}
    col = order_by if order_by in allowed else "oos_sharpe"
    direction = "desc" if descending else "asc"
    params = {
        "run_id": f"eq.{run_id}",
        "select": _COMBO_COLS,
        "order": f"{col}.{direction}.nullslast",
    }
    if limit is not None:
        params["limit"] = limit
        params["offset"] = offset
    return _get("backtest_combinations", params)


def get_trades(
    run_id: str,
    combo_idx: Optional[int] = None,
    ticker: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> Optional[list[dict]]:
    params = {
        "run_id": f"eq.{run_id}",
        "select": _TRADE_COLS_LIST,
        "order": "combo_idx.asc,trade_idx.asc",
    }
    if combo_idx is not None:
        params["combo_idx"] = f"eq.{combo_idx}"
    if ticker:
        params["ticker"] = f"eq.{ticker}"
    if limit is not None:
        params["limit"] = limit
        params["offset"] = offset
    return _get("backtest_trades", params)


def get_trade_detail(
    run_id: str,
    combo_idx: int,
    trade_idx: int,
) -> Optional[dict]:
    """Single-trade fetch including signals_at_entry_json for drill-down UI."""
    rows = _get(
        "backtest_trades",
        {
            "run_id": f"eq.{run_id}",
            "combo_idx": f"eq.{combo_idx}",
            "trade_idx": f"eq.{trade_idx}",
            "select": _TRADE_COLS_DETAIL,
            "limit": 1,
        },
    )
    if rows is None:
        return None
    return rows[0] if rows else None


def sweep_stale_runs(max_age_seconds: Optional[float] = None) -> int:
    """Mark Supabase runs whose `updated_at` heartbeat is older than the cutoff failed.

    Mirrors `backend.cpcv_sqlite.sweep_stale_runs` so both stores converge.
    Returns a best-effort count (PostgREST doesn't give an exact rowcount
    unless we ask for it, and this is a periodic cleanup so approximate is fine).
    """
    if not is_enabled():
        return 0
    if max_age_seconds is None:
        max_age_seconds = float(getattr(settings, "cpcv_stale_sweep_seconds", 30 * 60))
    cutoff = datetime.fromtimestamp(time.time() - max_age_seconds, tz=timezone.utc).isoformat()
    # Two PostgREST filters: status=eq.running AND updated_at<cutoff
    qs = urlencode({
        "status": "eq.running",
        "updated_at": f"lt.{cutoff}",
    }, safe=".,:()*")
    data = json.dumps({
        "status": "failed",
        "error": "stale run: no terminal event within timeout",
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }).encode("utf-8")
    req = Request(
        f"{_rest_url('backtest_runs')}?{qs}",
        data=data,
        headers={**_headers("return=representation"), "Accept": "application/json"},
        method="PATCH",
    )
    try:
        with urlopen(req, timeout=_HTTP_TIMEOUT) as r:
            body = r.read()
            try:
                return len(json.loads(body)) if body else 0
            except Exception:
                return 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("supabase sweep_stale_runs failed: %s", exc)
        return 0


def get_events(
    run_id: str,
    after_id: Optional[int] = None,
    limit: int = 200,
) -> Optional[list[dict]]:
    params = {
        "run_id": f"eq.{run_id}",
        "select": _EVENT_COLS,
        "order": "id.asc",
        "limit": limit,
    }
    if after_id is not None:
        params["id"] = f"gt.{after_id}"
    return _get("backtest_events", params)


__all__ = [
    "is_enabled",
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
    "get_trade_detail",
    "get_events",
]
