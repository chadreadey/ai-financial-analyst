"""Backfill `.price_cache/*.csv` with full 2015-01-01 → today history from Tiingo.

Fixes silent-drop bug where 262/495 tickers in the WRDS ∩ price-cache universe
had truncated CSVs (bulk-fetch artifacts starting at 2017-03-27 / 2020-07-27)
that caused the backtest loader to reject them and fall through to Tiingo,
which then rate-limited (HTTP 429) on the free tier.

Prereq: Tiingo Power tier ($30/mo) — free tier will 429 within minutes.

Behaviour:
- Iterates WRDS ∩ .price_cache/*.csv (should be 495 tickers).
- For each, fetches EOD history via direct Tiingo HTTP call so 429 is visible.
- Writes CSV in the same schema as quant/backtest._save_cache (columns
  `close,high,low,open,volume`, indexed by `date`).
- Rate-limit-aware: 0.3s sleep between calls; exponential backoff on 429
  (30s → 60s → 120s → 240s → 300s, cap 5min, up to 5 retries).
- Idempotent: skips tickers whose CSV already covers ≤ 2015-01-08 AND was
  modified in the last hour.
- Writes JSON report to docs/audit/coverage/backfill-YYYY-MM-DDTHHMMSS.json.

Classifications:
- BACKFILL:  data now covers 2015 (post_first ≤ 2015-01-08)
- POST_IPO:  data starts after 2015 (real IPO date)
- NO_DATA:   provider returned nothing
- ERROR:     exception raised
- SKIPPED:   idempotent skip

Usage:
    python scripts/backfill_price_cache.py
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill")

CACHE_DIR = REPO / ".price_cache"
WRDS_DB = REPO / ".wrds_pit.db"
COVERAGE_DIR = REPO / "docs" / "audit" / "coverage"

START_DATE = "2015-01-01"
FRESH_THRESHOLD_DAYS = 7          # CSV covers 2015 if first_date within 7 days
RECENT_MOD_SECONDS = 3600         # skip if modified in last hour
SLEEP_BETWEEN_CALLS = 0.3         # ~3.3 req/sec sustained
BACKOFF_SECONDS = [30, 60, 120, 240, 300]
MAX_RETRIES = len(BACKOFF_SECONDS)


def _load_universe() -> list[str]:
    conn = sqlite3.connect(str(WRDS_DB))
    wrds = {r[0] for r in conn.execute("SELECT DISTINCT ticker FROM compustat_quarterly").fetchall()}
    conn.close()
    cache = {p.stem for p in CACHE_DIR.iterdir() if p.suffix == ".csv"}
    return sorted(wrds & cache)


def _existing_first_date(ticker: str) -> Optional[pd.Timestamp]:
    path = CACHE_DIR / f"{ticker}.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, parse_dates=["date"], index_col="date", nrows=1)
        df.index = df.index.normalize()
        return pd.Timestamp(df.index[0])
    except Exception:
        return None


def _is_recently_fresh(ticker: str) -> bool:
    """Skip if CSV already covers 2015 and was modified in the last hour."""
    path = CACHE_DIR / f"{ticker}.csv"
    if not path.exists():
        return False
    first = _existing_first_date(ticker)
    if first is None:
        return False
    if (first - pd.Timestamp(START_DATE)).days > FRESH_THRESHOLD_DAYS:
        return False
    mtime = path.stat().st_mtime
    return (time.time() - mtime) < RECENT_MOD_SECONDS


def _fetch_from_tiingo(session: requests.Session, ticker: str) -> tuple[str, list[dict]]:
    """Fetch EOD history from Tiingo with 429-aware retry.

    Returns (status, bars) where status is one of:
      "ok"       — got bars (may be empty)
      "no_data"  — HTTP 200 with empty list
      "error"    — non-retryable error
    """
    url = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices"
    params = {"startDate": START_DATE}
    attempt = 0
    while True:
        try:
            resp = session.get(url, params=params, timeout=(5, 30))
            if resp.status_code == 429:
                if attempt >= MAX_RETRIES:
                    logger.error("[%s] 429 rate-limited after %d retries; aborting", ticker, attempt)
                    return "error", []
                wait = BACKOFF_SECONDS[attempt]
                logger.warning("[%s] 429 rate-limited (attempt %d); sleeping %ds", ticker, attempt + 1, wait)
                time.sleep(wait)
                attempt += 1
                continue
            if resp.status_code == 404:
                # Ticker not found on Tiingo — treat as no_data
                return "no_data", []
            resp.raise_for_status()
            bars = resp.json()
            if not isinstance(bars, list) or len(bars) == 0:
                return "no_data", []
            return "ok", bars
        except requests.HTTPError as exc:
            logger.warning("[%s] HTTPError %s", ticker, exc)
            return "error", []
        except requests.RequestException as exc:
            if attempt >= MAX_RETRIES:
                logger.error("[%s] network error after %d retries: %s", ticker, attempt, exc)
                return "error", []
            wait = BACKOFF_SECONDS[attempt]
            logger.warning("[%s] network error (attempt %d): %s; sleeping %ds", ticker, attempt + 1, exc, wait)
            time.sleep(wait)
            attempt += 1


def _bars_to_dataframe(bars: list[dict]) -> pd.DataFrame:
    """Convert Tiingo bars to the OHLCV schema used by quant/backtest._save_cache."""
    df = pd.DataFrame(bars)
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(None).dt.normalize()
    df = df.sort_values("date").set_index("date")
    out = pd.DataFrame(index=df.index)
    out["close"] = df["adjClose"] if "adjClose" in df.columns else df["close"]
    out["high"] = df["adjHigh"] if "adjHigh" in df.columns else df.get("high", out["close"])
    out["low"] = df["adjLow"] if "adjLow" in df.columns else df.get("low", out["close"])
    out["open"] = df["adjOpen"] if "adjOpen" in df.columns else df.get("open", out["close"])
    out["volume"] = df["adjVolume"] if "adjVolume" in df.columns else df.get("volume", 0)
    return out


def main() -> int:
    api_key = os.getenv("TIINGO_API_KEY", "").strip()
    if not api_key:
        logger.error("TIINGO_API_KEY not set")
        return 1

    universe = _load_universe()
    logger.info("Universe (WRDS ∩ price_cache): %d tickers", len(universe))

    COVERAGE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    report_path = COVERAGE_DIR / f"backfill-{ts}.json"

    session = requests.Session()
    session.headers["Authorization"] = f"Token {api_key}"

    counts = {"BACKFILL": 0, "POST_IPO": 0, "NO_DATA": 0, "ERROR": 0, "SKIPPED": 0}
    per_ticker = []
    started = time.time()

    for i, ticker in enumerate(universe, 1):
        old_first = _existing_first_date(ticker)
        old_first_str = str(old_first.date()) if old_first is not None else "none"

        if _is_recently_fresh(ticker):
            counts["SKIPPED"] += 1
            per_ticker.append({
                "ticker": ticker, "status": "SKIPPED",
                "old_first": old_first_str, "new_first": old_first_str,
                "rows": None,
            })
            logger.info("[SKIPPED] %s  already fresh (first=%s, mtime<1h)", ticker, old_first_str)
            continue

        status, bars = _fetch_from_tiingo(session, ticker)

        if status == "error":
            counts["ERROR"] += 1
            per_ticker.append({
                "ticker": ticker, "status": "ERROR",
                "old_first": old_first_str, "new_first": old_first_str, "rows": None,
            })
            logger.info("[ERROR   ] %s  old_first=%s (kept existing)", ticker, old_first_str)
        elif status == "no_data" or not bars:
            counts["NO_DATA"] += 1
            per_ticker.append({
                "ticker": ticker, "status": "NO_DATA",
                "old_first": old_first_str, "new_first": old_first_str, "rows": 0,
            })
            logger.info("[NO_DATA ] %s  provider returned empty", ticker)
        else:
            try:
                df = _bars_to_dataframe(bars)
                out_path = CACHE_DIR / f"{ticker}.csv"
                df.to_csv(out_path)
                new_first = df.index[0]
                new_first_str = str(new_first.date())
                gap_days = (new_first - pd.Timestamp(START_DATE)).days
                if gap_days <= FRESH_THRESHOLD_DAYS:
                    status_label = "BACKFILL"
                else:
                    status_label = "POST_IPO"
                counts[status_label] += 1
                per_ticker.append({
                    "ticker": ticker, "status": status_label,
                    "old_first": old_first_str, "new_first": new_first_str, "rows": len(df),
                })
                logger.info(
                    "[%-8s] %s  old_first=%s → new_first=%s  rows=%d",
                    status_label, ticker, old_first_str, new_first_str, len(df),
                )
            except Exception as exc:
                counts["ERROR"] += 1
                per_ticker.append({
                    "ticker": ticker, "status": "ERROR",
                    "old_first": old_first_str, "new_first": old_first_str,
                    "rows": None, "exception": str(exc),
                })
                logger.error("[ERROR   ] %s  serialization failed: %s", ticker, exc)

        # Progress ping every 25
        if i % 25 == 0:
            elapsed = time.time() - started
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(universe) - i) / rate if rate > 0 else 0
            logger.info("── progress %d/%d  elapsed=%.1fs  rate=%.2f/s  eta=%.0fs",
                        i, len(universe), elapsed, rate, eta)

        time.sleep(SLEEP_BETWEEN_CALLS)

    elapsed = time.time() - started
    report = {
        "run_timestamp": ts,
        "start_date": START_DATE,
        "universe_size": len(universe),
        "elapsed_seconds": round(elapsed, 2),
        "counts": counts,
        "per_ticker": per_ticker,
    }
    report_path.write_text(json.dumps(report, indent=2, default=str))
    logger.info("── SUMMARY ─────────────────────────────")
    logger.info("total:    %d", len(universe))
    logger.info("BACKFILL: %d", counts["BACKFILL"])
    logger.info("POST_IPO: %d", counts["POST_IPO"])
    logger.info("NO_DATA:  %d", counts["NO_DATA"])
    logger.info("ERROR:    %d", counts["ERROR"])
    logger.info("SKIPPED:  %d", counts["SKIPPED"])
    logger.info("elapsed:  %.1fs", elapsed)
    logger.info("report:   %s", report_path.relative_to(REPO))
    return 0 if counts["ERROR"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
