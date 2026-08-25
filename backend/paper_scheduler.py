"""
Monthly paper trading rebalance scheduler.

Safety model (see docs/audit/2026-07-04-core-platform-audit):
  * FAIL-CLOSED universe: a watchlist read error or an empty universe
    aborts the rebalance WITHOUT closing anything. An empty target set is
    never interpreted as "sell everything" (audit F-002).
  * SINGLE order submitter: analysis runs with auto_paper_trade disabled so
    the orchestrator does not also place orders — this module is the only
    submitter, preventing double-sized positions (audit F-001).
  * VERDICT-FLIP exits: held names whose fresh verdict turns bearish are
    closed, not silently kept (audit F-006).
  * BOUNDED work: each per-ticker analysis has a wall-clock timeout so one
    hung upstream cannot freeze the whole rebalance (audit F-020).
  * NON-REENTRANT: a module lock prevents scheduled and manual rebalances
    from overlapping and interleaving order/close state (audit F-005).
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from typing import Any, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings
from backend.alpaca_paper_client import get_alpaca_client
from backend.jobs import create_job, run_analysis_job
from backend.schemas import RunAnalysisRequest

logger = logging.getLogger(__name__)

# Prevents scheduled cron and manual API rebalances from running at the same
# time (audit F-005). Non-blocking: a second invocation is skipped, not queued.
_rebalance_lock = threading.Lock()


class WatchlistUnavailable(Exception):
    """Raised when the watchlist cannot be read. Triggers a fail-closed abort."""


def _get_watchlist_tickers() -> list[str]:
    """Return watchlist tickers from the ``watchlist_entries`` table.

    Reads the SAME table the watchlist API writes to (``watchlist_entries``);
    the previous ``watchlist`` name never existed, so every scheduled run read
    empty and closed the entire book (audit F-002).

    Raises ``WatchlistUnavailable`` on any read error so the caller can
    fail closed instead of treating an error as an empty universe.
    """
    try:
        conn = sqlite3.connect(settings.warehouse_db_path)
        try:
            # Match the API's lazy table creation so a fresh deploy yields a
            # clean empty list (→ fail-closed abort) rather than an error.
            conn.execute(
                "CREATE TABLE IF NOT EXISTS watchlist_entries "
                "(ticker TEXT PRIMARY KEY, added_at TEXT DEFAULT '')"
            )
            rows = conn.execute("SELECT ticker FROM watchlist_entries").fetchall()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — re-raised as a typed abort signal
        raise WatchlistUnavailable(str(exc)) from exc
    return [r[0] for r in rows if r[0]]


def _verdict_side(verdict: str) -> Optional[str]:
    """Classify a verdict string into 'buy' / 'sell' / None.

    Guards against the ``"BUY" in "DO NOT BUY"`` substring trap (audit F-007).
    The deterministic override upstream emits a clean enum, so those are matched
    exactly first; the fallback for any non-enum text refuses to trade on
    negated/ambiguous phrases rather than mis-reading them as a buy.
    """
    v = (verdict or "").strip().upper()
    if v in ("STRONG BUY", "BUY"):
        return "buy"
    if v in ("STRONG SELL", "SELL"):
        return "sell"
    # Defensive fallback for unexpected free text.
    if any(neg in v for neg in ("NOT", "AVOID", "DON'T", "DONT", "NO ")):
        return None
    has_buy = "BUY" in v
    has_sell = "SELL" in v
    if has_buy and not has_sell:
        return "buy"
    if has_sell and not has_buy:
        return "sell"
    return None


def _analyze_bounded(ticker: str, timeout: float) -> tuple[Optional[dict], Optional[str]]:
    """Run analysis for one ticker with a wall-clock timeout (audit F-020).

    Analysis runs with ``auto_paper_trade=False`` so the orchestrator never
    submits an order — this module is the sole submitter (audit F-001).

    Returns ``(structured_verdict, None)`` on success or ``(None, error)`` on
    timeout/failure. On timeout the analysis thread is abandoned (daemon), the
    rebalance moves on, and no order is placed for this ticker.
    """
    job = create_job(ticker)
    request = RunAnalysisRequest(ticker=ticker)
    holder: dict[str, Any] = {}

    def _target() -> None:
        try:
            run_analysis_job(job, request, auto_paper_trade=False)
        except Exception as exc:  # noqa: BLE001
            holder["error"] = exc

    t = threading.Thread(target=_target, daemon=True, name=f"rebalance-analysis-{ticker}")
    t.start()
    t.join(timeout)

    if t.is_alive():
        return None, f"analysis timed out after {timeout:.0f}s"
    if "error" in holder:
        return None, f"analysis error: {holder['error']}"
    if getattr(job, "status", None) != "complete" or not getattr(job, "result", None):
        return None, f"analysis failed: {getattr(job, 'error', 'unknown')}"
    return job.result.structured_verdict, None


def _run_rebalance_locked(target_tickers: Optional[list[str]]) -> dict[str, Any]:
    client = get_alpaca_client()
    current_positions = client.get_positions()
    current_symbols = {p["symbol"] for p in current_positions}

    # Resolve the target universe. Fail closed: on a watchlist read error or an
    # empty universe, abort WITHOUT closing any positions (audit F-002).
    watchlist_sourced = target_tickers is None
    if watchlist_sourced:
        try:
            target_tickers = _get_watchlist_tickers()
        except WatchlistUnavailable as exc:
            logger.error(
                "Rebalance ABORTED: watchlist unreadable (%s). No positions closed.",
                exc,
            )
            return {
                "status": "aborted-watchlist-error",
                "error": str(exc),
                "closed": [],
                "opened": [],
                "errors": [f"watchlist read failed: {exc}"],
            }

    target_set = {t.upper() for t in (target_tickers or [])}
    if not target_set:
        logger.warning(
            "Rebalance ABORTED: empty target universe (fail-closed; no positions "
            "closed). Use an explicit close endpoint to flatten intentionally."
        )
        return {
            "status": "aborted-empty-universe",
            "closed": [],
            "opened": [],
            "errors": [],
        }

    ticker_timeout = float(settings.rebalance_ticker_timeout_seconds)
    closed: list[str] = []
    opened: list[str] = []
    errors: list[str] = []

    # 1) Close positions no longer in the target universe.
    for symbol in current_symbols:
        if symbol not in target_set:
            try:
                client.close_position(symbol)
                closed.append(symbol)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"close {symbol}: {exc}")

    for ticker in sorted(target_set):
        held = ticker in current_symbols
        structured, err = _analyze_bounded(ticker, ticker_timeout)
        if err:
            errors.append(f"analysis {ticker}: {err}")
            continue

        conviction = float(structured.get("conviction_score") or 0.0)
        side = _verdict_side(structured.get("verdict") or "")

        if held:
            # 2) Verdict-flip exit: a held name whose fresh verdict turned
            #    bearish is closed rather than silently kept (audit F-006).
            if side == "sell":
                try:
                    client.close_position(ticker)
                    closed.append(ticker)
                    logger.info("Rebalance: closed %s on bearish verdict flip", ticker)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"close {ticker}: {exc}")
            # Already-held bullish/neutral names are left in place.
            continue

        # 3) Open new positions that clear conviction + a directional verdict.
        if conviction < settings.auto_paper_trade_min_conviction:
            continue
        if side is None:
            continue
        try:
            order = client.submit_market_order(
                symbol=ticker, qty=settings.paper_default_qty, side=side
            )
            opened.append(ticker)
            logger.info("Rebalance: opened %s %s order=%s", side, ticker, order["order_id"])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"open {ticker}: {exc}")

    try:
        client.sync_positions_to_db()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Rebalance: sync failed: %s", exc)

    return {
        "status": "ok" if not errors else "partial",
        "closed": closed,
        "opened": opened,
        "errors": errors,
    }


def run_rebalance(target_tickers: Optional[list[str]] = None) -> dict[str, Any]:
    """Run one rebalance pass. Non-reentrant (audit F-005).

    If a rebalance is already running (scheduled or manual), this invocation
    is skipped rather than allowed to interleave order/close operations.
    """
    if not _rebalance_lock.acquire(blocking=False):
        logger.warning("Rebalance already in progress; skipping this invocation.")
        return {
            "status": "skipped-already-running",
            "closed": [],
            "opened": [],
            "errors": [],
        }
    try:
        return _run_rebalance_locked(target_tickers)
    finally:
        _rebalance_lock.release()


def _scheduled_rebalance():
    logger.info("Scheduled monthly rebalance starting...")
    try:
        result = run_rebalance()
        logger.info("Scheduled rebalance result: %s", result)
    except Exception as exc:
        logger.error("Scheduled rebalance failed: %s", exc, exc_info=True)


def create_scheduler(start: bool = True) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="US/Eastern")
    parts = settings.paper_rebalance_cron.split()
    if len(parts) == 5:
        trigger = CronTrigger(minute=parts[0], hour=parts[1], day=parts[2], month=parts[3], day_of_week=parts[4])
    else:
        trigger = CronTrigger(minute=30, hour=9, day=1)
    scheduler.add_job(
        _scheduled_rebalance,
        trigger=trigger,
        id="paper_rebalance",
        name="Monthly paper trading rebalance",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if start:
        scheduler.start()
        logger.info("Paper trading scheduler started (cron=%s)", settings.paper_rebalance_cron)
    return scheduler
