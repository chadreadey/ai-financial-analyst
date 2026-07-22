"""
Phase-3 runner: SPY vs Quant-only vs AI-augmented eval + attribution report.

Reads:
    runs/candidates/*.json    (Phase 1)
    runs/ai_picks/*.json      (Phase 2)
    .price_cache/{ticker}.csv (existing local cache)

Writes:
    docs/eval/three_series/latest.json     (metrics + attribution)
    docs/eval/three_series/latest.md       (human-readable report)
    docs/eval/three_series/daily_returns.csv (wide dataframe of all 3 series)

Usage:
    python3 scripts/run_three_series_eval.py
    python3 scripts/run_three_series_eval.py --n-positions 10 --max-per-sector 4
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from quant.three_series_eval import (  # noqa: E402
    attribution,
    build_series,
    build_spy_series,
    format_markdown_report,
    portfolios_from_ai_picks,
    portfolios_from_candidate_lists,
)

logger = logging.getLogger(__name__)


DEFAULT_CANDIDATE_DIR = os.path.join(REPO_ROOT, "runs", "candidates")
DEFAULT_AI_PICKS_DIR = os.path.join(REPO_ROOT, "runs", "ai_picks")
DEFAULT_PRICE_CACHE = os.path.join(REPO_ROOT, ".price_cache")
DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, "docs", "eval", "three_series")


def _load_json_dir(path: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for fname in sorted(os.listdir(path)):
        if fname.startswith("_") or not fname.endswith(".json"):
            continue
        with open(os.path.join(path, fname)) as fh:
            out[fname[:-5]] = json.load(fh)
    return out


def _load_price_cache(price_dir: str, tickers: set[str]) -> dict[str, pd.DataFrame]:
    prices: dict[str, pd.DataFrame] = {}
    for t in tickers:
        path = os.path.join(price_dir, f"{t}.csv")
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_csv(path, parse_dates=["date"], index_col="date")
            df.index = df.index.normalize()
            prices[t] = df
        except Exception as exc:
            logger.debug("price load failed for %s: %s", t, exc)
    return prices


def _all_tickers(
    candidate_files: dict[str, dict],
    ai_pick_files: dict[str, dict],
) -> set[str]:
    tickers: set[str] = {"SPY"}
    for payload in candidate_files.values():
        for c in payload.get("candidates", []):
            tickers.add(c["ticker"])
    for payload in ai_pick_files.values():
        for p in payload.get("portfolio", {}).get("picks", []):
            tickers.add(p["ticker"])
    return tickers


def run(
    candidate_dir: str = DEFAULT_CANDIDATE_DIR,
    ai_picks_dir: str = DEFAULT_AI_PICKS_DIR,
    price_cache: str = DEFAULT_PRICE_CACHE,
    out_dir: str = DEFAULT_OUT_DIR,
    n_positions: int = 10,
    max_per_sector: int = 4,
) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    candidate_files = _load_json_dir(candidate_dir)
    ai_pick_files = _load_json_dir(ai_picks_dir)
    logger.info(
        "Loaded %d candidate lists and %d AI pick files",
        len(candidate_files),
        len(ai_pick_files),
    )
    if not candidate_files or not ai_pick_files:
        raise RuntimeError("Run Phase 1 (candidates) and Phase 2 (AI picks) first.")

    tickers = _all_tickers(candidate_files, ai_pick_files)
    prices = _load_price_cache(price_cache, tickers)
    logger.info("Loaded price data for %d/%d tickers", len(prices), len(tickers))

    quant_ports = portfolios_from_candidate_lists(
        candidate_files, n_positions=n_positions, max_per_sector=max_per_sector
    )
    ai_ports = portfolios_from_ai_picks(ai_pick_files)

    all_dates = sorted(set(quant_ports.keys()) | set(ai_ports.keys()))
    if not all_dates:
        raise RuntimeError("No rebalance dates found in candidate/AI pick files")
    start = all_dates[0]

    # Shared end date so all three series cover the same window.
    # Cap the final holding period at min(last_rebalance + monthly_horizon,
    # SPY last date) — otherwise the portfolio series runs to end-of-price-
    # cache (unbounded) while SPY is truncated, silently inflating one side.
    spy_df = prices.get("SPY")
    if spy_df is None:
        raise RuntimeError("SPY not in price cache — cannot build benchmark")

    monthly_horizon_days = 30
    natural_end = all_dates[-1] + pd.Timedelta(days=monthly_horizon_days)
    end = min(natural_end, pd.Timestamp(spy_df.index[-1]))

    quant = build_series("Quant-only", quant_ports, prices, end_date=end)
    ai = build_series("AI-augmented", ai_ports, prices, end_date=end)
    spy = build_spy_series(spy_df, start, end)

    attr = attribution(ai, quant, spy)
    md = format_markdown_report(spy, quant, ai, attr)

    payload = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "config": {
            "n_positions": n_positions,
            "max_per_sector": max_per_sector,
        },
        "series": {
            "SPY": spy.metrics,
            "Quant-only": quant.metrics,
            "AI-augmented": ai.metrics,
        },
        "attribution": attr,
    }

    with open(os.path.join(out_dir, "latest.json"), "w") as fh:
        json.dump(payload, fh, indent=2)
    with open(os.path.join(out_dir, "latest.md"), "w") as fh:
        fh.write(md)

    df = pd.DataFrame(
        {
            "SPY": spy.daily_returns,
            "Quant-only": quant.daily_returns,
            "AI-augmented": ai.daily_returns,
        }
    )
    df.to_csv(os.path.join(out_dir, "daily_returns.csv"))

    logger.info("Wrote report to %s", out_dir)
    logger.info("SPY: %s", spy.metrics)
    logger.info("Quant-only: %s", quant.metrics)
    logger.info("AI-augmented: %s", ai.metrics)
    return payload


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--candidate-dir", default=DEFAULT_CANDIDATE_DIR)
    p.add_argument("--ai-picks-dir", default=DEFAULT_AI_PICKS_DIR)
    p.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    p.add_argument("--n-positions", type=int, default=10)
    p.add_argument("--max-per-sector", type=int, default=4)
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run(
        candidate_dir=args.candidate_dir,
        ai_picks_dir=args.ai_picks_dir,
        price_cache=args.price_cache,
        out_dir=args.out_dir,
        n_positions=args.n_positions,
        max_per_sector=args.max_per_sector,
    )


if __name__ == "__main__":
    main()
