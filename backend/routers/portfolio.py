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


# ── Candidate Pipeline ────────────────────────────────────────────────
#
# Lightweight ranker over a fixed liquid universe. Cached in SQLite so we
# don't recompute signals on every page poll. Plan calls for a daily-cadence
# feature; 1h TTL is conservative enough for a paralysis-breaker v1.

_CANDIDATE_CACHE_TTL_SECONDS = 60 * 60  # 1 hour


def _ensure_rankings_table():
    conn = sqlite3.connect(_db_path())
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quant_rankings (
            ticker TEXT PRIMARY KEY,
            ranked_at REAL NOT NULL,
            composite_score REAL NOT NULL,
            composite_direction TEXT NOT NULL,
            actionable INTEGER NOT NULL,
            top_signals_json TEXT NOT NULL,
            universe TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def _open_position_tickers() -> set[str]:
    """Tickers we already hold — exclude from candidates."""
    conn = sqlite3.connect(_db_path())
    try:
        rows = conn.execute("SELECT ticker FROM paper_positions").fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return {r[0].upper() for r in rows if r and r[0]}


def _serialize_signals(sv) -> list[dict]:
    """Pull the top-N |score| signals from a SignalVector for display."""
    items: list[tuple[str, float]] = []
    for attr in (
        "obv_trend",
        "rsi",
        "bollinger_pctb",
        "mean_reversion_z",
        "sma_trend",
        "atr_regime",
        "high_52w",
    ):
        sig = getattr(sv, attr, None)
        if sig is not None:
            items.append((attr, float(getattr(sig, "score", 0.0) or 0.0)))
    # Single-scalar earnings/momentum signals are surfaced when non-zero
    for attr in (
        "earnings_rank_score",
        "institutional_flow_score",
        "sentiment_score",
        "sector_momentum_score",
        "price_momentum_score",
        "kalshi_macro_score",
    ):
        score = float(getattr(sv, attr, 0.0) or 0.0)
        if abs(score) > 0.001:
            items.append((attr, score))
    items.sort(key=lambda x: abs(x[1]), reverse=True)
    return [{"name": name, "score": round(score, 3)} for name, score in items[:3]]


def _compute_rankings(universe_name: str = "liquid_20") -> tuple[list[dict], list[str]]:
    """Run the quant signal stack over a fixed universe. Returns (rows, errors)."""
    from quant.universe import LIQUID_10, LIQUID_20, LIQUID_50
    from quant.signals import compute_signal_vector_from_provider

    universes = {"liquid_10": LIQUID_10, "liquid_20": LIQUID_20, "liquid_50": LIQUID_50}
    tickers = universes.get(universe_name, LIQUID_20)

    rows: list[dict] = []
    errors: list[str] = []

    def _score_one(ticker: str) -> Optional[dict]:
        try:
            sv = compute_signal_vector_from_provider(ticker)
            if sv is None:
                return None
            return {
                "ticker": ticker,
                "composite_score": float(sv.composite_score),
                "composite_direction": str(sv.composite_direction or "HOLD"),
                "actionable": bool(sv.actionable),
                "top_signals_json": __import__("json").dumps(_serialize_signals(sv)),
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("ranking failed for %s: %s", ticker, exc)
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_score_one, t): t for t in tickers}
        for fut in as_completed(futs):
            t = futs[fut]
            try:
                r = fut.result()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{t}: {exc}")
                continue
            if r is None:
                errors.append(f"{t}: no signal data")
                continue
            rows.append(r)

    return rows, errors


def _persist_rankings(rows: list[dict], universe_name: str) -> float:
    _ensure_rankings_table()
    now = time.time()
    conn = sqlite3.connect(_db_path())
    # Wipe stale rows for this universe so deletions clean up
    conn.execute("DELETE FROM quant_rankings WHERE universe = ?", (universe_name,))
    for r in rows:
        conn.execute(
            "INSERT OR REPLACE INTO quant_rankings "
            "(ticker, ranked_at, composite_score, composite_direction, "
            "actionable, top_signals_json, universe) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                r["ticker"],
                now,
                r["composite_score"],
                r["composite_direction"],
                1 if r["actionable"] else 0,
                r["top_signals_json"],
                universe_name,
            ),
        )
    conn.commit()
    conn.close()
    return now


def _load_cached_rankings(universe_name: str) -> tuple[list[dict], Optional[float]]:
    _ensure_rankings_table()
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM quant_rankings WHERE universe = ? ORDER BY composite_score DESC",
        (universe_name,),
    ).fetchall()
    conn.close()
    if not rows:
        return [], None
    ranked_at = max(float(r["ranked_at"]) for r in rows)
    out = [
        {
            "ticker": r["ticker"],
            "composite_score": float(r["composite_score"]),
            "composite_direction": r["composite_direction"],
            "actionable": bool(r["actionable"]),
            "top_signals_json": r["top_signals_json"],
        }
        for r in rows
    ]
    return out, ranked_at


@router.get("/candidates")
async def get_candidates(limit: int = 20, universe: str = "liquid_20", refresh: bool = False):
    """
    Ranked quant candidates for tickers we don't already own.

    Caches rankings in SQLite with a 1-hour TTL. Pass ?refresh=true to force a
    recompute. Excludes any ticker currently in paper_positions.
    """
    import json as _json

    rows, ranked_at = _load_cached_rankings(universe)
    now = time.time()
    is_stale = ranked_at is None or (now - ranked_at) > _CANDIDATE_CACHE_TTL_SECONDS

    errors: list[str] = []
    if refresh or is_stale or not rows:
        try:
            fresh, errors = _compute_rankings(universe)
            if fresh:
                ranked_at = _persist_rankings(fresh, universe)
                rows = sorted(fresh, key=lambda r: r["composite_score"], reverse=True)
                # Re-attach in same dict shape as cached load
                rows = [
                    {
                        "ticker": r["ticker"],
                        "composite_score": r["composite_score"],
                        "composite_direction": r["composite_direction"],
                        "actionable": r["actionable"],
                        "top_signals_json": r["top_signals_json"],
                    }
                    for r in rows
                ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("candidate ranking failed: %s", exc)
            errors.append(f"ranker: {exc}")

    held = _open_position_tickers()
    cached_at_iso = ""
    if ranked_at:
        from datetime import datetime
        cached_at_iso = datetime.utcfromtimestamp(ranked_at).strftime("%Y-%m-%dT%H:%M:%SZ")

    candidates = []
    for r in rows:
        if r["ticker"].upper() in held:
            continue
        try:
            top_signals = _json.loads(r["top_signals_json"]) or []
        except Exception:
            top_signals = []
        candidates.append({
            "ticker": r["ticker"],
            "composite_score": round(float(r["composite_score"]), 4),
            "composite_direction": r["composite_direction"],
            "actionable": bool(r["actionable"]),
            "top_signals": top_signals,
            "cached_at": cached_at_iso,
        })
        if len(candidates) >= limit:
            break

    return {
        "candidates": candidates,
        "cached_at": cached_at_iso,
        "universe": universe,
        "errors": errors,
    }
