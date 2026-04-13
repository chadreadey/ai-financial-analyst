#!/usr/bin/env python3
"""
XGBoost Meta-Model Test: Build features, train, validate.

Usage:
    python scripts/run_xgb_test.py --universe liquid_50
    python scripts/run_xgb_test.py --universe liquid_50 --train-end 2023-01-01
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import os
import pandas as pd

from quant.universe import get_universe


def progress(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}")


def main():
    parser = argparse.ArgumentParser(description="XGBoost Meta-Model Test")
    parser.add_argument("--universe", default="liquid_50")
    parser.add_argument("--start", default="2014-01-01")
    parser.add_argument("--train-end", default="2023-01-01",
                        help="End of training period (default: 2023-01-01)")
    parser.add_argument("--val-months", type=int, default=12,
                        help="Validation months after train-end (default: 12)")
    parser.add_argument("--rebuild-features", action="store_true",
                        help="Force rebuild feature matrix (skip cache)")
    args = parser.parse_args()

    tickers = get_universe(args.universe)
    feature_path = f".xgb_features_{args.universe}.csv"

    print(f"\n{'='*60}")
    print(f"  XGBOOST META-MODEL TEST")
    print(f"{'='*60}")
    print(f"  Universe: {args.universe} ({len(tickers)} tickers)")
    print(f"  Train: {args.start} to {args.train_end}")
    print(f"  Validation: {args.val_months} months after train-end")

    # ── Phase 1: Build feature matrix ──
    if os.path.exists(feature_path) and not args.rebuild_features:
        progress(f"Loading cached feature matrix from {feature_path}")
        from quant.xgb_features import load_feature_matrix
        fm = load_feature_matrix(feature_path)
        progress(f"Loaded {len(fm)} rows")
    else:
        progress("Building feature matrix (this takes a few minutes)...")

        from quant.backtest import load_universe_data, _fetch_ohlcv, load_vix_data
        from quant.xgb_features import build_feature_matrix, save_feature_matrix

        # Load price data
        universe_data = load_universe_data(tickers, args.start, progress_cb=progress)
        progress(f"Loaded {len(universe_data)} tickers")

        # Load VIX
        vix_df = load_vix_data(args.start)

        # Load sector ETFs
        from quant.backtest import _load_sector_etf_data
        from price_provider import get_price_provider
        provider = get_price_provider()
        sector_etf_data = _load_sector_etf_data(args.start, provider)

        # Init WRDS provider
        wrds_provider = None
        inst_wrds_store = None
        try:
            from quant.wrds_store import WRDSPointInTimeStore
            from quant.fundamental_provider import WRDSFundamentalProvider
            store = WRDSPointInTimeStore()
            if store.summary().get("compustat_quarterly", 0) > 0:
                wrds_provider = WRDSFundamentalProvider(store)
                # Check if 13F data is seeded
                test = store.get_inst_holdings_as_of(tickers[0], "2099-12-31", n_quarters=1)
                if test:
                    inst_wrds_store = store
                    progress("WRDS provider + 13F store initialized")
                else:
                    progress("WRDS provider initialized (no 13F data)")
        except Exception as exc:
            progress(f"WRDS init failed: {exc}")

        # Init Finnhub
        finnhub_client = None
        sentiment_cache = None
        try:
            from finnhub_client import FinnhubClient, SentimentDiskCache
            sentiment_cache = SentimentDiskCache()
            finnhub_key = os.getenv("FINNHUB_API_KEY", "").strip()
            if finnhub_key:
                finnhub_client = FinnhubClient(finnhub_key)
        except Exception:
            pass

        # Generate monthly rebalance dates
        rebalance_dates = list(pd.date_range(args.start, pd.Timestamp.now(), freq="ME"))
        progress(f"Rebalance dates: {len(rebalance_dates)}")

        # Build
        t0 = time.time()
        fm = build_feature_matrix(
            universe_data=universe_data,
            rebalance_dates=rebalance_dates,
            wrds_provider=wrds_provider,
            finnhub_client=finnhub_client,
            sentiment_cache=sentiment_cache,
            inst_wrds_store=inst_wrds_store,
            sector_etf_data=sector_etf_data,
            vix_df=vix_df,
        )
        elapsed = time.time() - t0
        progress(f"Feature matrix built in {elapsed:.1f}s: {len(fm)} rows")

        save_feature_matrix(fm, feature_path)

    # ── Phase 2: Train and validate ──
    print(f"\n{'='*60}")
    print(f"  TRAINING XGBOOST RANKER")
    print(f"{'='*60}")

    from quant.xgb_ranker import train_with_temporal_split

    t0 = time.time()
    model, metrics = train_with_temporal_split(
        fm, train_end_date=args.train_end, val_months=args.val_months,
    )
    elapsed = time.time() - t0

    print(f"\n  Training: {metrics['train_dates']} ({metrics['train_rows']} rows)")
    print(f"  Validation: {metrics['val_dates']} ({metrics['val_rows']} rows)")
    print(f"  Train time: {elapsed:.2f}s")

    print(f"\n  ── Validation Metrics ──")
    print(f"  Spearman IC:           {metrics['spearman_ic']:+.4f} (p={metrics['ic_pval']:.4f})")
    print(f"  Top-decile return:     {metrics['top_decile_return_pct']:+.2f}%")
    print(f"  Bottom-decile return:  {metrics['bottom_decile_return_pct']:+.2f}%")
    print(f"  Long/short spread:     {metrics['long_short_spread_pct']:+.2f}%")

    print(f"\n  ── Feature Importance (gain-based) ──")
    imp = metrics["feature_importance"]
    for feat, weight in sorted(imp.items(), key=lambda x: -x[1]):
        bar = "█" * int(weight * 40)
        print(f"    {feat:>12s}: {weight:5.1%} {bar}")

    # ── Quick linear comparison ──
    print(f"\n  ── Linear Blend Comparison ──")
    from scipy.stats import spearmanr

    fm_copy = fm.copy()
    fm_copy["date"] = pd.to_datetime(fm_copy["date"])
    train_end = pd.Timestamp(args.train_end)
    val_end = train_end + pd.DateOffset(months=args.val_months)
    val = fm_copy[(fm_copy["date"] > train_end) & (fm_copy["date"] <= val_end)]

    if len(val) > 0:
        # Equal-weight linear composite
        signal_cols = ["obv_trend", "earnings", "inst_flow", "sentiment",
                       "quality", "price_mom", "insider"]
        linear_score = val[signal_cols].mean(axis=1)
        linear_ic, _ = spearmanr(linear_score, val["fwd_21d_return"])

        # XGB score
        from quant.xgb_ranker import FEATURE_COLS
        xgb_score = model.predict(val[FEATURE_COLS])
        xgb_ic, _ = spearmanr(xgb_score, val["fwd_21d_return"])

        print(f"  Linear equal-weight IC: {linear_ic:+.4f}")
        print(f"  XGBoost IC:             {xgb_ic:+.4f}")
        print(f"  Improvement:            {(xgb_ic - linear_ic):+.4f}")

    print(f"\n{'='*60}")
    print(f"  DONE")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
