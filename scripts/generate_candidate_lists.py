"""
Phase-1 deliverable: generate historical candidate lists.

For each monthly rebalance in the requested window, compute the screener
composite over the IC-validated survivors (QMJ / SUE / ERM) and persist
the top-N candidates. These lists feed Phase 2 (agents choose 10 from 50).

Reuses `scripts/run_audit_ic.compute_signal_panel` so the raw signal values
are identical to what the IC audit measured.

Output:
    runs/candidates/YYYY-MM-DD.json     — one file per rebalance
    runs/candidates/_manifest.json      — list of dates + universe metadata

Usage:
    python3 scripts/generate_candidate_lists.py --start 2018-01-01 --end 2024-12-31
    python3 scripts/generate_candidate_lists.py --start 2022-01-01 --end 2024-12-31 --top-n 50
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from quant.screener import (  # noqa: E402
    SCREENER_WEIGHTS,
    candidates_to_dict,
    select_candidates_from_panel,
)
from quant.wrds_store import WRDSPointInTimeStore  # noqa: E402
from quant.fundamental_provider import WRDSFundamentalProvider  # noqa: E402
from scripts.run_audit_ic import (  # noqa: E402
    WRDS_DB_PATH,
    compute_signal_panel,
    get_wrds_universe,
    load_universe_prices,
)

logger = logging.getLogger(__name__)

DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, "runs", "candidates")


def _month_end_rebalance_dates(start: str, end: str) -> list[pd.Timestamp]:
    """Monthly rebalance dates (last business day of each month)."""
    idx = pd.date_range(start=start, end=end, freq="BME")
    return list(idx)


def _sector_lookup_wrds() -> dict[str, str]:
    """
    Build a ticker -> GICS sector map from WRDS when the seed carries it.

    Returns an empty dict when the column is absent — callers fall back
    to `quant.universe.get_sector`.
    """
    sectors: dict[str, str] = {}
    try:
        conn = sqlite3.connect(WRDS_DB_PATH)
        try:
            rows = conn.execute(
                "SELECT DISTINCT ticker, gsector FROM compustat_quarterly WHERE gsector IS NOT NULL"
            ).fetchall()
            _GSECTOR_TO_NAME = {
                "10": "Energy",
                "15": "Materials",
                "20": "Industrials",
                "25": "Consumer Discretionary",
                "30": "Consumer Staples",
                "35": "Health Care",
                "40": "Financials",
                "45": "Information Technology",
                "50": "Communication Services",
                "55": "Utilities",
                "60": "Real Estate",
            }
            for tkr, gs in rows:
                key = str(gs)
                sectors[tkr] = _GSECTOR_TO_NAME.get(key, key)
        except sqlite3.OperationalError:
            pass
        conn.close()
    except Exception as exc:
        logger.debug("WRDS sector lookup failed: %s", exc)
    return sectors


def _make_sector_fn(wrds_sectors: dict[str, str]):
    from quant.universe import get_sector

    def fn(ticker: str) -> str:
        return wrds_sectors.get(ticker) or get_sector(ticker) or "Unknown"

    return fn


def generate_candidate_lists(
    start: str,
    end: str,
    top_n: int = 50,
    max_per_sector: int | None = None,
    limit_tickers: int | None = None,
    out_dir: str = DEFAULT_OUT_DIR,
    limit_dates: int | None = None,
) -> dict:
    os.makedirs(out_dir, exist_ok=True)

    tickers = get_wrds_universe()
    universe = load_universe_prices(tickers)
    universe = {t: df for t, df in universe.items() if len(df) >= 60}
    if limit_tickers:
        universe = dict(list(universe.items())[:limit_tickers])
    logger.info("Loaded price data for %d tickers", len(universe))

    store = WRDSPointInTimeStore(WRDS_DB_PATH)
    provider = WRDSFundamentalProvider(store)

    wrds_sectors = _sector_lookup_wrds()
    sector_fn = _make_sector_fn(wrds_sectors)

    rebalance_dates = _month_end_rebalance_dates(start, end)
    if limit_dates:
        rebalance_dates = rebalance_dates[:limit_dates]

    manifest = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "start": start,
        "end": end,
        "top_n": top_n,
        "max_per_sector": max_per_sector,
        "universe_size": len(universe),
        "screener_weights": SCREENER_WEIGHTS,
        "dates": [],
    }

    for i, reb_date in enumerate(rebalance_dates):
        t0 = time.time()
        panel = compute_signal_panel(universe, reb_date, store, provider)
        if panel is None or panel.empty:
            logger.warning("Skipping %s — empty panel", reb_date.date())
            continue

        keep_cols = [c for c in ("qmj", "sue", "erm") if c in panel.columns]
        panel = panel[keep_cols].dropna(how="all")

        candidates = select_candidates_from_panel(
            panel,
            sector_fn=sector_fn,
            top_n=top_n,
            max_per_sector=max_per_sector,
        )

        payload = {
            "rebalance_date": reb_date.date().isoformat(),
            "universe_size": int(len(panel)),
            "top_n": top_n,
            "screener_weights": SCREENER_WEIGHTS,
            "candidates": candidates_to_dict(candidates),
        }
        out_path = os.path.join(out_dir, f"{reb_date.date().isoformat()}.json")
        with open(out_path, "w") as fh:
            json.dump(payload, fh, indent=2)

        manifest["dates"].append(reb_date.date().isoformat())
        logger.info(
            "[%d/%d] %s: %d candidates (universe=%d) in %.1fs",
            i + 1,
            len(rebalance_dates),
            reb_date.date(),
            len(candidates),
            len(panel),
            time.time() - t0,
        )

    with open(os.path.join(out_dir, "_manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)

    logger.info("Wrote %d candidate lists to %s", len(manifest["dates"]), out_dir)
    return manifest


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default=datetime.utcnow().strftime("%Y-%m-%d"))
    p.add_argument("--top-n", type=int, default=50)
    p.add_argument("--max-per-sector", type=int, default=None)
    p.add_argument("--limit-tickers", type=int, default=None)
    p.add_argument("--limit-dates", type=int, default=None)
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    generate_candidate_lists(
        start=args.start,
        end=args.end,
        top_n=args.top_n,
        max_per_sector=args.max_per_sector,
        limit_tickers=args.limit_tickers,
        limit_dates=args.limit_dates,
        out_dir=args.out_dir,
    )


if __name__ == "__main__":
    main()
