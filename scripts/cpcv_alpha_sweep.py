#!/usr/bin/env python3
"""
CPCV Alpha Decomposition Sweep.

For each hypothesis about negative alpha, sweeps a range of parameter
values and measures alpha, Sharpe, and PBO via CPCV at each point.

Usage:
    python scripts/cpcv_alpha_sweep.py --hypothesis regime
    python scripts/cpcv_alpha_sweep.py --hypothesis threshold
    python scripts/cpcv_alpha_sweep.py --hypothesis universe
    python scripts/cpcv_alpha_sweep.py --hypothesis all
"""

import argparse
import json
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from quant.backtest import BacktestConfig, run_cpcv
from quant.cpcv import make_cpcv_groups
from quant.universe import get_universe


# ── SPY benchmark for alpha computation ──────────────────────────────


def load_spy_group_returns(start_date, end_date, n_groups):
    spy = pd.read_csv(
        Path(__file__).resolve().parent.parent / ".price_cache/SPY.csv",
        parse_dates=["date"],
        index_col="date",
    ).sort_index()
    spy_range = spy[spy.index >= start_date]
    trading_dates = pd.DatetimeIndex(sorted(spy_range.index))
    groups = make_cpcv_groups(start_date, end_date, n_groups, trading_dates)
    group_returns = []
    for s, e in groups:
        g = spy[(spy.index >= s) & (spy.index <= e)]
        if len(g) > 1:
            group_returns.append((float(g.iloc[-1]["close"]) / float(g.iloc[0]["close"]) - 1) * 100)
        else:
            group_returns.append(0)
    return group_returns


def compute_alpha_from_cpcv(cpcv_dict, group_spy_returns):
    details = cpcv_dict.get("combination_details", [])
    if not details:
        return {}
    returns = []
    alphas = []
    for c in details:
        r = c["return_pct"]
        spy_ret = sum(group_spy_returns[gi] for gi in c["test_groups"])
        returns.append(r)
        alphas.append(r - spy_ret)
    arr_r = np.array(returns)
    arr_a = np.array(alphas)
    return {
        "mean_return": round(float(np.mean(arr_r)), 2),
        "mean_alpha": round(float(np.mean(arr_a)), 2),
        "median_alpha": round(float(np.median(arr_a)), 2),
        "pct_positive_alpha": round(float(np.mean(arr_a > 0) * 100), 1),
        "alpha_p5": round(float(np.percentile(arr_a, 5)), 2),
        "alpha_p95": round(float(np.percentile(arr_a, 95)), 2),
    }


# ── Base config (gold standard) ─────────────────────────────────────


def make_base_config(tickers):
    return BacktestConfig(
        tickers=tickers,
        start_date="2020-01-01",
        end_date="",
        rebalance_freq="monthly",
        long_threshold=0.20,
        short_threshold=-999.0,  # no shorts
        enable_regime_filter=True,
        vix_caution_threshold=20.0,
        vix_risk_off_threshold=28.0,
        enable_ic_calibration=False,
        enable_death_golden_cross=True,
    )


N_GROUPS = 10
MAX_COMBOS = 50  # sample for speed; set to 0 for full 252


