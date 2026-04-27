#!/usr/bin/env python3
"""
Backfill Finnhub insider MSPR (Monthly Share Purchase Ratio) cache for the
full WRDS PIT ticker universe so the Session 2 audit IC harness can score
the `insider_mspr` signal.

Strategy:
  - One big-window API call per ticker (2014-01-01 → 2025-12-31) — Finnhub
    returns up to ~10yr of monthly records in a single response.
  - From the big-window result, emit per-window cache files matching the
    keys that `quant.sentiment.compute_insider_sentiment_score` looks up
    at run time:
        path = .sentiment_cache/insider_{TICKER}_{from}_{to}.json
        from = (rebalance_date - 30d - lookback_months*31d).strftime(%Y-%m-%d)
        to   = (rebalance_date - 30d).strftime(%Y-%m-%d)
  - Resumable: skip the big-window file if already present.

Usage:
    python scripts/prefetch_insider_mspr.py
    python scripts/prefetch_insider_mspr.py --start 2015-01-01 --end 2025-12-31
    python scripts/prefetch_insider_mspr.py --tickers AAPL,MSFT
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

import pandas as pd

from finnhub_client import FinnhubClient, SentimentDiskCache


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("prefetch_insider")

RATE_LIMIT_SLEEP = 1.1  # ~55 req/min; Finnhub free tier is 60/min

# Big-window pull horizon. 2014 start gives the audit's 2015 rebalance dates
# enough lookback context (3 months default).
BIG_WINDOW_FROM = "2014-01-01"
BIG_WINDOW_TO = "2025-12-31"


def get_wrds_tickers(db_path: Path) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM compustat_quarterly ORDER BY ticker"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def generate_audit_windows(
    start: str, end: str, lookback_months: int = 3,
) -> list[tuple[str, str]]:
    """
    Replicate the (from_date, to_date) window pairs that
    compute_insider_sentiment_score will look up at audit run time.

    For each calendar month-end rebalance d in [start, end]:
        end_d   = d - 30 days
        start_d = end_d - lookback_months*31 days
    """
    windows: set[tuple[str, str]] = set()
    s = pd.Timestamp(start) + pd.offsets.MonthEnd(0)
    e = pd.Timestamp(end)
    cur = s
    while cur <= e:
        end_d = cur - timedelta(days=30)
        start_d = end_d - timedelta(days=lookback_months * 31)
        windows.add((start_d.strftime("%Y-%m-%d"), end_d.strftime("%Y-%m-%d")))
        cur += pd.offsets.MonthEnd(1)
    # Also add business-month-end dates because the audit uses BME, not ME.
    bme = pd.date_range(start, end, freq="BME")
    for d in bme:
        end_d = d - timedelta(days=30)
        start_d = end_d - timedelta(days=lookback_months * 31)
        windows.add((start_d.strftime("%Y-%m-%d"), end_d.strftime("%Y-%m-%d")))
    return sorted(windows)


def filter_records_to_window(
    big_records: list[dict], from_date: str, to_date: str,
) -> list[dict]:
    """Return MSPR records whose (year, month) falls within [from, to]."""
    f = datetime.strptime(from_date, "%Y-%m-%d")
    t = datetime.strptime(to_date, "%Y-%m-%d")
    out = []
    for r in big_records:
        try:
            y = int(r.get("year"))
            m = int(r.get("month"))
        except (TypeError, ValueError):
            continue
        # Treat each record as the first day of its month for inclusion.
        rec_dt = datetime(y, m, 1)
        if f <= rec_dt <= t:
            out.append(r)
    return out


def emit_window_caches(
    ticker: str,
    big_records: list[dict],
    cache: SentimentDiskCache,
    windows: list[tuple[str, str]],
) -> tuple[int, int]:
    """
    Write per-window subset files.

    Returns (n_new_written, n_overwrites). An "overwrite" happens when an
    existing cache file is empty (the legacy partial-prefetch cohort wrote
    `[]` for many tickers) but the big-window pull contains matching MSPR
    records — in that case we replace the empty file with the real data.
    """
    written = 0
    overwrites = 0
    for from_d, to_d in windows:
        path = cache._path("insider", ticker, from_d, to_d)
        existing_empty = False
        if os.path.exists(path):
            try:
                with open(path) as f:
                    existing = json.load(f)
                existing_empty = isinstance(existing, list) and len(existing) == 0
            except Exception:
                existing_empty = True
            if not existing_empty:
                continue
        subset = filter_records_to_window(big_records, from_d, to_d)
        # Only overwrite empty files when the big-window actually has
        # matching records — otherwise we'd just rewrite the same `[]`.
        if existing_empty and not subset:
            continue
        cache.save_insider(ticker, from_d, to_d, subset)
        if existing_empty:
            overwrites += 1
        else:
            written += 1
    return written, overwrites


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--start", default="2015-01-01",
                   help="Audit start date (default: 2015-01-01)")
    p.add_argument("--end", default="2025-12-31",
                   help="Audit end date (default: 2025-12-31)")
    p.add_argument("--lookback-months", type=int, default=3)
    p.add_argument("--tickers", default="",
                   help="Comma-separated tickers (overrides WRDS universe)")
    p.add_argument("--limit", type=int, default=0,
                   help="Limit number of tickers (for testing)")
    p.add_argument("--db", default=str(REPO_ROOT / ".wrds_pit.db"))
    args = p.parse_args()

    api_key = os.getenv("FINNHUB_API_KEY", "").strip()
    if not api_key:
        logger.error("FINNHUB_API_KEY is not set in environment / .env — aborting")
        sys.exit(2)

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = get_wrds_tickers(Path(args.db))
    if args.limit:
        tickers = tickers[: args.limit]

    client = FinnhubClient(api_key)
    cache = SentimentDiskCache()
    big_dir = Path(cache._dir) / "insider_big"
    big_dir.mkdir(exist_ok=True)

    windows = generate_audit_windows(
        args.start, args.end, lookback_months=args.lookback_months,
    )
    logger.info(
        "Tickers=%d  audit windows=%d  big-window=%s..%s  cache=%s",
        len(tickers), len(windows), BIG_WINDOW_FROM, BIG_WINDOW_TO, cache._dir,
    )

    n_attempted = 0
    n_cached = 0
    n_no_data = 0
    n_failed = 0
    n_skipped = 0
    n_window_files_written = 0
    n_window_overwrites = 0
    response_times: list[float] = []

    for i, ticker in enumerate(tickers, 1):
        n_attempted += 1
        big_path = big_dir / f"{ticker}.json"

        # Resumable: load prior big-window pull instead of re-fetching
        if big_path.exists():
            n_skipped += 1
            try:
                with open(big_path) as f:
                    records = json.load(f)
            except Exception:
                records = []
        else:
            t0 = time.time()
            try:
                records = client.get_insider_sentiment(
                    ticker, BIG_WINDOW_FROM, BIG_WINDOW_TO,
                )
                response_times.append(time.time() - t0)
                with open(big_path, "w") as f:
                    json.dump(records, f)
            except Exception as exc:
                logger.warning("API failed for %s: %s", ticker, exc)
                n_failed += 1
                time.sleep(RATE_LIMIT_SLEEP)
                continue
            time.sleep(RATE_LIMIT_SLEEP)

        if not records:
            n_no_data += 1
        else:
            n_cached += 1

        # Emit per-window subset files even when records is empty —
        # an empty list is a valid cache hit ("no insider data") and
        # avoids cache-miss API hits during the audit run.
        try:
            new, overw = emit_window_caches(
                ticker, records or [], cache, windows,
            )
            n_window_files_written += new
            n_window_overwrites += overw
        except Exception as exc:
            logger.warning("emit_window_caches failed for %s: %s", ticker, exc)

        if i % 25 == 0 or i == len(tickers):
            avg_ms = (sum(response_times) / max(1, len(response_times))) * 1000
            logger.info(
                "Progress: %d/%d  cached=%d  no_data=%d  failed=%d  skipped=%d  "
                "window_files=%d  overwrites=%d  avg_resp=%.0fms",
                i, len(tickers), n_cached, n_no_data, n_failed, n_skipped,
                n_window_files_written, n_window_overwrites, avg_ms,
            )

    avg_ms = (sum(response_times) / max(1, len(response_times))) * 1000
    print()
    print("=== Insider MSPR Backfill Summary ===")
    print(f"  Attempted:           {n_attempted}")
    print(f"  Successfully cached: {n_cached}  (>= 1 month of MSPR records)")
    print(f"  No data available:   {n_no_data}")
    print(f"  API failures:        {n_failed}")
    print(f"  Skipped (resumable): {n_skipped}")
    print(f"  Window files written:{n_window_files_written}")
    print(f"  Window files repaired (empty→data): {n_window_overwrites}")
    print(f"  Big-window range:    {BIG_WINDOW_FROM} → {BIG_WINDOW_TO}")
    print(f"  Avg response time:   {avg_ms:.0f} ms")
    print(f"  Cache dir:           {cache._dir}")
    print(f"  Big-window dir:      {big_dir}")


if __name__ == "__main__":
    main()
