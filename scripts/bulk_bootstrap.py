"""
Bulk bootstrap: ingest a ticker list into the warehouse, then seed Pinecone.

Seeds Pinecone immediately after each ticker's bootstrap so that the RAG
index grows incrementally — a partial run is still useful.

Usage:
    python3.10 scripts/bulk_bootstrap.py
    python3.10 scripts/bulk_bootstrap.py --tickers AAPL MSFT   # subset
    python3.10 scripts/bulk_bootstrap.py --no-seed             # DB only
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bulk_bootstrap")

DEFAULT_TICKERS = [
    # Mega-cap tech
    "AAPL",
    "MSFT",
    "GOOGL",
    "META",
    "NVDA",
    "AMZN",
    "TSLA",
    # Financials
    "JPM",
    "GS",
    "BAC",
    # Healthcare
    "JNJ",
    "LLY",
    "UNH",
    # Energy
    "XOM",
    "CVX",
    # Consumer
    "WMT",
    "HD",
    "MCD",
    "NKE",
    "COST",
    # Industrials
    "CAT",
    "HON",
    # Semiconductors
    "AMD",
    "AVGO",
    # Media / Comm
    "NFLX",
    "DIS",
]


def _get_pinecone_index():
    from pinecone import Pinecone
    from config import settings

    api_key = settings.pinecone_api_key.strip()
    if not api_key:
        return None
    pc = Pinecone(api_key=api_key)
    return pc.Index(settings.pinecone_index_name)


def seed_ticker(ticker: str, index, db_path: str, namespace: str) -> int:
    from warehouse.embedder import upsert_ticker_sections

    count = upsert_ticker_sections(
        ticker=ticker,
        db_path=db_path,
        index=index,
        namespace=namespace or "__default__",
        batch_size=100,
    )
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="+", metavar="TICKER")
    parser.add_argument("--no-seed", action="store_true", help="Skip Pinecone seeding")
    parser.add_argument("--no-text", action="store_true", help="Skip filing text (XBRL only, fast)")
    parser.add_argument(
        "--sections-limit", type=int, default=None, help="Override 10-K sections limit"
    )
    parser.add_argument("--tenq-limit", type=int, default=None, help="Override 10-Q sections limit")
    args = parser.parse_args()

    # Apply overrides before importing settings (settings reads from env at import time)
    if args.no_text:
        os.environ["ENABLE_FILING_TEXT"] = "false"
    if args.sections_limit is not None:
        os.environ["WAREHOUSE_SECTIONS_LIMIT"] = str(args.sections_limit)
    if args.tenq_limit is not None:
        os.environ["WAREHOUSE_TENQ_LIMIT"] = str(args.tenq_limit)

    tickers = [t.upper() for t in (args.tickers or DEFAULT_TICKERS)]
    do_seed = not args.no_seed

    from sec.client import SECClient
    from warehouse.bootstrap import bootstrap_ticker
    from warehouse.db import WarehouseDB
    from config import settings

    db = WarehouseDB()
    sec = SECClient()
    index = _get_pinecone_index() if do_seed else None
    namespace = settings.pinecone_namespace or "__default__"
    db_path = settings.warehouse_db_path

    total = len(tickers)
    results = []

    for i, ticker in enumerate(tickers, 1):
        logger.info("━━━ [%d/%d] %s ━━━", i, total, ticker)
        t0 = time.monotonic()

        try:
            result = bootstrap_ticker(ticker, db, sec)
            logger.info(
                "%s bootstrapped: %d filings, %d facts, %d sections (%.1fs)",
                ticker,
                result.filing_count,
                result.fact_count,
                result.sections_extracted,
                result.elapsed_s,
            )
        except Exception as exc:
            logger.error("%s bootstrap FAILED: %s", ticker, exc)
            results.append((ticker, "FAILED", 0))
            continue

        seeded = 0
        if index is not None:
            try:
                seeded = seed_ticker(ticker, index, db_path, namespace)
                logger.info("%s → Pinecone: %d records seeded", ticker, seeded)
            except Exception as exc:
                logger.warning("%s Pinecone seed failed: %s", ticker, exc)

        elapsed = time.monotonic() - t0
        results.append((ticker, "OK", seeded))
        logger.info("%s done in %.1fs\n", ticker, elapsed)

    print("\n" + "═" * 55)
    print(f"{'Ticker':<8} {'Status':<8} {'Pinecone records':>16}")
    print("─" * 55)
    for ticker, status, seeded in results:
        print(f"{ticker:<8} {status:<8} {seeded:>16}")
    ok = sum(1 for _, s, _ in results if s == "OK")
    total_seeded = sum(s for _, _, s in results)
    print("═" * 55)
    print(f"{ok}/{total} tickers bootstrapped  |  {total_seeded} total Pinecone records")


if __name__ == "__main__":
    main()
