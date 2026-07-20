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
            exit_conditions TEXT DEFAULT '',
            direction TEXT DEFAULT 'LONG',
            conviction_score REAL
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
            exit_reason TEXT DEFAULT '',
            direction TEXT DEFAULT 'LONG'
        )
    """)
    # Migrate existing tables
    for table, cols in [
        ("paper_positions", [("direction", "TEXT DEFAULT 'LONG'"), ("conviction_score", "REAL")]),
        ("paper_trades", [("direction", "TEXT DEFAULT 'LONG'")]),
    ]:
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col_name, col_type in cols:
            if col_name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
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
        direction = r["direction"] if "direction" in r.keys() else "LONG"
        if current and entry:
            if direction == "SHORT":
                unrealized = round((entry - current) / entry * 100, 2)
            else:
                unrealized = round((current - entry) / entry * 100, 2)
        else:
            unrealized = None
        days_held = 0
        if r["entry_date"]:
            try:
                from datetime import datetime

                days_held = (datetime.now() - datetime.strptime(r["entry_date"], "%Y-%m-%d")).days
            except Exception:
                pass

        positions.append(
            {
                "ticker": r["ticker"],
                "entry_price": entry,
                "entry_date": r["entry_date"] or "",
                "current_price": current,
                "verdict": r["verdict"] or "",
                "exit_conditions": r["exit_conditions"] or "",
                "direction": direction,
                "conviction_score": r["conviction_score"]
                if "conviction_score" in r.keys()
                else None,
                "unrealized_pnl_pct": unrealized,
                "days_held": days_held,
            }
        )

    return {"positions": positions}


@router.post("/positions")
async def add_position(position: dict):
    _ensure_tables()
    ticker = position.get("ticker", "").upper().strip()
    if not ticker:
        return {"status": "error", "message": "Ticker required"}

    conn = sqlite3.connect(_db_path())
    conn.execute(
        "INSERT OR REPLACE INTO paper_positions "
        "(ticker, entry_price, entry_date, verdict, exit_conditions, direction, conviction_score) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            ticker,
            float(position.get("entry_price", 0)),
            position.get("entry_date", time.strftime("%Y-%m-%d")),
            position.get("verdict", ""),
            position.get("exit_conditions", ""),
            position.get("direction", "LONG"),
            position.get("conviction_score"),
        ),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "ticker": ticker, "direction": position.get("direction", "LONG")}


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
    direction = row["direction"] if "direction" in row.keys() else "LONG"
    if entry_price:
        if direction == "SHORT":
            pnl_pct = round((entry_price - exit_price) / entry_price * 100, 2)
        else:
            pnl_pct = round((exit_price - entry_price) / entry_price * 100, 2)
    else:
        pnl_pct = 0

    conn.execute(
        "INSERT INTO paper_trades (ticker, entry_price, entry_date, exit_price, exit_date, pnl_pct, exit_reason, direction) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ticker,
            entry_price,
            row["entry_date"],
            exit_price,
            time.strftime("%Y-%m-%d"),
            pnl_pct,
            exit_reason,
            direction,
        ),
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
        trades.append(
            {
                "id": r["id"],
                "ticker": r["ticker"],
                "entry_price": r["entry_price"],
                "entry_date": r["entry_date"] or "",
                "exit_price": r["exit_price"],
                "exit_date": r["exit_date"] or "",
                "pnl_pct": r["pnl_pct"],
                "exit_reason": r["exit_reason"] or "",
            }
        )
        equity *= 1 + (r["pnl_pct"] or 0) / 100
        curve.append({"date": r["exit_date"] or "", "equity": round(equity, 2)})

    return {"trades": trades, "equity_curve": curve}


@router.get("/positions-with-verdicts")
async def get_positions_with_verdicts():
    """
    Join open paper positions with the latest agent verdict from analysis_history.

    Used by the Portfolio Overview dashboard. In-process join over already-stored
    data — no new tables, no async streaming.
    """
    from datetime import datetime

    _ensure_tables()
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    pos_rows = conn.execute("SELECT * FROM paper_positions").fetchall()

    # Pull every analysis row once and pick the most recent per ticker.
    # Cheaper than N round-trips and fine for paper trading position counts.
    latest_by_ticker: dict[str, sqlite3.Row] = {}
    try:
        history_rows = conn.execute(
            "SELECT analysis_id, ticker, run_at, verdict, conviction, "
            "composite_score, price_target "
            "FROM analysis_history ORDER BY run_at DESC"
        ).fetchall()
        for r in history_rows:
            t = r["ticker"]
            if t not in latest_by_ticker:
                latest_by_ticker[t] = r
    except sqlite3.OperationalError:
        pass
    conn.close()

    now_ts = time.time()
    positions = []
    total_unrealized_pnl_pct_weighted = 0.0
    total_equity = 0.0

    for r in pos_rows:
        ticker = r["ticker"]
        entry = r["entry_price"]
        direction = r["direction"] if "direction" in r.keys() else "LONG"
        current = _fetch_current_price(ticker)

        if current and entry:
            if direction == "SHORT":
                unrealized = round((entry - current) / entry * 100, 2)
            else:
                unrealized = round((current - entry) / entry * 100, 2)
        else:
            unrealized = None

        days_held = 0
        if r["entry_date"]:
            try:
                days_held = (datetime.now() - datetime.strptime(r["entry_date"], "%Y-%m-%d")).days
            except Exception:
                pass

        # Latest verdict join
        latest_verdict = None
        hist = latest_by_ticker.get(ticker)
        if hist is not None:
            run_at = float(hist["run_at"] or 0)
            days_stale: Optional[int] = None
            as_of_iso = ""
            if run_at > 0:
                try:
                    days_stale = max(0, int((now_ts - run_at) // 86400))
                    as_of_iso = datetime.utcfromtimestamp(run_at).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    days_stale = None
            target = hist["price_target"] if "price_target" in hist.keys() else None
            implied_upside_pct: Optional[float] = None
            if target and current and current > 0:
                try:
                    implied_upside_pct = round(
                        (float(target) - float(current)) / float(current) * 100, 2
                    )
                except Exception:
                    implied_upside_pct = None
            latest_verdict = {
                "analysis_id": hist["analysis_id"] or "",
                "verdict": hist["verdict"] or "",
                "conviction": hist["conviction"] or "",
                "composite_score": hist["composite_score"],
                "price_target": target,
                "implied_upside_pct": implied_upside_pct,
                "as_of": as_of_iso,
                "run_at": run_at,
                "days_stale": days_stale,
            }

        # Naive "weight by entry value" totals — Alpaca account is the truth,
        # but we surface a quick summary even when Alpaca is offline.
        if entry:
            total_equity += float(entry)
            if unrealized is not None:
                total_unrealized_pnl_pct_weighted += float(entry) * unrealized

        positions.append(
            {
                "ticker": ticker,
                "entry_price": entry,
                "entry_date": r["entry_date"] or "",
                "current_price": current,
                "entry_verdict": r["verdict"] or "",
                "exit_conditions": r["exit_conditions"] or "",
                "direction": direction,
                "conviction_score": r["conviction_score"]
                if "conviction_score" in r.keys()
                else None,
                "unrealized_pnl_pct": unrealized,
                "days_held": days_held,
                "latest_verdict": latest_verdict,
            }
        )

    avg_unrealized_pnl_pct: Optional[float] = None
    if total_equity > 0:
        avg_unrealized_pnl_pct = round(total_unrealized_pnl_pct_weighted / total_equity, 2)

    stale_count = sum(
        1
        for p in positions
        if p["latest_verdict"] is None
        or (
            p["latest_verdict"].get("days_stale") is not None
            and p["latest_verdict"]["days_stale"] > 7
        )
    )

    return {
        "positions": positions,
        "totals": {
            "total_positions": len(positions),
            "total_equity_at_entry": round(total_equity, 2),
            "avg_unrealized_pnl_pct": avg_unrealized_pnl_pct,
            "stale_count": stale_count,
        },
    }


@router.get("/metrics")
async def get_metrics():
    _ensure_tables()
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT pnl_pct FROM paper_trades").fetchall()
    conn.close()

    if not rows:
        return {
            "sharpe": None,
            "sortino": None,
            "win_rate_pct": None,
            "total_pnl_pct": None,
            "total_trades": 0,
        }

    returns = [r["pnl_pct"] / 100 for r in rows]
    wins = sum(1 for r in returns if r > 0)
    total_pnl = 1.0
    for r in returns:
        total_pnl *= 1 + r
    total_pnl_pct = round((total_pnl - 1) * 100, 2)

    import pandas as pd
    from quant.metrics import compute_sharpe, compute_sortino

    returns_series = pd.Series(returns)
    sharpe = compute_sharpe(returns_series, min_observations=2)
    sortino = compute_sortino(returns_series, min_observations=2)

    return {
        "sharpe": sharpe,
        "sortino": sortino,
        "win_rate_pct": round(wins / len(returns) * 100, 1),
        "total_pnl_pct": total_pnl_pct,
        "total_trades": len(returns),
    }


# ── Alpaca integration endpoints ──────────────────────────────────

from backend.alpaca_paper_client import get_alpaca_client  # noqa: E402

try:
    from backend.paper_scheduler import run_rebalance  # noqa: E402
except ImportError:
    run_rebalance = None  # type: ignore[assignment]


@router.get("/account")
async def get_alpaca_account():
    """Return Alpaca paper account info (balance, buying power)."""
    try:
        client = get_alpaca_client()
        return client.get_account()
    except EnvironmentError:
        return {"error": "Alpaca not configured"}
    except Exception as exc:
        logger.warning("Failed to get Alpaca account: %s", exc)
        return {"error": str(exc)}


@router.get("/orders")
async def get_alpaca_orders():
    """Return recent Alpaca order history."""
    try:
        client = get_alpaca_client()
        orders = client.get_orders()
        return {"orders": orders}
    except EnvironmentError:
        return {"orders": [], "error": "Alpaca not configured"}
    except Exception as exc:
        logger.warning("Failed to get Alpaca orders: %s", exc)
        return {"orders": [], "error": str(exc)}


@router.post("/rebalance")
async def trigger_rebalance(body: dict = None):
    """Trigger a manual rebalance. Optionally pass {"tickers": ["AAPL", "MSFT"]}."""
    try:
        tickers = (body or {}).get("tickers")
        result = run_rebalance(target_tickers=tickers)
        return result
    except Exception as exc:
        logger.error("Rebalance failed: %s", exc, exc_info=True)
        return {"status": "error", "error": str(exc)}
