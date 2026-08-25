"""
Diagnostics API — read the stochastic assumption log over HTTP.

Exposes the assumption logger's records so the dashboard (or an operator) can
see, in-app, which statistical assumptions were checked and which were
violated. Read-only.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter()

_SEV_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _log_path() -> Optional[str]:
    env = os.getenv("ASSUMPTION_AUDIT_JSONL")
    if env:
        return env
    try:
        from config import settings

        return getattr(settings, "assumption_audit_log_path", None)
    except Exception:
        return None


def _load(path: str, limit: int) -> list[dict]:
    recs: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return recs[-limit:] if limit and limit > 0 else recs


@router.get("/assumptions")
async def get_assumptions(
    status: Optional[str] = Query(None, description="pass | violated | skipped | error"),
    severity: Optional[str] = Query(None, description="low | medium | high | critical (or higher)"),
    limit: int = Query(500, ge=1, le=10000),
):
    """Return recent assumption-log records plus a summary.

    Reads the in-process default log first (live records from the running API),
    and falls back to the JSONL file on disk when the in-memory log is empty.
    """
    records: list[dict] = []
    source = "memory"

    try:
        from quant.assumption_audit import get_audit_log

        log = get_audit_log()
        records = [r.to_dict() for r in log.records]
    except Exception:
        records = []

    if not records:
        path = _log_path()
        if path and os.path.exists(path):
            source = path
            try:
                records = _load(path, limit)
            except Exception:
                records = []

    def keep(r: dict) -> bool:
        st = r.get("status", "")
        if status:
            if status == "skipped":
                if not st.startswith("skipped"):
                    return False
            elif st != status:
                return False
        if severity and _SEV_RANK.get(r.get("severity", "low"), 0) < _SEV_RANK.get(severity, 0):
            return False
        return True

    filtered = [r for r in records if keep(r)][-limit:]

    summary = {"pass": 0, "violated": 0, "skipped": 0, "error": 0}
    for r in filtered:
        st = r.get("status", "")
        if st.startswith("skipped"):
            summary["skipped"] += 1
        elif st in summary:
            summary[st] += 1

    return {
        "source": source,
        "total_records": len(records),
        "shown": len(filtered),
        "summary": summary,
        "records": filtered,
    }
