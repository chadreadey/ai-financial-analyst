"""
Monthly paper trading rebalance scheduler.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings
from backend.alpaca_paper_client import get_alpaca_client
from backend.jobs import create_job, run_analysis_job
from backend.schemas import RunAnalysisRequest

logger = logging.getLogger(__name__)


def _get_watchlist_tickers() -> list[str]:
    try:
        conn = sqlite3.connect(settings.warehouse_db_path)
        rows = conn.execute("SELECT ticker FROM watchlist").fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def run_rebalance(target_tickers: Optional[list[str]] = None) -> dict[str, Any]:
    client = get_alpaca_client()
    current_positions = client.get_positions()
    current_symbols = {p["symbol"] for p in current_positions}

    if not target_tickers:
        target_tickers = _get_watchlist_tickers()
    target_set = {t.upper() for t in target_tickers}

    closed: list[str] = []
    opened: list[str] = []
    errors: list[str] = []

    for symbol in current_symbols:
        if symbol not in target_set:
            try:
                client.close_position(symbol)
                closed.append(symbol)
            except Exception as exc:
                errors.append(f"close {symbol}: {exc}")

    for ticker in target_set:
        if ticker in current_symbols:
            continue
        try:
            job = create_job(ticker)
            request = RunAnalysisRequest(ticker=ticker)
            run_analysis_job(job, request)

            if job.status != "complete" or not job.result:
                errors.append(f"analysis {ticker}: {getattr(job, 'error', 'failed')}")
                continue

            structured = job.result.structured_verdict
            conviction = float(structured.get("conviction_score", 0))
            verdict = (structured.get("verdict") or "").upper()

            if conviction < settings.auto_paper_trade_min_conviction:
                continue

            if "BUY" in verdict:
                side = "buy"
            elif "SELL" in verdict:
                side = "sell"
            else:
                continue

            order = client.submit_market_order(symbol=ticker, qty=settings.paper_default_qty, side=side)
            opened.append(ticker)
            logger.info("Rebalance: opened %s %s order=%s", side, ticker, order["order_id"])
        except Exception as exc:
            errors.append(f"open {ticker}: {exc}")

    try:
        client.sync_positions_to_db()
    except Exception as exc:
        logger.warning("Rebalance: sync failed: %s", exc)

    return {
        "status": "ok" if not errors else "partial",
        "closed": closed,
        "opened": opened,
        "errors": errors,
    }


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
    )
    if start:
        scheduler.start()
        logger.info("Paper trading scheduler started (cron=%s)", settings.paper_rebalance_cron)
    return scheduler