def progress(msg):
    print(f"    [{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ── Hypothesis 1: Regime filter aggressiveness ───────────────────────


def sweep_regime(tickers, group_spy):
    print("\n" + "=" * 80)
    print("  HYPOTHESIS 1: Regime filter aggressiveness")
    print("  Testing: OFF, soft (25/35), default (20/28), tight (15/22)")
    print("=" * 80)

    configs = [
        ("OFF", {"enable_regime_filter": False}),
        ("VIX 30/40", {"vix_caution_threshold": 30.0, "vix_risk_off_threshold": 40.0}),
        ("VIX 25/35", {"vix_caution_threshold": 25.0, "vix_risk_off_threshold": 35.0}),
        ("VIX 20/28 (gold)", {"vix_caution_threshold": 20.0, "vix_risk_off_threshold": 28.0}),
        ("VIX 18/25", {"vix_caution_threshold": 18.0, "vix_risk_off_threshold": 25.0}),
        ("VIX 15/22", {"vix_caution_threshold": 15.0, "vix_risk_off_threshold": 22.0}),
    ]

    return _run_sweep("regime", configs, tickers, group_spy)


# ── Hypothesis 2: Long threshold too conservative ────────────────────


def sweep_threshold(tickers, group_spy):
    print("\n" + "=" * 80)
    print("  HYPOTHESIS 2: Long entry threshold")
    print("  Testing: 0.05, 0.10, 0.15, 0.20 (gold), 0.25, 0.30")
    print("=" * 80)

    configs = [
        ("thresh=0.05", {"long_threshold": 0.05}),
        ("thresh=0.10", {"long_threshold": 0.10}),
        ("thresh=0.15", {"long_threshold": 0.15}),
        ("thresh=0.20 (gold)", {"long_threshold": 0.20}),
        ("thresh=0.25", {"long_threshold": 0.25}),
        ("thresh=0.30", {"long_threshold": 0.30}),
    ]

    return _run_sweep("threshold", configs, tickers, group_spy)


# ── Hypothesis 3: Universe concentration ─────────────────────────────


def sweep_universe(group_spy):
    print("\n" + "=" * 80)
    print("  HYPOTHESIS 3: Universe concentration")
    print("  Testing: liquid_10, liquid_20, liquid_50")
    print("=" * 80)

    results = []
    for uni_name in ["liquid_10", "liquid_20", "liquid_50"]:
        uni_tickers = get_universe(uni_name)
        print(f"\n  --- {uni_name} ({len(uni_tickers)} tickers) ---")

        config = make_base_config(uni_tickers)
        t0 = time.time()
        cpcv = run_cpcv(
            config,
            n_groups=N_GROUPS,
            max_combinations=MAX_COMBOS or None,
            progress_cb=progress,
        )
        elapsed = time.time() - t0

        alpha_stats = compute_alpha_from_cpcv(cpcv.to_dict(), group_spy)
        row = {
            "name": f"{uni_name} ({len(uni_tickers)})",
            "mean_return": alpha_stats.get("mean_return", 0),
            "mean_alpha": alpha_stats.get("mean_alpha", 0),
            "median_alpha": alpha_stats.get("median_alpha", 0),
            "pct_pos_alpha": alpha_stats.get("pct_positive_alpha", 0),
            "median_sharpe": cpcv.median_oos_sharpe,
            "pbo": round(cpcv.pbo * 100, 1),
            "pct_pos_sharpe": cpcv.pct_positive_oos,
            "elapsed": round(elapsed, 0),
        }
        results.append(row)
        _print_row(row)

    return results


# ── Hypothesis 4: Rebalance frequency ────────────────────────────────


def sweep_rebalance(tickers, group_spy):
    print("\n" + "=" * 80)
    print("  HYPOTHESIS 4: Rebalance frequency")
    print("  Testing: weekly vs monthly")
    print("=" * 80)

    configs = [
        ("weekly", {"rebalance_freq": "weekly"}),
        ("monthly (gold)", {"rebalance_freq": "monthly"}),
    ]

    return _run_sweep("rebalance", configs, tickers, group_spy)


# ── Sweep runner ─────────────────────────────────────────────────────


def _run_sweep(name, configs, tickers, group_spy):
    results = []
    for label, overrides in configs:
        print(f"\n  --- {label} ---")
        config = make_base_config(tickers)
        for k, v in overrides.items():
            setattr(config, k, v)

        t0 = time.time()
        cpcv = run_cpcv(
            config,
            n_groups=N_GROUPS,
            max_combinations=MAX_COMBOS or None,
            progress_cb=progress,
        )
        elapsed = time.time() - t0

        alpha_stats = compute_alpha_from_cpcv(cpcv.to_dict(), group_spy)
        row = {
            "name": label,
            "mean_return": alpha_stats.get("mean_return", 0),
            "mean_alpha": alpha_stats.get("mean_alpha", 0),
            "median_alpha": alpha_stats.get("median_alpha", 0),
            "pct_pos_alpha": alpha_stats.get("pct_positive_alpha", 0),
            "median_sharpe": cpcv.median_oos_sharpe,
            "pbo": round(cpcv.pbo * 100, 1),
            "pct_pos_sharpe": cpcv.pct_positive_oos,
            "elapsed": round(elapsed, 0),
        }
        results.append(row)
        _print_row(row)

    return results


def _print_row(row):
    print(
        f"    Return={row['mean_return']:+.1f}%  Alpha={row['mean_alpha']:+.1f}%  "
        f"Med.Alpha={row['median_alpha']:+.1f}%  α>0={row['pct_pos_alpha']:.0f}%  "
        f"Sharpe={row['median_sharpe']:.2f}  PBO={row['pbo']:.1f}%  "
        f"SR>0={row['pct_pos_sharpe']:.0f}%  ({row['elapsed']:.0f}s)"
    )


def print_comparison_table(all_results):
    print("\n" + "=" * 110)
    print("  SUMMARY: Alpha vs Sharpe vs PBO across all experiments")
    print("=" * 110)
    header = (
        f"{'Config':<25s} {'Return':>8s} {'Alpha':>8s} {'Med.α':>8s} "
        f"{'α>0%':>6s} {'Sharpe':>7s} {'PBO':>6s} {'SR>0%':>6s}"
    )
    print(f"  {header}")
    print(f"  {'-' * 105}")
    for section_name, rows in all_results:
        print(f"\n  [{section_name}]")
        for r in rows:
            line = (
                f"  {r['name']:<25s} {r['mean_return']:>+7.1f}% {r['mean_alpha']:>+7.1f}% "
                f"{r['median_alpha']:>+7.1f}% {r['pct_pos_alpha']:>5.0f}% "
                f"{r['median_sharpe']:>6.2f} {r['pbo']:>5.1f}% {r['pct_pos_sharpe']:>5.0f}%"
            )
            print(line)
    print()


def main():
    parser = argparse.ArgumentParser(description="CPCV Alpha Decomposition Sweep")
    parser.add_argument(
        "--hypothesis",
        default="all",
        choices=["regime", "threshold", "universe", "rebalance", "all"],
        help="Which hypothesis to test (default: all)",
    )
    parser.add_argument(
        "--max-combos",
        type=int,
        default=50,
        help="Max CPCV combinations per test (default: 50; 0=all 252)",
    )
    args = parser.parse_args()

    global MAX_COMBOS
    MAX_COMBOS = args.max_combos

    tickers = get_universe("liquid_10")
    group_spy = load_spy_group_returns("2020-01-01", "2026-04-07", N_GROUPS)

    all_results = []

    if args.hypothesis in ("regime", "all"):
        all_results.append(("Regime Filter", sweep_regime(tickers, group_spy)))
    if args.hypothesis in ("threshold", "all"):
        all_results.append(("Long Threshold", sweep_threshold(tickers, group_spy)))
    if args.hypothesis in ("universe", "all"):
        all_results.append(("Universe Size", sweep_universe(group_spy)))
    if args.hypothesis in ("rebalance", "all"):
        all_results.append(("Rebalance Freq", sweep_rebalance(tickers, group_spy)))

    print_comparison_table(all_results)

    # Save raw results
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    outpath = f"backtests/cpcv_alpha_sweep_{ts}.json"
    with open(outpath, "w") as f:
        json.dump({name: rows for name, rows in all_results}, f, indent=2)
    print(f"  Results saved to: {outpath}")


if __name__ == "__main__":
    main()
