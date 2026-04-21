"""Structured event stream for CPCV runs.

Dual-writes to SQLite (always, cheap) and Supabase (best-effort, graceful
no-op when disabled). Events are the live-progress feed: one row per
`emit_event` call, fire-and-forget, no batching.

Only the orchestrator emits events. Workers do not — they return result
dicts and the orchestrator converts each yield into the appropriate event.
This keeps Supabase credentials off worker containers and gives us a
single source of truth for run status (per architect review §5).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)


# Event kinds emitted by the orchestrator. UI relies on these exact strings.
EVENT_RUN_STARTED = "run_started"
EVENT_RUN_COMPLETED = "run_completed"
EVENT_RUN_DEGRADED = "run_degraded"
EVENT_RUN_FAILED = "run_failed"
EVENT_COMBO_COMPLETED = "combo_completed"
EVENT_COMBO_SKIPPED = "combo_skipped"
EVENT_COMBO_FAILED = "combo_failed"


class BacktestEvent(BaseModel):
    """Structured event emitted during a CPCV run."""

    run_id: str
    kind: str
    combo_idx: Optional[int] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)

    def to_sqlite_row(self) -> dict:
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "combo_idx": self.combo_idx,
            "payload": self.payload,
            "created_at": self.created_at,
        }

    def to_supabase_row(self) -> dict:
        """Supabase schema uses TIMESTAMPTZ — let Postgres default it unless
        we have a specific timestamp to set."""
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "combo_idx": self.combo_idx,
            "payload": self.payload,
        }


def emit_event(
    run_id: str,
    kind: str,
    payload: Optional[dict[str, Any]] = None,
    combo_idx: Optional[int] = None,
) -> BacktestEvent:
    """Dual-write a single event. Never raises.

    SQLite write is attempted first (local, WAL-mode — effectively always
    succeeds). Supabase write follows; failures are swallowed and logged
    at WARNING.
    """
    event = BacktestEvent(
        run_id=run_id,
        kind=kind,
        combo_idx=combo_idx,
        payload=dict(payload) if payload else {},
    )

    try:
        from backend import cpcv_sqlite
        cpcv_sqlite.insert_event(event.to_sqlite_row())
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQLite event write failed: %s", exc)

    try:
        from backend import supabase_backtest
        if supabase_backtest.is_enabled():
            supabase_backtest.insert_event(event.to_supabase_row())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Supabase event write failed: %s", exc)

    return event


__all__ = [
    "BacktestEvent",
    "emit_event",
    "EVENT_RUN_STARTED",
    "EVENT_RUN_COMPLETED",
    "EVENT_RUN_DEGRADED",
    "EVENT_RUN_FAILED",
    "EVENT_COMBO_COMPLETED",
    "EVENT_COMBO_SKIPPED",
    "EVENT_COMBO_FAILED",
]
