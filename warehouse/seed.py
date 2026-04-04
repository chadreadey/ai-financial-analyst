"""
Seed the Pinecone RAG index from the local warehouse SQLite database.

Uses Pinecone integrated inference (llama-text-embed-v2) — no OpenAI key needed.

Usage:
    python -m warehouse.seed                        # upsert all tickers
    python -m warehouse.seed --tickers AAPL MSFT    # upsert specific tickers
    python -m warehouse.seed --dry-run              # preview without upserting
    python -m warehouse.seed --tickers AAPL --dry-run

Environment (loaded from .env via config.py):
    PINECONE_API_KEY      — required
    PINECONE_INDEX_NAME   — default: financial-analyst
    PINECONE_NAMESPACE    — default: (empty)
    WAREHOUSE_DB_PATH     — default: .warehouse.db
    ENABLE_RAG            — must be true for RAG queries to fire at runtime
                            (seed script runs regardless of this flag)
"""

import argparse
import logging
import sys

# Ensure project root is on the path when run as `python -m warehouse.seed`
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from warehouse.embedder import embed_and_upsert_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _get_index():
    from pinecone import Pinecone, ServerlessSpec

    api_key = settings.pinecone_api_key.strip()
    if not api_key:
        logger.error("PINECONE_API_KEY is not set. Add it to .env and retry.")
        sys.exit(1)

    pc = Pinecone(api_key=api_key)
    index_name = settings.pinecone_index_name

    existing = [i.name for i in pc.list_indexes()]
    if index_name not in existing:
        logger.info("Creating Pinecone index '%s'...", index_name)
        pc.create_index(
            name=index_name,
            dimension=settings.pinecone_embed_dimensions,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        logger.info("Index created.")
    else:
        logger.info("Using existing Pinecone index '%s'", index_name)

    return pc.Index(index_name)


def main():
    parser = argparse.ArgumentParser(
        description="Embed SEC filing sections and upsert to Pinecone."
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        metavar="TICKER",
        help="Limit to specific tickers (default: all in warehouse)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview vectors without upserting to Pinecone",
    )
    args = parser.parse_args()

    db_path = settings.warehouse_db_path
    if not os.path.exists(db_path):
        logger.error("Warehouse DB not found at '%s'. Run a bootstrap first.", db_path)
        sys.exit(1)

    index = _get_index()

    summary = embed_and_upsert_all(
        db_path=db_path,
        index=index,
        namespace=settings.pinecone_namespace,
        batch_size=settings.pinecone_upsert_batch_size,
        tickers=args.tickers,
        dry_run=args.dry_run,
    )

    if summary:
        print("\nSeed summary:")
        for ticker, count in sorted(summary.items()):
            label = "vectors previewed" if args.dry_run else "vectors upserted"
            print(f"  {ticker}: {count} {label}")
    else:
        print("No sections found to embed.")


if __name__ == "__main__":
    main()
