"""
Update worker: consumes filing update jobs from Redis queue.

For each job:
  1. Mark accession as processing (dedup guard)
  2. Run incremental_update(ticker, db, sec_client)
  3. If had_changes: re-seed Pinecone for the ticker
  4. Unmark processing
  5. On failure: send to dead letter queue

The worker blocks on BRPOP so it does not spin when the queue is empty.

Environment:
    DATABASE_URL               Supabase postgres connection string (or blank for SQLite)
    WAREHOUSE_DB_PATH          SQLite path when DATABASE_URL is blank (default: .warehouse.db)
    SEC_USER_AGENT             User-Agent header for SEC EDGAR
    UPSTASH_REDIS_REST_URL
    UPSTASH_REDIS_REST_TOKEN
    PINECONE_API_KEY
    PINECONE_INDEX_NAME        default: financial-analyst
    PINECONE_NAMESPACE         default: (empty string)
"""

import logging
import os
import sys
import time

# ── project root on sys.path so we can import warehouse/config ───────────────
_INFRA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_INFRA_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from infra.worker.queue_client import (
    dequeue_job,
    is_processing,
    mark_processing,
    send_to_dead_letter,
    unmark_processing,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [update_worker] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Pinecone index (lazy-initialised once at startup) ─────────────────────────
_pinecone_index = None


def _get_pinecone_index():
    global _pinecone_index
    if _pinecone_index is not None:
        return _pinecone_index

    from pinecone import Pinecone, ServerlessSpec

    api_key = os.environ.get("PINECONE_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError("PINECONE_API_KEY is not set")

    index_name = os.environ.get("PINECONE_INDEX_NAME", "financial-analyst")
    pc = Pinecone(api_key=api_key)

    existing = [i.name for i in pc.list_indexes()]
    if index_name not in existing:
        logger.info("creating Pinecone index '%s'", index_name)
        pc.create_index(
            name=index_name,
            dimension=1536,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )

    _pinecone_index = pc.Index(index_name)
    return _pinecone_index


# ── Database helpers ──────────────────────────────────────────────────────────

def build_db():
    """
    Return a WarehouseDB instance.

    Backend is selected automatically by WarehouseDB based on DATABASE_URL:
      - DATABASE_URL set   → psycopg2 / Supabase PostgreSQL
      - DATABASE_URL unset → sqlite3  (.warehouse.db)
    """
    from warehouse.db import WarehouseDB

    db_path = os.environ.get("WAREHOUSE_DB_PATH", ".warehouse.db")
    if not os.path.isabs(db_path):
        db_path = os.path.join(_PROJECT_ROOT, db_path)
    return WarehouseDB(db_path=db_path)


def build_sec_client():
    from sec.client import SECClient

    user_agent = os.environ.get(
        "SEC_USER_AGENT", "AIFinancialAnalyst admin@example.com"
    )
    return SECClient(user_agent=user_agent)


# ── Pinecone re-seed for a single ticker ─────────────────────────────────────

def reseed_ticker(ticker: str, db_path: str) -> int:
    """
    Re-embed and upsert all filing sections for a ticker into Pinecone.
    Returns the number of records upserted.
    """
    from warehouse.embedder import upsert_ticker_sections

    index = _get_pinecone_index()
    namespace = os.environ.get("PINECONE_NAMESPACE", "")
    count = upsert_ticker_sections(
        ticker=ticker,
        db_path=db_path,
        index=index,
        namespace=namespace,
        batch_size=100,
        dry_run=False,
    )
    logger.info("pinecone re-seed for %s: %d records upserted", ticker, count)
    return count


# ── Job processor ─────────────────────────────────────────────────────────────

def process_job(job: dict) -> None:
    """
    Process a single filing update job.

    Steps:
      1. Validate fields
      2. Dedup check — skip if already processing
      3. Mark as processing
      4. Run incremental_update
      5. Re-seed Pinecone if there were changes
      6. Unmark processing
    """
    ticker = job.get("ticker", "").upper()
    accession = job.get("accession", "")
    form = job.get("form", "")

    if not ticker or not accession:
        raise ValueError(f"job missing ticker or accession: {job!r}")

    logger.info("processing job: ticker=%s accession=%s form=%s", ticker, accession, form)

    if is_processing(accession):
        logger.info(
            "accession %s already processing (duplicate job) — skipping", accession
        )
        return

    mark_processing(accession)
    try:
        db = build_db()
        sec_client = build_sec_client()

        from warehouse.change_detector import incremental_update

        result = incremental_update(ticker, db, sec_client)
        logger.info(
            "incremental_update %s: had_changes=%s new_filings=%d elapsed=%.1fs",
            ticker, result.had_changes, result.new_filing_count, result.elapsed_s,
        )

        if result.had_changes:
            # Re-seed Pinecone so RAG reflects the new filing text
            db_path = os.environ.get("WAREHOUSE_DB_PATH", ".warehouse.db")
            if not os.path.isabs(db_path):
                db_path = os.path.join(_PROJECT_ROOT, db_path)
            try:
                reseed_ticker(ticker, db_path)
            except Exception as exc:
                # Pinecone failure is non-fatal — log and continue
                logger.error("pinecone re-seed failed for %s: %s", ticker, exc)

    finally:
        unmark_processing(accession)


# ── Main consumer loop ────────────────────────────────────────────────────────

def main() -> None:
    logger.info("update worker starting")

    while True:
        try:
            job = dequeue_job(block_seconds=5)
        except Exception as exc:
            logger.error("dequeue error: %s", exc, exc_info=True)
            time.sleep(5)
            continue

        if job is None:
            # Queue was empty for the blocking window — loop immediately
            continue

        try:
            process_job(job)
        except Exception as exc:
            logger.error(
                "job failed: ticker=%s accession=%s error=%s",
                job.get("ticker"), job.get("accession"), exc,
                exc_info=True,
            )
            try:
                send_to_dead_letter(job, str(exc))
            except Exception as dlq_exc:
                logger.error("failed to write to dead letter queue: %s", dlq_exc)


if __name__ == "__main__":
    main()
