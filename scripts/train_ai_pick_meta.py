"""
Phase-4 runner: train the AI-pick meta-model.

Reads runs/candidates/ and runs/ai_picks/, joins them with local price
cache + sector ETFs, builds a per-pick feature matrix, trains an XGBoost
classifier for `beat_sector_21d`, and persists to models/.

Usage:
    python3 scripts/train_ai_pick_meta.py
    python3 scripts/train_ai_pick_meta.py --horizon 21 --test-frac 0.2
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

from quant.ai_pick_meta_model import (  # noqa: E402
    SECTOR_TO_ETF,
    build_training_frame,
    save_model,
    train_meta_model,
)

logger = logging.getLogger(__name__)


DEFAULT_CANDIDATE_DIR = os.path.join(REPO_ROOT, "runs", "candidates")
DEFAULT_AI_PICKS_DIR = os.path.join(REPO_ROOT, "runs", "ai_picks")
DEFAULT_PRICE_CACHE = os.path.join(REPO_ROOT, ".price_cache")
DEFAULT_MODEL_PATH = os.path.join(REPO_ROOT, "models", "ai_pick_meta.pkl")


def _load_json_dir(path: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for fname in sorted(os.listdir(path)):
        if fname.startswith("_") or not fname.endswith(".json"):
            continue
        with open(os.path.join(path, fname)) as fh:
            out[fname[:-5]] = json.load(fh)
    return out


def _load_prices(price_dir: str, tickers: set[str]) -> dict[str, pd.DataFrame]:
    prices: dict[str, pd.DataFrame] = {}
    for t in tickers:
        p = os.path.join(price_dir, f"{t}.csv")
        if not os.path.exists(p):
            continue
        try:
            df = pd.read_csv(p, parse_dates=["date"], index_col="date")
            df.index = df.index.normalize()
            prices[t] = df
        except Exception as exc:
            logger.debug("load %s failed: %s", t, exc)
    return prices


def run(
    candidate_dir: str = DEFAULT_CANDIDATE_DIR,
    ai_picks_dir: str = DEFAULT_AI_PICKS_DIR,
    price_cache: str = DEFAULT_PRICE_CACHE,
    model_path: str = DEFAULT_MODEL_PATH,
    horizon_days: int = 21,
    test_frac: float = 0.2,
    n_estimators: int = 200,
    max_depth: int = 3,
    learning_rate: float = 0.05,
) -> dict:
    candidate_files = _load_json_dir(candidate_dir)
    ai_pick_files = _load_json_dir(ai_picks_dir)
    logger.info(
        "Loaded %d candidate lists and %d AI pick files",
        len(candidate_files),
        len(ai_pick_files),
    )

    all_tickers: set[str] = set(SECTOR_TO_ETF.values())
    for payload in ai_pick_files.values():
        for pk in payload.get("portfolio", {}).get("picks", []):
            all_tickers.add(pk["ticker"])
    prices = _load_prices(price_cache, all_tickers)
    logger.info(
        "Loaded price data for %d/%d tickers (incl. sector ETFs)",
        len(prices),
        len(all_tickers),
    )

    frame = build_training_frame(ai_pick_files, candidate_files, prices, horizon_days=horizon_days)
    logger.info(
        "Built training frame with %d rows over %d unique dates",
        len(frame),
        frame["rebalance_date"].nunique() if "rebalance_date" in frame else 0,
    )

    if len(frame) < 20:
        raise RuntimeError(
            "Not enough usable rows to train — extend candidate/AI-picks history or check sector "
            "ETF availability."
        )

    trained = train_meta_model(
        frame,
        test_frac=test_frac,
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
    )
    save_model(trained, model_path)

    frame_out = os.path.join(os.path.dirname(model_path), "training_frame.csv")
    os.makedirs(os.path.dirname(frame_out), exist_ok=True)
    frame.to_csv(frame_out, index=False)

    logger.info("Meta-model metrics: %s", json.dumps(trained.metrics, indent=2))
    logger.info("Saved model to %s", model_path)

    return {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "n_rows": int(len(frame)),
        "horizon_days": horizon_days,
        "metrics": trained.metrics,
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--candidate-dir", default=DEFAULT_CANDIDATE_DIR)
    p.add_argument("--ai-picks-dir", default=DEFAULT_AI_PICKS_DIR)
    p.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    p.add_argument("--model-path", default=DEFAULT_MODEL_PATH)
    p.add_argument("--horizon", dest="horizon_days", type=int, default=21)
    p.add_argument("--test-frac", type=float, default=0.2)
    p.add_argument("--n-estimators", type=int, default=200)
    p.add_argument("--max-depth", type=int, default=3)
    p.add_argument("--lr", dest="learning_rate", type=float, default=0.05)
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
        model_path=args.model_path,
        horizon_days=args.horizon_days,
        test_frac=args.test_frac,
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
    )


if __name__ == "__main__":
    main()
