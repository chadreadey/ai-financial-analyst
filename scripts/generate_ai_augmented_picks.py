"""
Phase-2 deliverable: generate AI-augmented pick lists for historical rebalances.

Reads:
    runs/candidates/YYYY-MM-DD.json     (from Phase 1)

For each date, runs the Portfolio Construction agent (heuristic by default,
LLM with --live) to pick 10 from the top-50 candidate list. Writes:
    runs/ai_picks/YYYY-MM-DD.json
    runs/ai_picks/_manifest.json

Modes:
    --mode heuristic   (default; deterministic top-N with sector caps)
    --mode llm         (real LLM PC-agent call per rebalance)

Usage:
    python3 scripts/generate_ai_augmented_picks.py
    python3 scripts/generate_ai_augmented_picks.py --mode llm --limit-dates 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from agents.portfolio_construction import (  # noqa: E402
    PortfolioConstructionAgent,
    select_deterministic,
)

logger = logging.getLogger(__name__)

DEFAULT_CANDIDATE_DIR = os.path.join(REPO_ROOT, "runs", "candidates")
DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, "runs", "ai_picks")


def _load_candidate_dates(candidate_dir: str) -> list[str]:
    dates: list[str] = []
    for fname in sorted(os.listdir(candidate_dir)):
        if fname.startswith("_") or not fname.endswith(".json"):
            continue
        dates.append(fname[:-5])
    return dates


async def _run_llm_selection(
    agent: PortfolioConstructionAgent,
    candidates: list[dict],
):
    return await agent.select(candidates)


def _run_one(
    date_str: str,
    candidate_dir: str,
    out_dir: str,
    mode: str,
    n_positions: int,
    max_per_sector: int,
    min_composite: float,
    llm_agent: "PortfolioConstructionAgent | None",
) -> dict:
    with open(os.path.join(candidate_dir, f"{date_str}.json")) as fh:
        payload = json.load(fh)

    candidates = payload.get("candidates", [])

    if mode == "llm" and llm_agent is not None:
        portfolio = asyncio.run(_run_llm_selection(llm_agent, candidates))
    else:
        portfolio = select_deterministic(
            candidates,
            n_positions=n_positions,
            max_per_sector=max_per_sector,
            min_composite=min_composite,
        )

    out = {
        "rebalance_date": date_str,
        "n_candidates": len(candidates),
        "portfolio": portfolio.to_dict(),
        "config": {
            "mode": mode,
            "n_positions": n_positions,
            "max_per_sector": max_per_sector,
            "min_composite": min_composite,
        },
    }
    with open(os.path.join(out_dir, f"{date_str}.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    return out


def generate_ai_augmented_picks(
    candidate_dir: str = DEFAULT_CANDIDATE_DIR,
    out_dir: str = DEFAULT_OUT_DIR,
    mode: str = "heuristic",
    n_positions: int = 10,
    max_per_sector: int = 4,
    min_composite: float = 0.0,
    limit_dates: int | None = None,
) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    dates = _load_candidate_dates(candidate_dir)
    if limit_dates:
        dates = dates[:limit_dates]

    llm_agent: "PortfolioConstructionAgent | None" = None
    if mode == "llm":
        llm_agent = PortfolioConstructionAgent(
            n_positions=n_positions,
            max_per_sector=max_per_sector,
            min_composite=min_composite,
        )

    manifest = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "mode": mode,
        "n_positions": n_positions,
        "max_per_sector": max_per_sector,
        "min_composite": min_composite,
        "dates": [],
    }

    for i, d in enumerate(dates):
        t0 = time.time()
        try:
            out = _run_one(
                d,
                candidate_dir,
                out_dir,
                mode=mode,
                n_positions=n_positions,
                max_per_sector=max_per_sector,
                min_composite=min_composite,
                llm_agent=llm_agent,
            )
        except Exception as exc:
            logger.error("[%d/%d] %s FAILED: %s", i + 1, len(dates), d, exc)
            continue
        manifest["dates"].append(d)
        picks_str = ", ".join(p["ticker"] for p in out["portfolio"]["picks"])
        logger.info(
            "[%d/%d] %s (%s): %s cash=%.2f in %.2fs",
            i + 1,
            len(dates),
            d,
            out["portfolio"]["source"],
            picks_str,
            out["portfolio"]["cash_weight"],
            time.time() - t0,
        )

    with open(os.path.join(out_dir, "_manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    logger.info("Wrote %d AI-augmented pick files to %s", len(manifest["dates"]), out_dir)
    return manifest


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--candidate-dir", default=DEFAULT_CANDIDATE_DIR)
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    p.add_argument("--mode", choices=["heuristic", "llm"], default="heuristic")
    p.add_argument("--n-positions", type=int, default=10)
    p.add_argument("--max-per-sector", type=int, default=4)
    p.add_argument("--min-composite", type=float, default=0.0)
    p.add_argument("--limit-dates", type=int, default=None)
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    generate_ai_augmented_picks(
        candidate_dir=args.candidate_dir,
        out_dir=args.out_dir,
        mode=args.mode,
        n_positions=args.n_positions,
        max_per_sector=args.max_per_sector,
        min_composite=args.min_composite,
        limit_dates=args.limit_dates,
    )


if __name__ == "__main__":
    main()
