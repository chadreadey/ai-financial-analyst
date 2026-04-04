"""
Seed Pinecone time-series namespaces with historical financial and macro data.

Financial source: SEC EDGAR XBRL (free, no API key needed — goes back to ~2009)
Macro source:     FRED API (free with API key)

Usage:
  python scripts/seed_timeseries.py --tickers AAPL MSFT NVDA
  python scripts/seed_timeseries.py --sp500                         # full S&P 500
  python scripts/seed_timeseries.py --sp500 --skip-existing         # resume after interruption
  python scripts/seed_timeseries.py --tickers AAPL --skip-macro --dry-run
  python scripts/seed_timeseries.py --skip-financial --start-year 2000
  python scripts/seed_timeseries.py --tickers AAPL --limit 20       # last 20 quarters

Environment variables required (or set in .env):
  PINECONE_API_KEY
  PINECONE_INDEX_NAME   (default: financial-analyst)
  FRED_API_KEY          (required for macro vectors)
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import pathlib
import sys
import urllib.request
from io import StringIO

# Ensure project root is on path when called from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seed_timeseries")

_ROOT = pathlib.Path(__file__).parent.parent


def _load_module(name: str, rel_path: str):
    """Load a warehouse submodule without triggering warehouse/__init__.py."""
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _get_pinecone_index(api_key: str, index_name: str):
    from pinecone import Pinecone
    pc = Pinecone(api_key=api_key)
    return pc.Index(index_name)


def _fetch_sp500_tickers() -> list[str]:
    logger.info("Fetching S&P 500 ticker list from Wikipedia...")
    import pandas as pd
    req = urllib.request.Request(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    html = urllib.request.urlopen(req).read().decode("utf-8")
    df = pd.read_html(StringIO(html))[0]
    tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
    logger.info("Fetched %d S&P 500 tickers", len(tickers))
    return tickers


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Pinecone time-series namespaces")

    ticker_group = parser.add_mutually_exclusive_group()
    ticker_group.add_argument(
        "--tickers",
        nargs="+",
        metavar="TICKER",
        help="Specific tickers to seed (e.g. AAPL MSFT NVDA)",
    )
    ticker_group.add_argument(
        "--sp500",
        action="store_true",
        help="Seed all S&P 500 tickers (fetched from Wikipedia)",
    )

    parser.add_argument(
        "--skip-financial",
        action="store_true",
        help="Skip financial (XBRL) vector upsert",
    )
    parser.add_argument(
        "--skip-macro",
        action="store_true",
        help="Skip macro (FRED) vector upsert",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip tickers already recorded in --seeded-file (safe to resume after interruption)",
    )
    parser.add_argument(
        "--seeded-file",
        default=str(_ROOT / ".seeded_tickers.txt"),
        help="Path to file tracking already-seeded tickers (default: .seeded_tickers.txt in project root)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be upserted without writing to Pinecone",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2000,
        help="Earliest year to include in macro vectors (default: 2000)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max quarterly periods per ticker (default: all available ~60 quarters from 2009)",
    )
    parser.add_argument(
        "--financial-namespace",
        default="financial_ts",
        help="Pinecone namespace for financial vectors (default: financial_ts)",
    )
    parser.add_argument(
        "--macro-namespace",
        default="macro_ts",
        help="Pinecone namespace for macro vectors (default: macro_ts)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Records per Pinecone upsert batch (default: 50)",
    )

    args = parser.parse_args()

    # ── load config ─────────────────────────────────────────────────────────
    from config import settings

    pinecone_key = (os.getenv("PINECONE_API_KEY") or settings.pinecone_api_key).strip()
    if not pinecone_key:
        logger.error("PINECONE_API_KEY is not set — aborting")
        sys.exit(1)

    index_name = (os.getenv("PINECONE_INDEX_NAME") or settings.pinecone_index_name).strip()
    fred_key = (os.getenv("FRED_API_KEY") or settings.fred_api_key).strip()

    # ── init Pinecone ────────────────────────────────────────────────────────
    logger.info("Connecting to Pinecone index '%s'...", index_name)
    index = _get_pinecone_index(pinecone_key, index_name)

    # ── financial vectors (XBRL) ─────────────────────────────────────────────
    if not args.skip_financial:
        if args.sp500:
            tickers = _fetch_sp500_tickers()
        else:
            tickers = [t.upper() for t in (args.tickers or [])]

        if not tickers:
            logger.warning(
                "No --tickers or --sp500 provided; skipping financial vectors."
            )
        else:
            xbrl_mod = _load_module("xbrl_vectors", "warehouse/xbrl_vectors.py")

            from sec.cache import SECCache
            from sec.client import SECClient

            sec_client = SECClient(
                user_agent=os.getenv("SEC_USER_AGENT", settings.sec_user_agent),
                cache=SECCache(),
            )

            summary = xbrl_mod.upsert_all_xbrl_financial_vectors(
                tickers=tickers,
                sec_client=sec_client,
                index=index,
                namespace=args.financial_namespace,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
                limit=args.limit,
                skip_existing=args.skip_existing,
                seeded_tickers_file=args.seeded_file,
            )

            seeded_count = sum(1 for v in summary.values() if v > 0)
            skipped_count = sum(1 for v in summary.values() if v == 0)
            total_records = sum(summary.values())
            logger.info(
                "Financial: %d tickers seeded (%d records), %d skipped",
                seeded_count, total_records, skipped_count,
            )

    # ── macro vectors (FRED) ─────────────────────────────────────────────────
    if not args.skip_macro:
        if not fred_key:
            logger.error("FRED_API_KEY is not set — cannot seed macro vectors")
        else:
            macro_mod = _load_module("macro_vectors", "warehouse/macro_vectors.py")

            count = macro_mod.upsert_macro_vectors(
                fred_api_key=fred_key,
                index=index,
                namespace=args.macro_namespace,
                start_year=args.start_year,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            action = "would upsert" if args.dry_run else "upserted"
            logger.info("Macro: %s %d records", action, count)

    logger.info("Done.")


if __name__ == "__main__":
    main()
