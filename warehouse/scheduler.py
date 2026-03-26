"""
Scheduled refresh cycle for the filing warehouse.

Iterates over tracked tickers and runs incremental updates,
respecting SEC rate limits by processing sequentially.
"""

import logging

from sec.client import SECClient
from warehouse.change_detector import UpdateResult, incremental_update, needs_update
from warehouse.db import WarehouseDB

logger = logging.getLogger(__name__)


def run_refresh_cycle(
    tickers: list[str] | None,
    db: WarehouseDB,
    sec_client: SECClient,
    dry_run: bool = False,
) -> dict[str, UpdateResult]:
    """
    Run incremental_update for each ticker in sequence.

    Args:
        tickers:    Explicit list, or None to use all tracked tickers from the DB.
        db:         WarehouseDB instance.
        sec_client: SECClient instance (reused across tickers for rate-limit state).
        dry_run:    If True, only check staleness and log—never write.

    Returns:
        Mapping of ticker -> UpdateResult.
    """
    if tickers is None:
        tickers = db.list_tracked_tickers()

    if not tickers:
        logger.info("refresh cycle: no tickers to process")
        return {}

    logger.info("refresh cycle: %d ticker(s) queued", len(tickers))
    results: dict[str, UpdateResult] = {}

    for ticker in tickers:
        ticker = ticker.upper()
        if dry_run:
            stale = needs_update(ticker, db, sec_client)
            logger.info("dry-run %s: needs_update=%s", ticker, stale)
            results[ticker] = UpdateResult(
                ticker=ticker,
                had_changes=stale,
                new_filing_count=0,
                elapsed_s=0.0,
            )
            continue

        try:
            result = incremental_update(ticker, db, sec_client)
            results[ticker] = result
        except Exception:
            logger.error(
                "refresh cycle: error updating %s", ticker, exc_info=True,
            )
            results[ticker] = UpdateResult(
                ticker=ticker,
                had_changes=False,
                new_filing_count=0,
                elapsed_s=0.0,
            )

    changed = sum(1 for r in results.values() if r.had_changes)
    logger.info(
        "refresh cycle complete: %d/%d tickers had changes",
        changed, len(results),
    )
    return results
