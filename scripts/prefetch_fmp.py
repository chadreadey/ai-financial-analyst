#!/usr/bin/env python3
"""
Prefetch FMP fundamental data (income statements, balance sheets, analyst estimates)
to SQLite cache for backtesting without burning API calls.

Usage:
    python scripts/prefetch_fmp.py --universe liquid_10
    python scripts/prefetch_fmp.py --universe liquid_50
    python scripts/prefetch_fmp.py --tickers AAPL,MSFT,GOOGL
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import os
from fmp_client import FMPClient
from quant.fmp_cache import FMPFundamentalCache
from quant.universe import get_universe


def main():
    parser = argparse.ArgumentParser(description="Prefetch FMP fundamental data to cache")
    parser.add_argument("--universe", default="liquid_10",
                        help="Universe name (default: liquid_10)")
    parser.add_argument("--tickers", default="",
                        help="Comma-separated tickers (overrides --universe)")
    parser.add_argument("--force", action="store_true",
                        help="Re-fetch even if cached")
    parser.add_argument("--sleep", type=float, default=0.5,
                        help="Seconds between API calls (default: 0.5)")

    args = parser.parse_args()

    fmp_key = os.getenv("FMP_API_KEY", "").strip()
    if not fmp_key:
        print("ERROR: FMP_API_KEY not set in .env")
        sys.exit(1)

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        tickers = get_universe(args.universe)

    client = FMPClient(fmp_key)
    cache = FMPFundamentalCache()

    print(f"Prefetching FMP data for {len(tickers)} tickers...")
    print(f"  3 endpoints per ticker × {len(tickers)} tickers = {len(tickers) * 3} max API calls")
    print(f"  FMP free tier: 250 calls/day")
    print(f"  Estimated time: {len(tickers) * 3 * args.sleep / 60:.1f} minutes")
    print()

    t0 = time.time()
    stats = cache.prefetch(tickers, client, rate_limit_sleep=args.sleep, force=args.force)
    elapsed = time.time() - t0

    print(f"\nDone in {elapsed:.1f}s")
    print(f"  API calls: {stats['api_calls']}")
    print(f"  Already cached: {stats['cached']}")
    print(f"  Errors: {stats['errors']}")
    print(f"  Total tickers in cache: {cache.ticker_count()}")
    print(f"  Cache summary: {cache.summary()}")
    print(f"  FMP calls used this session: {client.call_count}")


if __name__ == "__main__":
    main()
