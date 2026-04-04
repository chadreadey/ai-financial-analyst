from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def _horizon_days(time_horizon: str) -> int:
    h = (time_horizon or "").strip().lower()
    if h == "short-term":
        return 365
    if h == "long-term":
        return 365 * 5
    return 365


def _fetch_current_price(ticker: str) -> Optional[float]:
    if not ticker:
        return None
    try:
        from tiingo_client import TiingoClient
        from config import settings

        if not settings.tiingo_api_key:
            return None
        client = TiingoClient(settings.tiingo_api_key)
        data = client.get_quote(ticker.upper())
        if isinstance(data, dict):
            value = data.get("last") or data.get("close")
            return float(value) if value is not None else None
        if isinstance(data, list) and data:
            value = data[0].get("last") or data[0].get("close")
            return float(value) if value is not None else None
    except Exception:
        return None
    return None


def compute_outcome_metrics(entry: dict) -> dict:
    run_at = float(entry.get("run_at") or 0)
    ticker = entry.get("ticker") or ""
    entry_price = entry.get("entry_price_at_run")
    price_target = entry.get("price_target")
    stop_loss_value = entry.get("stop_loss_value")
    stop_loss_unit = (entry.get("stop_loss_unit") or "").lower()
    time_horizon = entry.get("time_horizon") or ""

    current_price = _fetch_current_price(ticker)
    return_pct = None
    if current_price is not None and entry_price not in (None, 0):
        try:
            return_pct = ((current_price - float(entry_price)) / float(entry_price)) * 100.0
        except Exception:
            return_pct = None

    days_remaining = None
    status = "unknown"
    if run_at > 0:
        run_dt = datetime.fromtimestamp(run_at, tz=timezone.utc)
        end_dt = run_dt.timestamp() + (_horizon_days(time_horizon) * 86400)
        now_ts = datetime.now(timezone.utc).timestamp()
        days_remaining = int((end_dt - now_ts) // 86400)
        status = "horizon_elapsed" if days_remaining < 0 else "open"

    if current_price is not None:
        if price_target is not None and current_price >= float(price_target):
            status = "target_hit"
        elif stop_loss_value is not None:
            if stop_loss_unit == "percent" and entry_price not in (None, 0):
                floor = float(entry_price) * (1.0 - (float(stop_loss_value) / 100.0))
                if current_price <= floor:
                    status = "stop_hit"
            elif stop_loss_unit == "price" and current_price <= float(stop_loss_value):
                status = "stop_hit"

    return {
        "current_price": current_price,
        "return_since_analysis_pct": round(return_pct, 2) if return_pct is not None else None,
        "outcome_status": status,
        "days_remaining": days_remaining,
    }
