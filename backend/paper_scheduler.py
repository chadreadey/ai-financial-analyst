"""
Monthly paper trading rebalance scheduler.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import date
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


def _quant_screen(
    as_of_date: Optional[date] = None,
    top_n: int = 30,
    max_per_sector: int = 5,
    universe: Optional[list[str]] = None,
) -> list[str]:
    """
    Rank the WRDS PIT ∩ price-cache universe by the v4-qmj-only composite
    and return the top-N tickers subject to a sector cap.

    Mirrors the per-rebalance precompute block from `quant/backtest.py`
    (lines 2125–2426) for the four active production signals:
      - OBV trend (weight 0.20)
      - earnings_rank_score via ERM+SUE+Dispersion (weight 0.40)
      - QMJ via compute_qmj_score (weight 0.30)
      - institutional_flow_score (weight 0.10)

    Point-in-time discipline: all data sources are filtered to as_of_date
    before signals are computed. Tickers with no WRDS coverage retain
    neutral (0.0) scores for the unavailable components — they still rank
    via OBV alone.

    Args:
        as_of_date: Ranking date. Defaults to today.
        top_n: Number of tickers to return.
        max_per_sector: Maximum tickers per GICS sector (sector cap).
        universe: Override the default WRDS ∩ price-cache universe.
            Primarily for testing. If None, derives the intersection
            from the live WRDS DB + `.price_cache/` directory.

    Returns:
        list[str]: Tickers ordered by composite descending, length <= top_n.
        Empty list is a valid no-result (NOT an error).

    Never raises — the caller (`run_rebalance`) catches any exception and
    falls back to the watchlist path.
    """
    # ── R8: lazy imports inside the function body so FastAPI startup
    # never depends on quant deps being importable. Any ImportError here
    # surfaces at screen time, not server start time.
    import pandas as pd

    from quant.backtest import compute_signals_at_date
    from quant.cross_sectional import (
        compute_normalized_composite,
        make_volatility_tier_fn,
        normalize_signals_cross_sectionally,
    )
    from quant.earnings_signals import (
        blend_earnings_signals,
        compute_earnings_signal_scores,
    )
    from quant.factor_baselines import compute_qmj_score
    from quant.fundamental_provider import WRDSFundamentalProvider
    from quant.institutional_flow import (
        blend_institutional_flow,
        compute_institutional_flow_scores,
    )
    from quant.universe import get_sector
    from quant.wrds_store import WRDSPointInTimeStore

    if as_of_date is None:
        as_of_date = date.today()

    REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    WRDS_DB_PATH = os.path.join(REPO_ROOT, ".wrds_pit.db")
    PRICE_CACHE_DIR = os.path.join(REPO_ROOT, ".price_cache")

    # ── 1. Resolve universe ────────────────────────────────────────────
    if universe is None:
        try:
            conn = sqlite3.connect(WRDS_DB_PATH)
            wrds_rows = conn.execute(
                "SELECT DISTINCT ticker FROM compustat_quarterly ORDER BY ticker"
            ).fetchall()
            conn.close()
            wrds_tickers = {r[0] for r in wrds_rows}
        except Exception as exc:
            logger.warning("Quant screen: WRDS DB read failed (%s) — empty universe", exc)
            wrds_tickers = set()

        try:
            price_tickers = {
                f.replace(".csv", "")
                for f in os.listdir(PRICE_CACHE_DIR)
                if f.endswith(".csv")
            }
        except Exception as exc:
            logger.warning("Quant screen: price cache scan failed (%s)", exc)
            price_tickers = set()

        universe = sorted(wrds_tickers & price_tickers)

    if not universe:
        logger.warning("Quant screen: empty universe — returning []")
        return []

    # ── 2. Price data loading (PIT-safe) ───────────────────────────────
    as_of_ts = pd.Timestamp(as_of_date)
    universe_data: dict = {}
    for ticker in universe:
        path = os.path.join(PRICE_CACHE_DIR, f"{ticker}.csv")
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_csv(path, parse_dates=["date"], index_col="date")
        except Exception as exc:
            logger.debug("Quant screen: skip %s — read_csv failed (%s)", ticker, exc)
            continue
        df.index = df.index.normalize()
        available = df[df.index <= as_of_ts]
        if len(available) < 60:
            continue
        universe_data[ticker] = available

    if not universe_data:
        logger.warning("Quant screen: no tickers with >=60 PIT rows — returning []")
        return []

    # ── 3. Technical signals (OBV + ATR for vol tier) ──────────────────
    signals = compute_signals_at_date(
        universe_data, as_of_ts, lookback_days=252,
    )
    if not signals:
        logger.warning("Quant screen: compute_signals_at_date returned empty — []")
        return []

    # ── 4. WRDS store + provider for fundamentals ──────────────────────
    store = WRDSPointInTimeStore()
    provider = WRDSFundamentalProvider(store)

    # ── 5. Earnings signal (weight 0.40) ───────────────────────────────
    try:
        earn_scores = compute_earnings_signal_scores(
            list(signals.keys()), provider, as_of_date=as_of_date,
        )
        if earn_scores:
            signals = blend_earnings_signals(signals, earn_scores, weight=0.30)
        else:
            logger.warning("Quant screen: no earnings scores returned (provider empty?)")
    except Exception as exc:
        logger.warning("Quant screen: earnings signals failed (%s) — continuing", exc)

    # ── 6. QMJ signal (weight 0.30) ────────────────────────────────────
    for ticker, sv in signals.items():
        try:
            raw = compute_qmj_score(ticker, as_of_date, store)
            sv.qmj_score = float(raw) if raw is not None else 0.0
        except Exception:
            sv.qmj_score = 0.0

    # ── 7. Institutional flow signal (weight 0.10) ─────────────────────
    try:
        inst_scores = compute_institutional_flow_scores(
            list(signals.keys()),
            as_of_date=as_of_date,
            wrds_store=store,
            fmp_client=None,
            fmp_cache=None,
            finnhub_client=None,
            finnhub_disk_cache=None,
        )
        if inst_scores:
            signals = blend_institutional_flow(signals, inst_scores, weight=0.10)
        else:
            # R2: warn explicitly so the missing 13F path is visible.
            logger.warning(
                "Quant screen: institutional flow returned no scores — "
                "composite degrades to 3 signals (verify WRDS 13F populated)"
            )
    except Exception as exc:
        logger.warning("Quant screen: institutional flow failed (%s) — continuing", exc)

    # ── 8. Cross-sectional normalization (vol-tier grouped) ────────────
    # R6: MUST use make_volatility_tier_fn here (NOT get_sector) to match
    # the audit walk-forward rankings. get_sector is only for the cap.
    signals = normalize_signals_cross_sectionally(
        signals, make_volatility_tier_fn(signals),
    )

    # ── 9. Composite per ticker ────────────────────────────────────────
    composites: dict[str, float] = {
        ticker: compute_normalized_composite(sv)
        for ticker, sv in signals.items()
    }

    # ── 10. Sort + sector cap ──────────────────────────────────────────
    ranked = sorted(composites.items(), key=lambda kv: kv[1], reverse=True)
    selected: list[str] = []
    sector_counts: dict[str, int] = {}
    for ticker, _score in ranked:
        sector = get_sector(ticker)
        if sector_counts.get(sector, 0) >= max_per_sector:
            continue
        selected.append(ticker)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(selected) >= top_n:
            break

    logger.info(
        "Quant screen: as_of=%s universe=%d signals=%d selected=%d top5=%s",
        as_of_date, len(universe), len(signals), len(selected), selected[:5],
    )
    return selected


def run_rebalance(
    target_tickers: Optional[list[str]] = None,
    use_quant_screen: bool = True,
    top_n_quant: int = 30,
    as_of_date: Optional[date] = None,
) -> dict[str, Any]:
    """
    Trigger one rebalance pass against the Alpaca paper account.

    Resolution priority for the candidate set:
      1. `target_tickers` (explicit override; bypasses screen entirely)
      2. Quant composite screen via `_quant_screen` (when `use_quant_screen`)
      3. Watchlist table (legacy fallback)
      4. No-op (`{"status": "no_targets", ...}`)

    Failures in the quant screen are logged with full traceback and fall
    through to the watchlist path; the caller still gets a successful
    rebalance against whatever targets the fallback produced.
    """
    client = get_alpaca_client()
    current_positions = client.get_positions()
    current_symbols = {p["symbol"] for p in current_positions}

    # ── Priority chain ─────────────────────────────────────────────────
    if target_tickers is not None:
        resolved_tickers: list[str] = list(target_tickers)
        logger.info(
            "Rebalance: using %d explicit tickers (override)", len(resolved_tickers),
        )
    elif use_quant_screen:
        try:
            resolved_tickers = _quant_screen(
                as_of_date=as_of_date, top_n=top_n_quant,
            )
            logger.info(
                "Rebalance: quant screen returned %d tickers as of %s",
                len(resolved_tickers), as_of_date or date.today(),
            )
        except Exception as exc:
            # R8 / loud-failure spec: traceback in the logs, transparent
            # fallback for the caller.
            logger.warning(
                "Rebalance: quant screen failed (%s) — falling back to watchlist",
                exc, exc_info=True,
            )
            resolved_tickers = _get_watchlist_tickers()
            logger.info(
                "Rebalance: watchlist fallback returned %d tickers",
                len(resolved_tickers),
            )
    else:
        resolved_tickers = _get_watchlist_tickers()
        logger.info(
            "Rebalance: watchlist returned %d tickers", len(resolved_tickers),
        )

    if not resolved_tickers:
        logger.info("Rebalance: no targets resolved — no-op")
        return {"status": "no_targets", "closed": [], "opened": [], "errors": []}

    target_set = {t.upper() for t in resolved_tickers}

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
