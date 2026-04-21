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
    data = json.dumps(rows, default=_json_default).encode("utf-8")
    req = Request(_rest_url(table), data=data, headers=_headers(prefer), method="POST")
    try:
        with urlopen(req, timeout=_HTTP_TIMEOUT):
            return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("supabase POST %s failed (%d rows): %s", table, len(rows), exc)
        return False


def _patch(table: str, filter_query: dict, patch: dict) -> bool:
    """PATCH with PostgREST filters (e.g. {'run_id': 'eq.abc123'})."""
    if not is_enabled() or not patch:
        return False
    qs = urlencode(filter_query)
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


# ── backtest_runs ─────────────────────────────────────────────────────────

def upsert_run(row: dict) -> bool:
    """Insert-or-update a single backtest_runs row (by run_id).

    Uses `Prefer: resolution=merge-duplicates` so dispatcher can call this at
    queued → running → complete transitions.
    """
    if not is_enabled():
        return False
    return _post("backtest_runs", [row], prefer="resolution=merge-duplicates,return=minimal")


def patch_run(run_id: str, patch: dict) -> bool:
    """Targeted PATCH of specific columns on a backtest_runs row."""
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


__all__ = [
    "is_enabled",
    "upsert_run",
    "patch_run",
    "insert_combinations_batch",
    "insert_trades_batch",
    "insert_event",
]
