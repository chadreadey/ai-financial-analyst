from __future__ import annotations

import logging
import math
import os
import sqlite3
import statistics
import time
from typing import Optional

from fastapi import APIRouter

from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _db_path() -> str:
    return settings.warehouse_db_path


def _ensure_tables():
    conn = sqlite3.connect(_db_path())
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_positions (
            ticker TEXT PRIMARY KEY,
            entry_price REAL,
            entry_date TEXT,
            current_price REAL,
            verdict TEXT DEFAULT '',
            exit_conditions TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            entry_price REAL,
            entry_date TEXT,
            exit_price REAL,
            exit_date TEXT,
            pnl_pct REAL,
            exit_reason TEXT DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()


def _fetch_current_price(ticker: str) -> Optional[float]:
    tiingo_key = os.getenv("TIINGO_API_KEY", "").strip()
    if tiingo_key:
        try:
            from tiingo_client import TiingoClient
            client = TiingoClient(tiingo_key)
            data = client.get_quote(ticker)
            if data and isinstance(data, list) and data:
                return float(data[0].get("last") or data[0].get("close") or 0) or None
            elif data and isinstance(data, dict):
                return float(data.get("last") or data.get("close") or 0) or None
        except Exception:
            pass
    return None


@router.get("/positions")
async def get_positions():
    _ensure_tables()
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM paper_positions").fetchall()
    conn.close()

    positions = []
    for r in rows:
        current = _fetch_current_price(r["ticker"])
        entry = r["entry_price"]
        unrealized = round((current - entry) / entry * 100, 2) if current and entry else None
        days_held = 0
        if r["entry_date"]:
            try:
                from datetime import datetime
                days_held = (datetime.now() - datetime.strptime(r["entry_date"], "%Y-%m-%d")).days
            except Exception:
                pass

        positions.append({
            "ticker": r["ticker"],
            "entry_price": entry,
            "entry_date": r["entry_date"] or "",
            "current_price": current,
            "verdict": r["verdict"] or "",
            "exit_conditions": r["exit_conditions"] or "",
            "unrealized_pnl_pct": unrealized,
            "days_held": days_held,
        })

    return {"positions": positions}


@router.post("/positions")
async def add_position(position: dict):
    _ensure_tables()
    ticker = position.get("ticker", "").upper().strip()
    if not ticker:
        return {"status": "error", "message": "Ticker required"}

    conn = sqlite3.connect(_db_path())
    conn.execute(
        "INSERT OR REPLACE INTO paper_positions (ticker, entry_price, entry_date, verdict, exit_conditions) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            ticker,
            float(position.get("entry_price", 0)),
            position.get("entry_date", time.strftime("%Y-%m-%d")),
            position.get("verdict", ""),
            position.get("exit_conditions", ""),
        ),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "ticker": ticker}


@router.put("/positions/{ticker}/close")
async def close_position(ticker: str, body: dict):
    ticker = ticker.upper()
    _ensure_tables()
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM paper_positions WHERE ticker = ?", (ticker,)).fetchone()
    if not row:
        conn.close()
        return {"status": "error", "message": "Position not found"}

    exit_price = float(body.get("exit_price", 0))
    exit_reason = body.get("exit_reason", "manual_close")
    entry_price = row["entry_price"]
    pnl_pct = round((exit_price - entry_price) / entry_price * 100, 2) if entry_price else 0

    conn.execute(
        "INSERT INTO paper_trades (ticker, entry_price, entry_date, exit_price, exit_date, pnl_pct, exit_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ticker, entry_price, row["entry_date"], exit_price, time.strftime("%Y-%m-%d"), pnl_pct, exit_reason),
    )
    conn.execute("DELETE FROM paper_positions WHERE ticker = ?", (ticker,))
    conn.commit()
    conn.close()
    return {"status": "ok", "pnl_pct": pnl_pct}


@router.get("/history")
async def get_trade_history():
    _ensure_tables()
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM paper_trades ORDER BY exit_date DESC").fetchall()
    conn.close()

    trades = []
    equity = 10000.0
    curve = []
    for r in rows:
        trades.append({
            "id": r["id"],
            "ticker": r["ticker"],
            "entry_price": r["entry_price"],
            "entry_date": r["entry_date"] or "",
            "exit_price": r["exit_price"],
            "exit_date": r["exit_date"] or "",
            "pnl_pct": r["pnl_pct"],
            "exit_reason": r["exit_reason"] or "",
        })
        equity *= (1 + (r["pnl_pct"] or 0) / 100)
        curve.append({"date": r["exit_date"] or "", "equity": round(equity, 2)})

    return {"trades": trades, "equity_curve": curve}


@router.get("/metrics")
async def get_metrics():
    _ensure_tables()
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT pnl_pct FROM paper_trades").fetchall()
    conn.close()

    if not rows:
        return {"sharpe": None, "sortino": None, "win_rate_pct": None, "total_pnl_pct": None, "total_trades": 0}

    returns = [r["pnl_pct"] / 100 for r in rows]
    wins = sum(1 for r in returns if r > 0)
    total_pnl = 1.0
    for r in returns:
        total_pnl *= (1 + r)
    total_pnl_pct = round((total_pnl - 1) * 100, 2)

    sharpe = None
    sortino = None
    if len(returns) > 1:
        mean_r = statistics.mean(returns)
        std_r = statistics.stdev(returns)
        if std_r > 0:
            sharpe = round(mean_r / std_r * math.sqrt(len(returns)), 2)
        downside = [r for r in returns if r < 0]
        if len(downside) > 1:
            down_std = statistics.stdev(downside)
            if down_std > 0:
                sortino = round(mean_r / down_std * math.sqrt(len(returns)), 2)

    return {
        "sharpe": sharpe,
        "sortino": sortino,
        "win_rate_pct": round(wins / len(returns) * 100, 1),
        "total_pnl_pct": total_pnl_pct,
        "total_trades": len(returns),
    }
