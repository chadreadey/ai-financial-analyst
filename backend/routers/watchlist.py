from __future__ import annotations

import logging
import os
import sqlite3
import time

from fastapi import APIRouter

from backend.schemas import WatchlistEntry, WatchlistSummary
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _db_path() -> str:
    return settings.warehouse_db_path


def _ensure_table():
    conn = sqlite3.connect(_db_path())
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist_entries (
            ticker TEXT PRIMARY KEY,
            added_at TEXT DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()


@router.get("/")
async def list_watchlist():
    _ensure_table()
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM watchlist_entries ORDER BY ticker").fetchall()

    history_rows = []
    try:
        history_rows = conn.execute(
            "SELECT ticker, verdict, conviction, composite_score, run_at "
            "FROM analysis_history ORDER BY run_at DESC"
        ).fetchall()
    except sqlite3.OperationalError:
        pass
    conn.close()

    latest = {}
    for r in history_rows:
        t = r["ticker"]
        if t not in latest:
            latest[t] = r

    entries = []
    for r in rows:
        t = r["ticker"]
        hist = latest.get(t)
        entries.append(
            WatchlistEntry(
                ticker=t,
                added_at=r["added_at"] or "",
                latest_verdict=hist["verdict"] if hist else None,
                latest_conviction=hist["conviction"] if hist else None,
                latest_score=hist["composite_score"] if hist else None,
            )
        )
    return {"entries": entries}


@router.post("/{ticker}")
async def add_to_watchlist(ticker: str):
    _ensure_table()
    conn = sqlite3.connect(_db_path())
    conn.execute(
        "INSERT OR IGNORE INTO watchlist_entries (ticker, added_at) VALUES (?, ?)",
        (ticker.upper(), time.strftime("%Y-%m-%d")),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "ticker": ticker.upper()}


@router.delete("/{ticker}")
async def remove_from_watchlist(ticker: str):
    _ensure_table()
    conn = sqlite3.connect(_db_path())
    conn.execute("DELETE FROM watchlist_entries WHERE ticker = ?", (ticker.upper(),))
    conn.commit()
    conn.close()
    return {"status": "ok", "ticker": ticker.upper()}


def _compute_outcome(
    verdict: str, entry_price: float | None, current_price: float | None
) -> str | None:
    if entry_price is None or current_price is None or entry_price <= 0:
        return None
    v = (verdict or "").upper()
    bullish = any(x in v for x in ("BUY",))
    bearish = any(x in v for x in ("SELL",))
    if not bullish and not bearish:
        return None
    price_up = current_price > entry_price
    if (bullish and price_up) or (bearish and not price_up):
        return "hit"
    return "miss"


@router.get("/{ticker}/summary")
async def get_watchlist_summary(ticker: str):
    ticker = ticker.upper()
    current_price = None
    tiingo_key = os.getenv("TIINGO_API_KEY", "").strip()
    if tiingo_key:
        try:
            from tiingo_client import TiingoClient

            client = TiingoClient(tiingo_key)
            data = client.get_quote(ticker)
            if data:
                current_price = float(data.get("last") or data.get("close") or 0) or None
        except Exception:
            pass

    # Compute hit rate from analysis_history outcomes
    hit_rate_pct: float | None = None
    try:
        conn = sqlite3.connect(settings.warehouse_db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT verdict, entry_price_at_run FROM analysis_history WHERE ticker = ? ORDER BY run_at DESC LIMIT 20",
            (ticker,),
        ).fetchall()
        conn.close()
        outcomes = [
            _compute_outcome(r["verdict"], r["entry_price_at_run"], current_price) for r in rows
        ]
        scored = [o for o in outcomes if o is not None]
        if scored:
            hits = sum(1 for o in scored if o == "hit")
            hit_rate_pct = round(hits / len(scored) * 100, 1)
    except Exception:
        pass

    period_statuses = {
        "3mo": "pending",
        "1yr": "pending",
        "3yr": "pending",
        "5yr": "pending",
        "current": "pending",
    }

    return WatchlistSummary(
        ticker=ticker,
        current_price=current_price,
        hit_rate_pct=hit_rate_pct,
        period_statuses=period_statuses,
    )
