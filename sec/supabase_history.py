from __future__ import annotations

import json
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import settings


def is_enabled() -> bool:
    return (
        settings.enable_supabase_history
        and bool(settings.supabase_url.strip())
        and bool(settings.supabase_service_key.strip())
    )


def _endpoint(path: str = "") -> str:
    base = settings.supabase_url.rstrip("/")
    table = settings.supabase_history_table.strip() or "analyses"
    suffix = f"/{path.lstrip('/')}" if path else ""
    return f"{base}/rest/v1/{table}{suffix}"


def _headers(prefer: str = "") -> dict[str, str]:
    headers = {
        "apikey": settings.supabase_service_key,
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def upsert_record(record: dict) -> bool:
    if not is_enabled():
        return False
    req = Request(
        _endpoint(),
        data=json.dumps(record).encode("utf-8"),
        headers=_headers(prefer="resolution=merge-duplicates,return=minimal"),
        method="POST",
    )
    try:
        with urlopen(req, timeout=6):
            return True
    except Exception:
        return False


def fetch_history(ticker: str = "", limit: int = 20, offset: int = 0) -> Optional[list[dict]]:
    if not is_enabled():
        return None
    params = {
        "select": "*",
        "order": "run_at.desc",
        "limit": str(limit),
        "offset": str(offset),
    }
    if ticker:
        params["ticker"] = f"eq.{ticker.upper()}"
    req = Request(
        f"{_endpoint()}?{urlencode(params)}",
        headers=_headers(),
        method="GET",
    )
    try:
        with urlopen(req, timeout=6) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return payload if isinstance(payload, list) else None
    except Exception:
        return None


def fetch_detail(analysis_id: str) -> Optional[dict]:
    if not is_enabled():
        return None
    params = {"select": "*", "analysis_id": f"eq.{analysis_id}", "limit": "1"}
    req = Request(
        f"{_endpoint()}?{urlencode(params)}",
        headers=_headers(),
        method="GET",
    )
    try:
        with urlopen(req, timeout=6) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            if isinstance(payload, list) and payload:
                return payload[0]
    except Exception:
        return None
    return None
