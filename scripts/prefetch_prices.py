#!/usr/bin/env python3
"""
Backfill daily OHLCV CSV cache (.price_cache/{TICKER}.csv) for the WRDS PIT
universe so the Session 2 audit IC harness covers the full 495-ticker
universe instead of just the 215 in the local price cache.

Strategy:
  - Identify tickers in WRDS PIT (.wrds_pit.db) but missing from .price_cache/.
  - Try Tiingo first (more permissive on rate limits, deeper history).
  - Fall back to Alpaca if Tiingo returns empty.
  - Write CSV with the existing schema: date,close,high,low,open,volume
    using ADJUSTED prices (so dividends + splits are baked in).
  - Resumable: skip tickers already in price_cache.
  - Per-ticker errors are logged and counted; the run never blocks on one
    bad ticker.

Usage:
    python scripts/prefetch_prices.py
    python scripts/prefetch_prices.py --start 2014-01-01 --end 2025-12-31
    python scripts/prefetch_prices.py --tickers AAPL,MSFT --force
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

import pandas as pd

from tiingo_client import TiingoClient
from price_provider import AlpacaClient


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("prefetch_prices")

PRICE_CACHE_DIR = REPO_ROOT / ".price_cache"
WRDS_DB_PATH = REPO_ROOT / ".wrds_pit.db"

# Conservative sleep — Tiingo allows ~100/hr free or much more on paid;
# we hold to ~0.4s between calls to play nice without dragging.
TIINGO_SLEEP = 0.4
ALPACA_SLEEP = 0.35  # 200 req/min ceiling on free tier


def get_wrds_tickers(db_path: Path) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM compustat_quarterly ORDER BY ticker"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_existing_price_tickers(price_dir: Path) -> set[str]:
    if not price_dir.exists():
        return set()
    return {f.replace(".csv", "") for f in os.listdir(price_dir) if f.endswith(".csv")}


def bars_to_dataframe(bars: list[dict]) -> pd.DataFrame:
    """
    Normalize provider response into the existing .price_cache schema:
        index: date (UTC-naive midnight)
        cols:  close, high, low, open, volume   (all ADJUSTED)
    """
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame(bars)
    # Both Tiingo and Alpaca clients populate "date" as ISO 8601 string.
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(None).dt.normalize()
    df = df.sort_values("date").set_index("date")

    out = pd.DataFrame(index=df.index)
    out["close"] = df["adjClose"] if "adjClose" in df.columns else df.get("close")
    out["high"] = df["adjHigh"] if "adjHigh" in df.columns else df.get("high", out["close"])
    out["low"] = df["adjLow"] if "adjLow" in df.columns else df.get("low", out["close"])
    out["open"] = df["adjOpen"] if "adjOpen" in df.columns else df.get("open", out["close"])
    out["volume"] = df["adjVolume"] if "adjVolume" in df.columns else df.get("volume", 0)
    out = out.dropna(subset=["close"])
    return out


def fetch_tiingo(client: TiingoClient, ticker: str, start_date: str) -> list[dict]:
    return client.get_eod_history(ticker, start_date)


def fetch_alpaca(client: AlpacaClient, ticker: str, start_date: str) -> list[dict]:
    return client.get_eod_history(ticker, start_date)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--start", default="2014-01-01")
    p.add_argument("--end", default="2025-12-31",
                   help="Informational only; we fetch everything from --start onwards")
    p.add_argument("--tickers", default="", help="Comma-separated tickers (overrides WRDS universe)")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--force", action="store_true",
                   help="Re-fetch even if .price_cache/{ticker}.csv exists")
    p.add_argument("--no-alpaca-fallback", action="store_true")
    args = p.parse_args()

    tiingo_key = os.getenv("TIINGO_API_KEY", "").strip()
    alpaca_key = os.getenv("ALPACA_API_KEY", "").strip()
    alpaca_secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
    alpaca_feed = os.getenv("ALPACA_DATA_FEED", "iex").lower().strip()

    if not tiingo_key:
        logger.error("TIINGO_API_KEY is not set in environment / .env — aborting")
        sys.exit(2)

    tiingo = TiingoClient(tiingo_key)
    alpaca = None
    if alpaca_key and alpaca_secret and not args.no_alpaca_fallback:
        alpaca = AlpacaClient(alpaca_key, alpaca_secret, feed=alpaca_feed)
        logger.info("Alpaca fallback enabled (feed=%s)", alpaca_feed)
    else:
        logger.info("Alpaca fallback DISABLED (no creds or --no-alpaca-fallback)")

    # ── Universe selection ─────────────────────────────────────────────
    if args.tickers:
        wanted = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        existing = set() if args.force else get_existing_price_tickers(PRICE_CACHE_DIR)
        missing = [t for t in wanted if t not in existing]
    else:
        wrds = get_wrds_tickers(WRDS_DB_PATH)
        existing = set() if args.force else get_existing_price_tickers(PRICE_CACHE_DIR)
        missing = sorted(set(wrds) - existing)

    if args.limit:
        missing = missing[: args.limit]

    PRICE_CACHE_DIR.mkdir(exist_ok=True)
    logger.info(
        "Targets=%d  cache_dir=%s  start=%s",
        len(missing), PRICE_CACHE_DIR, args.start,
    )

    n_attempted = 0
    n_tiingo_ok = 0
    n_alpaca_ok = 0
    n_failed = 0  # both providers returned nothing
    fail_reasons: dict[str, list[str]] = {
        "no_data_both_providers": [],
        "tiingo_error": [],
        "alpaca_error": [],
    }
    response_times: list[float] = []

    for i, ticker in enumerate(missing, 1):
        n_attempted += 1
        bars: list[dict] = []
        provider_used = ""

        # ── Tiingo first ─────────────────────────────────────────────
        t0 = time.time()
        try:
            bars = fetch_tiingo(tiingo, ticker, args.start)
        except Exception as exc:
            fail_reasons["tiingo_error"].append(f"{ticker}:{exc}")
            bars = []
        response_times.append(time.time() - t0)
        if bars:
            provider_used = "tiingo"
        time.sleep(TIINGO_SLEEP)

        # ── Alpaca fallback ──────────────────────────────────────────
        if not bars and alpaca is not None:
            try:
                bars = fetch_alpaca(alpaca, ticker, args.start)
            except Exception as exc:
                fail_reasons["alpaca_error"].append(f"{ticker}:{exc}")
                bars = []
            time.sleep(ALPACA_SLEEP)
            if bars:
                provider_used = "alpaca"

        if not bars:
            n_failed += 1
            fail_reasons["no_data_both_providers"].append(ticker)
            if i % 25 == 0 or i == len(missing):
                _log_progress(
                    i, len(missing), n_tiingo_ok, n_alpaca_ok, n_failed, response_times,
                )
            continue

        # ── Persist CSV ──────────────────────────────────────────────
        try:
            df = bars_to_dataframe(bars)
            if df.empty or len(df) < 30:
                # Treat tiny series as effectively no-data — audit needs ≥ 60d.
                n_failed += 1
                fail_reasons["no_data_both_providers"].append(f"{ticker} (only {len(df)} rows)")
                continue
            out_path = PRICE_CACHE_DIR / f"{ticker}.csv"
            df.to_csv(out_path)
            if provider_used == "tiingo":
                n_tiingo_ok += 1
            else:
                n_alpaca_ok += 1
        except Exception as exc:
            logger.warning("write failed for %s: %s", ticker, exc)
            n_failed += 1
            fail_reasons["no_data_both_providers"].append(f"{ticker} (write err: {exc})")

        if i % 25 == 0 or i == len(missing):
            _log_progress(
                i, len(missing), n_tiingo_ok, n_alpaca_ok, n_failed, response_times,
            )

    avg_ms = (sum(response_times) / max(1, len(response_times))) * 1000
    print()
    print("=== Price Backfill Summary ===")
    print(f"  Attempted:                  {n_attempted}")
    print(f"  Successfully via Tiingo:    {n_tiingo_ok}")
    print(f"  Successfully via Alpaca:    {n_alpaca_ok}")
    print(f"  Failed (no data):           {n_failed}")
    print(f"  Avg response time:          {avg_ms:.0f} ms")
    final_count = len(get_existing_price_tickers(PRICE_CACHE_DIR))
    print(f"  .price_cache/ total CSVs:   {final_count}")

    if fail_reasons["no_data_both_providers"]:
        print()
        print("Tickers where both Tiingo and Alpaca returned nothing:")
        for t in fail_reasons["no_data_both_providers"]:
            print(f"  - {t}")
    if fail_reasons["tiingo_error"]:
        print()
        print(f"Tiingo errors ({len(fail_reasons['tiingo_error'])}):")
        for line in fail_reasons["tiingo_error"][:50]:
            print(f"  - {line}")
    if fail_reasons["alpaca_error"]:
        print()
        print(f"Alpaca errors ({len(fail_reasons['alpaca_error'])}):")
        for line in fail_reasons["alpaca_error"][:50]:
            print(f"  - {line}")


def _log_progress(
    i, total, n_tiingo_ok, n_alpaca_ok, n_failed, response_times,
):
    avg_ms = (sum(response_times) / max(1, len(response_times))) * 1000
    logger.info(
        "Progress: %d/%d  tiingo=%d  alpaca=%d  failed=%d  avg=%.0fms",
        i, total, n_tiingo_ok, n_alpaca_ok, n_failed, avg_ms,
    )


if __name__ == "__main__":
    main()
