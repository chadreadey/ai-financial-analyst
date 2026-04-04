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


def _seed_ticker(ticker: str, db: WarehouseDB) -> None:
    """Re-seed Pinecone for a single ticker after a warehouse update."""
    try:
        from pinecone import Pinecone
        from warehouse.embedder import embed_and_upsert_all
        from config import settings

        api_key = settings.pinecone_api_key.strip()
        if not api_key:
            return

        pc = Pinecone(api_key=api_key)
        index = pc.Index(settings.pinecone_index_name)
        summary = embed_and_upsert_all(
            db_path=db._db_path,
            index=index,
            namespace=settings.pinecone_namespace or "__default__",
            tickers=[ticker],
        )
        seeded = sum(summary.values())
        logger.info("Pinecone re-seed %s: %d records", ticker, seeded)
    except Exception:
        logger.warning("Pinecone re-seed failed for %s", ticker, exc_info=True)


def run_refresh_cycle(
    tickers: list[str] | None,
    db: WarehouseDB,
    sec_client: SECClient,
    dry_run: bool = False,
    seed_pinecone: bool = True,
) -> dict[str, UpdateResult]:
    """
    Run incremental_update for each ticker in sequence.

    Args:
        tickers:    Explicit list, or None to use all tracked tickers from the DB.
        db:         WarehouseDB instance.
        sec_client: SECClient instance (reused across tickers for rate-limit state).
        dry_run:    If True, only check staleness and log—never write.
        seed_pinecone: If True, re-seed Pinecone after updates that had changes.

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
            if result.had_changes and seed_pinecone and not dry_run:
                _seed_ticker(ticker, db)
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
