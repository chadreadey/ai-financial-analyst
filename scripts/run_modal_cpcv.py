#!/usr/bin/env python
"""Run CPCV via Modal (or locally) from the command line.

Examples:

  # Smoke (local, 3 combos, 5 tickers; no Modal):
  python scripts/run_modal_cpcv.py --smoke --local

  # Smoke on Modal (exercises full fan-out with tiny parameters):
  python scripts/run_modal_cpcv.py --smoke

  # 500-combo sweep on LIQUID_50 via Modal:
  python scripts/run_modal_cpcv.py \
      --universe liquid_50 --n-groups 16 --n-test 8 --max-combos 500

  # Same, locally (slow — ~hours — useful to compare numerical parity):
  python scripts/run_modal_cpcv.py --universe liquid_50 --n-groups 5 --n-test 2 --local
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env", override=False)
except ImportError:
    pass

logger = logging.getLogger("run_modal_cpcv")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--smoke", action="store_true", help="Tiny preset: 5 tickers, 5 groups, 2 test, 3 combos."
    )
    p.add_argument(
        "--universe", default="liquid_50", help="Named universe (liquid_10, liquid_50, liquid_100)."
    )
    p.add_argument("--start-date", default="2018-01-01")
    p.add_argument("--end-date", default="")
    p.add_argument("--n-groups", type=int, default=16)
    p.add_argument("--n-test", type=int, default=8)
    p.add_argument("--purge-months", type=int, default=1)
    p.add_argument("--embargo-months", type=int, default=1)
    p.add_argument(
        "--max-combos",
        type=int,
        default=None,
        help="Sample this many combos (deterministic seed=42). Default: run all.",
    )
    p.add_argument(
        "--local", action="store_true", help="Run in-process (no Modal). Useful for debugging."
    )
    p.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Permit dirty git tree (stamps run git_sha with '-dirty-<ts>').",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Save summary JSON here (default: runs/<run_id>.json).",
    )
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def _apply_smoke_preset(args: argparse.Namespace) -> argparse.Namespace:
    args.universe = "custom_smoke"
    args.n_groups = 5
    args.n_test = 2
    args.max_combos = 3
    args.start_date = "2023-01-01"
    args.end_date = "2024-06-01"
    return args


def _resolve_universe(name: str) -> list[str]:
    if name == "custom_smoke":
        return ["AAPL", "MSFT", "GOOGL", "AMZN", "JPM"]
    from quant.universe import get_universe

    return get_universe(name)


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
    )
    if args.smoke:
        args = _apply_smoke_preset(args)

    from quant.backtest import BacktestConfig

    tickers = _resolve_universe(args.universe)
    logger.info("Universe %r → %d tickers", args.universe, len(tickers))

    cfg = BacktestConfig(
        tickers=tickers,
        start_date=args.start_date,
        end_date=args.end_date,
        enable_regime_filter=False if args.smoke else True,
        enable_ic_calibration=False if args.smoke else True,
    )

    from modal_app.dispatcher import dispatch_cpcv
    from quant.git_sha import DirtyTreeError

    t0 = time.time()
    try:
        summary = dispatch_cpcv(
            cfg,
            n_groups=args.n_groups,
            n_test_groups=args.n_test,
            purge_months=args.purge_months,
            embargo_months=args.embargo_months,
            max_combos=args.max_combos,
            allow_dirty=args.allow_dirty,
            local=args.local,
        )
    except DirtyTreeError as exc:
        logger.error("%s", exc)
        logger.error("Tip: pass --allow-dirty if you understand the tradeoff.")
        return 2

    elapsed = time.time() - t0
    logger.info("total wall clock: %.1fs", elapsed)

    out_path = args.output or (Path("runs") / f"{summary['run_id']}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    logger.info("summary → %s", out_path)

    return 0 if summary.get("status") == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
