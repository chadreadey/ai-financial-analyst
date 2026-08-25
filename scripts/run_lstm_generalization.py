#!/usr/bin/env python3
"""
LSTM generalization test.

Trains the LSTM on one universe and tests on unseen stocks from a
different universe. This is the strongest test for whether the model
learns generalizable signal→return relationships vs overfitting to
specific stocks.

Tests:
  1. Train on liquid_10, test on liquid_20-only stocks (10 unseen)
  2. Train on liquid_20, test on liquid_50-only stocks (30 unseen)
  3. Leave-one-out by sector: train excluding one sector, test on it

Usage:
    python scripts/run_lstm_generalization.py
    python scripts/run_lstm_generalization.py --start 2022-01-01
    python scripts/run_lstm_generalization.py --test sector  # sector holdout only
    python scripts/run_lstm_generalization.py --lstm-weight 0.20
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from quant.backtest import (
    BacktestConfig,
    BacktestResult,
    run_backtest,
    load_universe_data,
)
from quant.universe import LIQUID_10, LIQUID_20, LIQUID_50, BENCHMARK, get_universe
from quant.lstm.model import (
    ReturnForecaster,
    LSTMConfig,
    build_features,
    build_target,
)

logger = logging.getLogger(__name__)

# Sector groupings for leave-one-out
SECTORS = {
    "Technology": ["AAPL", "MSFT", "NVDA", "GOOGL", "META"],
    "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK"],
    "Financials": ["JPM", "BAC", "GS", "MS"],
    "Consumer Disc.": ["AMZN", "TSLA", "HD", "NKE", "SBUX"],
    "Consumer Staples": ["PG", "KO", "PEP", "WMT", "COST"],
    "Industrials": ["CAT", "HON", "UPS", "BA", "GE"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
}


def progress(msg: str):
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] {msg}")


def train_lstm(universe_data, train_end, config):
    """Train LSTM on provided universe data up to train_end."""
    cfg = LSTMConfig(
        hidden_size=config.lstm_hidden_size,
        num_layers=config.lstm_num_layers,
        dropout=config.lstm_dropout,
        lookback_days=config.lstm_lookback_days,
        forecast_horizon=config.lstm_forecast_horizon,
        max_epochs=config.lstm_max_epochs,
        patience=config.lstm_patience,
    )

    cutoff = pd.Timestamp(train_end)
    all_feats, all_tgts = [], []

    for ticker, df in universe_data.items():
        if ticker == BENCHMARK:
            continue
        train_df = df[df.index <= cutoff]
        if len(train_df) < 300:
            continue
        all_feats.append(build_features(train_df))
        all_tgts.append(build_target(train_df, horizon=cfg.forecast_horizon))

    if not all_feats:
        return None, {}

    combined_feats = pd.concat(all_feats).sort_index()
    combined_tgt = pd.concat(all_tgts).sort_index()

    forecaster = ReturnForecaster(cfg)
    metrics = forecaster.fit(combined_feats, combined_tgt)
    return forecaster, metrics


def run_test_on_tickers(test_tickers, forecaster, config, universe_data):
    """Run backtest on test_tickers using a pre-trained forecaster."""
    import quant.backtest as bt_module

    bt_module._lstm_forecaster = forecaster

    test_config = BacktestConfig(
        tickers=test_tickers,
        start_date=config.start_date,
        end_date=config.end_date,
        rebalance_freq=config.rebalance_freq,
        enable_lstm=True,
        lstm_weight=config.lstm_weight,
    )

    return run_backtest(test_config, progress_cb=progress)


def test_cross_universe(train_universe, test_tickers, label, config):
    """Train on one universe, test on different stocks."""
    print(f"\n{'=' * 70}")
    print(f"  {label}")
    print(f"  Train: {len(train_universe)} stocks | Test: {len(test_tickers)} unseen stocks")
    print(f"  Test tickers: {test_tickers}")
    print(f"{'=' * 70}")

    api_key = os.getenv("TIINGO_API_KEY", "").strip()

    # Load data for all stocks (train + test + benchmark)
    all_tickers = list(set(train_universe + test_tickers + [BENCHMARK]))
    progress(f"Loading data for {len(all_tickers)} tickers...")
    universe_data = load_universe_data(all_tickers, config.start_date, api_key, progress)

    # Determine train end (70% of date range)
    all_dates = sorted(set().union(*(df.index for df in universe_data.values())))
    split_idx = int(len(all_dates) * 0.70)
    train_end = all_dates[split_idx].strftime("%Y-%m-%d")

    # --- Baseline: quant-only on test tickers ---
    progress("Running quant-only baseline on test tickers...")
    baseline_config = BacktestConfig(
        tickers=test_tickers,
        start_date=config.start_date,
        end_date=config.end_date,
        rebalance_freq=config.rebalance_freq,
        enable_lstm=False,
    )
    baseline = run_backtest(baseline_config, progress_cb=progress)

    # --- Train LSTM on train universe only ---
    train_data = {t: df for t, df in universe_data.items() if t in train_universe}
    progress(f"Training LSTM on {len(train_data)} train stocks (up to {train_end})...")
    forecaster, train_metrics = train_lstm(train_data, train_end, config)

    if forecaster is None:
        print("  LSTM training failed!")
        return {"label": label, "error": "training_failed"}

    print(
        f"  Training: {train_metrics.get('epochs')} epochs, "
        f"val_loss={train_metrics.get('val_loss')}, "
        f"device={train_metrics.get('device')}"
    )

    # --- Test on UNSEEN tickers ---
    progress(f"Testing on {len(test_tickers)} unseen stocks...")
    overlay = run_test_on_tickers(test_tickers, forecaster, config, universe_data)

    # --- Print comparison ---
    print(f"\n  {'Metric':<20s} {'Quant-Only':>12s} {'+ LSTM':>12s} {'Delta':>12s}")
    print(f"  {'-' * 58}")

    result = {"label": label, "train_stocks": len(train_universe), "test_stocks": len(test_tickers)}

    for name, b_attr, suffix in [
        ("Sharpe", "sharpe", ""),
        ("Total return", "total_return_pct", "%"),
        ("Max drawdown", "max_drawdown_pct", "%"),
        ("Win rate", "win_rate_pct", "%"),
        ("Alpha vs SPY", "alpha_pct", "%"),
        ("Trades", "total_trades", ""),
    ]:
        bv = getattr(baseline, b_attr, None)
        ov = getattr(overlay, b_attr, None)
        result[b_attr] = {"baseline": bv, "lstm": ov}

        if bv is not None and ov is not None:
            delta = ov - bv
            sign = "+" if delta >= 0 else ""
            print(f"  {name:<20s} {bv:>11}{suffix} {ov:>11}{suffix} {sign}{delta:>10.2f}{suffix}")
        else:
            print(f"  {name:<20s} {'N/A':>12s} {'N/A':>12s}")

    # Verdict
    if baseline.sharpe is not None and overlay.sharpe is not None:
        delta = overlay.sharpe - baseline.sharpe
        if delta >= 0.1:
            verdict = f"GENERALIZES — Sharpe +{delta:.2f} on unseen stocks"
        elif delta >= 0:
            verdict = f"MARGINAL — Sharpe +{delta:.2f} on unseen stocks"
        else:
            verdict = f"DOES NOT GENERALIZE — Sharpe {delta:.2f} on unseen stocks"
        print(f"\n  >> {verdict}")
        result["verdict"] = verdict
        result["sharpe_delta"] = delta

    return result


def main():
    parser = argparse.ArgumentParser(description="LSTM generalization test")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="")
    parser.add_argument("--rebalance", default="monthly", choices=["weekly", "monthly"])
    parser.add_argument("--lstm-weight", type=float, default=0.20)
    parser.add_argument("--hidden-size", type=int, default=64)
    parser.add_argument("--lookback", type=int, default=60)
    parser.add_argument("--max-epochs", type=int, default=100)
    parser.add_argument(
        "--test",
        default="all",
        choices=["all", "cross_universe", "sector"],
        help="Which tests to run",
    )
    parser.add_argument("--output", default="")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = BacktestConfig(
        tickers=[],  # set per test
        start_date=args.start,
        end_date=args.end,
        rebalance_freq=args.rebalance,
        lstm_weight=args.lstm_weight,
        lstm_hidden_size=args.hidden_size,
        lstm_lookback_days=args.lookback,
        lstm_max_epochs=args.max_epochs,
    )

    t0 = time.time()
    all_results = []

    # --- Test 1: Train liquid_10 → test on unseen liquid_20 stocks ---
    if args.test in ("all", "cross_universe"):
        unseen_from_20 = sorted(set(LIQUID_20) - set(LIQUID_10))
        r = test_cross_universe(
            LIQUID_10,
            unseen_from_20,
            "CROSS-UNIVERSE: Train liquid_10 → Test unseen liquid_20",
            config,
        )
        all_results.append(r)

    # --- Test 2: Train liquid_20 → test on unseen liquid_50 stocks ---
    if args.test in ("all", "cross_universe"):
        unseen_from_50 = sorted(set(LIQUID_50) - set(LIQUID_20))
        r = test_cross_universe(
            LIQUID_20,
            unseen_from_50,
            "CROSS-UNIVERSE: Train liquid_20 → Test unseen liquid_50",
            config,
        )
        all_results.append(r)

    # --- Test 3: Leave-one-sector-out ---
    if args.test in ("all", "sector"):
        all_sector_stocks = []
        for stocks in SECTORS.values():
            all_sector_stocks.extend(stocks)

        for sector_name, sector_stocks in SECTORS.items():
            # Only test with stocks that are in our universes
            available_test = [s for s in sector_stocks if s in LIQUID_50]
            available_train = [
                s for s in all_sector_stocks if s not in sector_stocks and s in LIQUID_50
            ]

            if len(available_test) < 2 or len(available_train) < 5:
                continue

            r = test_cross_universe(
                available_train,
                available_test,
                f"SECTOR HOLDOUT: Train without {sector_name} → Test {sector_name}",
                config,
            )
            all_results.append(r)

    # --- Summary ---
    elapsed = time.time() - t0
    print(f"\n{'=' * 70}")
    print(f"  GENERALIZATION SUMMARY")
    print(f"{'=' * 70}")
    print(f"\n  {'Test':<50s} {'Sharpe Delta':>12s} {'Verdict':>15s}")
    print(f"  {'-' * 79}")

    pass_count = 0
    for r in all_results:
        label = r.get("label", "?")[:48]
        delta = r.get("sharpe_delta")
        if delta is not None:
            verdict = "PASS" if delta >= 0 else "FAIL"
            if delta >= 0:
                pass_count += 1
            print(f"  {label:<50s} {delta:>+11.2f} {verdict:>15s}")
        else:
            print(f"  {label:<50s} {'N/A':>12s} {'ERROR':>15s}")

    total = len([r for r in all_results if r.get("sharpe_delta") is not None])
    print(f"\n  Result: {pass_count}/{total} tests passed")
    if total > 0:
        if pass_count == total:
            print("  >> MODEL GENERALIZES WELL — safe to deploy on broader universe")
        elif pass_count >= total * 0.7:
            print("  >> MODEL MOSTLY GENERALIZES — consider training on broader universe")
        else:
            print("  >> MODEL DOES NOT GENERALIZE — train on liquid_50 or add features")

    print(f"\n  Total time: {elapsed:.1f}s")

    output_path = (
        args.output or f"lstm_generalization_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"  Results saved to: {output_path}")


if __name__ == "__main__":
    main()
