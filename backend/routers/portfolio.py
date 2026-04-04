from __future__ import annotations

import logging
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from fastapi import APIRouter, HTTPException

from backend.schemas import PortfolioHolding, PortfolioSummary
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _db_path() -> str:
    return settings.warehouse_db_path


def _ensure_table():
    conn = sqlite3.connect(_db_path())
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_holdings (
            ticker TEXT PRIMARY KEY,
            shares REAL NOT NULL,
            cost_basis REAL NOT NULL,
            date_added TEXT DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()


def _fetch_live_price(ticker: str) -> Optional[float]:
    tiingo_key = os.getenv("TIINGO_API_KEY", "").strip()
    if tiingo_key:
        try:
            from tiingo_client import TiingoClient
            client = TiingoClient(tiingo_key)
            data = client.get_quote(ticker)
            if data:
                return float(data[0].get("last") or data[0].get("close") or 0)
        except Exception:
            pass

    fmp_key = os.getenv("FMP_API_KEY", "").strip()
    if fmp_key:
        try:
            from fmp_client import FMPClient
            client = FMPClient(fmp_key)
            data = client.get_quote(ticker)
            if data:
                return float(data[0].get("price", 0))
        except Exception:
            pass

    return None


@router.get("/", response_model=PortfolioSummary)
async def get_portfolio():
    _ensure_table()
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM portfolio_holdings ORDER BY ticker").fetchall()
    conn.close()
    holdings = [
        PortfolioHolding(
            ticker=r["ticker"],
            shares=r["shares"],
            cost_basis=r["cost_basis"],
            date_added=r["date_added"] or "",
        )
        for r in rows
    ]

    prices: dict[str, Optional[float]] = {}
    if holdings:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futs = {pool.submit(_fetch_live_price, h.ticker): h.ticker for h in holdings}
            for fut in as_completed(futs):
                prices[futs[fut]] = fut.result()

    total_cost = sum(h.shares * h.cost_basis for h in holdings)
    total_value = 0.0
    allocations: dict[str, float] = {}
    for h in holdings:
        price = prices.get(h.ticker)
        if price and price > 0:
            val = h.shares * price
        else:
            val = h.shares * h.cost_basis
        total_value += val
        allocations[h.ticker] = val

    if total_value > 0:
        allocations = {k: round(v / total_value * 100, 1) for k, v in allocations.items()}

    day_change_pct = 0.0
    if total_cost > 0:
        day_change_pct = round((total_value / total_cost - 1) * 100, 2)

    return PortfolioSummary(
        holdings=holdings,
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        day_change_pct=day_change_pct,
        allocations=allocations,
    )


@router.post("/holdings")
async def upsert_holding(holding: PortfolioHolding):
    _ensure_table()
    conn = sqlite3.connect(_db_path())
    conn.execute(
        """INSERT INTO portfolio_holdings (ticker, shares, cost_basis, date_added)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(ticker) DO UPDATE SET shares=excluded.shares, cost_basis=excluded.cost_basis""",
        (holding.ticker.upper(), holding.shares, holding.cost_basis, holding.date_added or time.strftime("%Y-%m-%d")),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "ticker": holding.ticker.upper()}


@router.delete("/holdings/{ticker}")
async def delete_holding(ticker: str):
    _ensure_table()
    conn = sqlite3.connect(_db_path())
    conn.execute("DELETE FROM portfolio_holdings WHERE ticker = ?", (ticker.upper(),))
    conn.commit()
    conn.close()
    return {"status": "ok", "ticker": ticker.upper()}
