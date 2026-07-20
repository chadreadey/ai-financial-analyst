#!/usr/bin/env python3
"""
Pre-populate Finnhub sentiment cache for a backtest date range.

Run this ONCE before a long backtest. All news + insider MSPR data is
written to .sentiment_cache/ so the backtest loop never hits the API.

Usage:
    python scripts/prefetch_sentiment.py --universe liquid_20 --start 2025-01-01
    python scripts/prefetch_sentiment.py --tickers AAPL,MSFT,NVDA --start 2025-01-01

Notes:
    - Finnhub free tier: ~60 req/min, 1yr news history
    - News before ~1yr ago will return empty (cached as empty — still valid)
    - Insider MSPR has 10yr history — always populated
    - Already-cached windows are skipped (safe to re-run)
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import pandas as pd

from finnhub_client import FinnhubClient, SentimentDiskCache
from quant.universe import get_universe


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

RATE_LIMIT_SLEEP = 1.1  # seconds between API calls — stays under 60 req/min


def generate_monthly_dates(start: str, end: str) -> list[pd.Timestamp]:
    """Generate month-end rebalance dates between start and end."""
    dates = []
    current = pd.Timestamp(start) + pd.offsets.MonthEnd(0)
    stop = pd.Timestamp(end)
    while current <= stop:
        dates.append(current)
        current += pd.offsets.MonthEnd(1)
    return dates


def prefetch_news(
    tickers: list[str],
    rebalance_dates: list[pd.Timestamp],
    client: FinnhubClient,
    cache: SentimentDiskCache,
    window_days: int = 30,
) -> tuple[int, int]:
    """Prefetch news for all (ticker, window) pairs. Returns (fetched, skipped)."""
    windows = set()
    for d in rebalance_dates:
        from_d = (d - timedelta(days=window_days)).strftime("%Y-%m-%d")
        to_d = d.strftime("%Y-%m-%d")
        for t in tickers:
            windows.add((t.upper(), from_d, to_d))

    fetched = skipped = 0
    total = len(windows)
    for i, (ticker, from_d, to_d) in enumerate(sorted(windows), 1):
        if cache.load_news(ticker, from_d, to_d) is not None:
            skipped += 1
            continue

        try:
            articles = client.get_company_news(ticker, from_d, to_d)
            cache.save_news(ticker, from_d, to_d, articles)
            fetched += 1
            if fetched % 10 == 0:
                pct = i / total * 100
                logger.info(
                    "News: %d/%d (%.0f%%) | fetched=%d skipped=%d", i, total, pct, fetched, skipped
                )
        except Exception as e:
            logger.warning("News fetch failed %s %s→%s: %s", ticker, from_d, to_d, e)
            fetched += 1  # count as attempted to keep rate-limit sleep consistent

        time.sleep(RATE_LIMIT_SLEEP)

    return fetched, skipped


def prefetch_insider(
    tickers: list[str],
    rebalance_dates: list[pd.Timestamp],
    client: FinnhubClient,
    cache: SentimentDiskCache,
    lookback_months: int = 3,
) -> tuple[int, int]:
    """Prefetch insider MSPR for all (ticker, window) pairs. Returns (fetched, skipped)."""
    windows = set()
    for d in rebalance_dates:
        end = d - timedelta(days=30)  # 1-month lag for point-in-time safety
        start = end - timedelta(days=lookback_months * 31)
        from_d = start.strftime("%Y-%m-%d")
        to_d = end.strftime("%Y-%m-%d")
        for t in tickers:
            windows.add((t.upper(), from_d, to_d))

    fetched = skipped = 0
    total = len(windows)
    for i, (ticker, from_d, to_d) in enumerate(sorted(windows), 1):
        if cache.load_insider(ticker, from_d, to_d) is not None:
            skipped += 1
            continue

        try:
            records = client.get_insider_sentiment(ticker, from_d, to_d)
            cache.save_insider(ticker, from_d, to_d, records)
            fetched += 1
            if fetched % 10 == 0:
                pct = i / total * 100
                logger.info(
                    "Insider: %d/%d (%.0f%%) | fetched=%d skipped=%d",
                    i,
                    total,
                    pct,
                    fetched,
                    skipped,
                )
        except Exception as e:
            logger.warning("Insider fetch failed %s %s→%s: %s", ticker, from_d, to_d, e)
            fetched += 1

        time.sleep(RATE_LIMIT_SLEEP)

    return fetched, skipped


def main():
    parser = argparse.ArgumentParser(description="Pre-populate Finnhub sentiment cache")
    parser.add_argument(
        "--universe", default="liquid_20", help="Universe name (default: liquid_20)"
    )
    parser.add_argument(
        "--tickers", default="", help="Comma-separated tickers (overrides --universe)"
    )
    parser.add_argument(
        "--start", default="2025-01-01", help="Start date YYYY-MM-DD (default: 2025-01-01)"
    )
    parser.add_argument("--end", default="", help="End date YYYY-MM-DD (default: today)")
    parser.add_argument(
        "--news-only", action="store_true", help="Only prefetch news (skip insider MSPR)"
    )
    parser.add_argument(
        "--insider-only", action="store_true", help="Only prefetch insider MSPR (skip news)"
    )
    args = parser.parse_args()

    api_key = os.getenv("FINNHUB_API_KEY", "").strip()
    if not api_key:
        print("ERROR: FINNHUB_API_KEY not set. Export it or add to .env")
        sys.exit(1)

    tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers
        else get_universe(args.universe)
    )
    end = args.end or datetime.today().strftime("%Y-%m-%d")
    rebalance_dates = generate_monthly_dates(args.start, end)

    client = FinnhubClient(api_key)
    cache = SentimentDiskCache()

    total_windows = len(tickers) * len(rebalance_dates)
    est_minutes = (total_windows * 2 * RATE_LIMIT_SLEEP) / 60  # news + insider

    print(f"\nFinnhub Sentiment Prefetch")
    print(
        f"  Tickers:   {len(tickers)} ({', '.join(tickers[:5])}{'...' if len(tickers) > 5 else ''})"
    )
    print(f"  Dates:     {args.start} → {end} ({len(rebalance_dates)} rebalance months)")
    print(f"  Windows:   {total_windows} total")
    print(f"  Est. time: ~{est_minutes:.0f} min (uncached) — cached windows skip instantly")
    print(f"  Cache dir: {cache._dir}")
    print()

    t0 = time.time()

    if not args.insider_only:
        print("==> Fetching news sentiment...")
        n_fetched, n_skipped = prefetch_news(tickers, rebalance_dates, client, cache)
        print(f"    News done: {n_fetched} fetched, {n_skipped} skipped\n")

    if not args.news_only:
        print("==> Fetching insider MSPR...")
        i_fetched, i_skipped = prefetch_insider(tickers, rebalance_dates, client, cache)
        print(f"    Insider done: {i_fetched} fetched, {i_skipped} skipped\n")

    elapsed = time.time() - t0
    print(f"Prefetch complete in {elapsed / 60:.1f} min")
    print(f"Cache ready at: {cache._dir}")
    print(f"\nNow run the backtest — it will read from cache, no API calls during the run.")


if __name__ == "__main__":
    main()
