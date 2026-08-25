"""
Pinecone embedding pipeline for SEC filing sections.

Uses Pinecone integrated inference (llama-text-embed-v2) — no external
embedding model required. Records are upserted via index.upsert_records();
Pinecone handles embedding internally.

Record ID format: {TICKER}_{accession_no_hyphens}_{section_key}
  e.g. AAPL_0000320193-23-000106_mda

Fields stored per record:
  _id, text, ticker, accession, section_key, form_type, filing_date

Text is NOT sub-chunked — each filing_sections row is one record
(sections are already semantically coherent SEC Item boundaries).
"""

import logging
import time
from typing import List, Optional

logger = logging.getLogger(__name__)


def _make_vector_id(ticker: str, accession: str, section_key: str) -> str:
    """Deterministic, idempotent record ID. Upserts are safe to re-run."""
    clean_accession = accession.replace("-", "")
    return f"{ticker.upper()}_{clean_accession}_{section_key}"


def _fetch_sections(
    db_path: str,
    tickers: Optional[List[str]] = None,
) -> List[dict]:
    """
    Fetch all filing_sections rows joined with filings metadata via WarehouseDB.

    Returns list of dicts with keys:
      ticker, accession, section_key, text, form_type, filing_date
    """
    from warehouse.db import WarehouseDB

    db = WarehouseDB(db_path)
    return db.list_filing_sections(tickers=tickers)


def _batch(items: list, size: int):
    """Yield successive chunks of `size` from `items`."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def upsert_ticker_sections(
    ticker: str,
    db_path: str,
    index,
    namespace: str,
    batch_size: int = 100,
    dry_run: bool = False,
) -> int:
    """
    Upsert all filing_sections for a single ticker via Pinecone integrated inference.
    Pinecone embeds the `text` field internally (llama-text-embed-v2).
    Returns the number of records upserted (or previewed in dry-run).
    """
    rows = _fetch_sections(db_path, tickers=[ticker])
    if not rows:
        logger.info("[%s] No filing sections found — skipping", ticker)
        return 0

    logger.info("[%s] Upserting %d sections...", ticker, len(rows))
    total = 0

    for chunk in _batch(rows, batch_size):
        records = []
        for row in chunk:
            rid = _make_vector_id(row["ticker"], row["accession"], row["section_key"])
            records.append(
                {
                    "_id": rid,
                    "text": row["text"][:4000],
                    "ticker": row["ticker"],
                    "accession": row["accession"],
                    "section_key": row["section_key"],
                    "form_type": row["form_type"],
                    "filing_date": row["filing_date"],
                }
            )

        ns = namespace or "__default__"
        if dry_run:
            logger.info("[%s] DRY RUN — would upsert %d records", ticker, len(records))
        else:
            try:
                index.upsert_records(ns, records)
                logger.info("[%s] Upserted %d records", ticker, len(records))
            except Exception as exc:
                logger.error("[%s] Upsert failed: %s", ticker, exc)
                continue

        total += len(records)
        time.sleep(0.05)

    return total


def embed_and_upsert_all(
    db_path: str,
    index,
    namespace: str,
    batch_size: int = 100,
    tickers: Optional[List[str]] = None,
    dry_run: bool = False,
) -> dict:
    """
    Upsert all filing sections (or a subset of tickers) via Pinecone integrated inference.

    Returns summary dict: {ticker: count_upserted, ...}
    """
    if tickers:
        target_tickers = [t.upper() for t in tickers]
    else:
        rows = _fetch_sections(db_path)
        seen = {}
        for r in rows:
            seen[r["ticker"]] = True
        target_tickers = sorted(seen.keys())

    if not target_tickers:
        logger.info("No tickers found in filing_sections — nothing to upsert")
        return {}

    logger.info("Upserting %d tickers: %s", len(target_tickers), target_tickers)
    summary = {}

    for ticker in target_tickers:
        count = upsert_ticker_sections(
            ticker=ticker,
            db_path=db_path,
            index=index,
            namespace=namespace,
            batch_size=batch_size,
            dry_run=dry_run,
        )
        summary[ticker] = count

    total = sum(summary.values())
    logger.info("Done. Total records %s: %d", "previewed" if dry_run else "upserted", total)
    return summary
