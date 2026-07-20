#!/usr/bin/env python3
"""
TimesFM overlay backtest.

Runs the quant backtest twice — once without TimesFM (baseline) and once
with TimesFM P50 forecast as a 7th signal — then compares results.

Requires:
  - timesfm package: pip install 'timesfm[torch]'
  - TIINGO_API_KEY in env
  - ENABLE_TIMESFM=true (or uses --force flag)

Usage:
    # Compare quant-only vs quant+TimesFM on 10 stocks
    python scripts/run_timesfm_backtest.py --universe liquid_10 --start 2022-01-01

    # Walk-forward comparison
    python scripts/run_timesfm_backtest.py --universe liquid_10 --start 2020-01-01 --walk-forward

    # Sweep different TimesFM weights
    python scripts/run_timesfm_backtest.py --universe liquid_10 --start 2022-01-01 --sweep-weights

    # Skip baseline (only run TimesFM)
    python scripts/run_timesfm_backtest.py --universe liquid_10 --start 2022-01-01 --skip-baseline
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quant.backtest import BacktestConfig, run_backtest, run_walk_forward, BacktestResult
from quant.universe import get_universe


def progress(msg: str):
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] {msg}")


def print_comparison(baseline: BacktestResult, overlay: BacktestResult, weight: float):
    """Print side-by-side comparison of quant-only vs quant+TimesFM."""
    print("\n" + "=" * 74)
    print("  QUANT-ONLY vs QUANT + TimesFM COMPARISON")
    print(f"  TimesFM weight: {weight:.0%}")
    print("=" * 74)

    def fmt(val, suffix="%", precision=2):
        if val is None:
            return "N/A".rjust(10)
        return f"{val:>{10}.{precision}f}{suffix}"

    rows = [
        ("Total return", baseline.total_return_pct, overlay.total_return_pct, "%"),
        ("Annual return", baseline.annual_return_pct, overlay.annual_return_pct, "%"),
        ("Sharpe", baseline.sharpe, overlay.sharpe, ""),
        ("Sortino", baseline.sortino, overlay.sortino, ""),
        ("Calmar", baseline.calmar, overlay.calmar, ""),
        ("Max drawdown", baseline.max_drawdown_pct, overlay.max_drawdown_pct, "%"),
        ("Win rate", baseline.win_rate_pct, overlay.win_rate_pct, "%"),
        ("Total trades", baseline.total_trades, overlay.total_trades, ""),
        ("Avg holding", baseline.avg_holding_days, overlay.avg_holding_days, " days"),
        ("SPY alpha", baseline.alpha_pct, overlay.alpha_pct, "%"),
    ]

    print(f"\n  {'Metric':<20s} {'Quant-Only':>12s} {'+ TimesFM':>12s} {'Delta':>12s}")
    print("  " + "-" * 58)

    for name, base_val, over_val, suffix in rows:
        if base_val is None or over_val is None:
            delta_str = "N/A".rjust(12)
        else:
            delta = over_val - base_val
            sign = "+" if delta >= 0 else ""
            delta_str = f"{sign}{delta:.2f}{suffix}".rjust(12)

        base_str = f"{base_val}{suffix}" if base_val is not None else "N/A"
        over_str = f"{over_val}{suffix}" if over_val is not None else "N/A"
        print(f"  {name:<20s} {base_str:>12s} {over_str:>12s} {delta_str}")

    # Key verdict
    sharpe_delta = None
    if baseline.sharpe is not None and overlay.sharpe is not None:
        sharpe_delta = overlay.sharpe - baseline.sharpe

    print("\n  ── Verdict ─────────────────────────────────────────")
    if sharpe_delta is not None:
        if sharpe_delta >= 0.1:
            print(f"  TimesFM IMPROVES Sharpe by {sharpe_delta:+.2f} — overlay adds value")
        elif sharpe_delta >= 0:
            print(f"  TimesFM has MARGINAL effect on Sharpe ({sharpe_delta:+.2f})")
        else:
            print(f"  TimesFM HURTS Sharpe by {sharpe_delta:+.2f} — quant-only is better")
    else:
        print("  Insufficient data to compare Sharpe ratios")

    # Walk-forward window comparison
    if baseline.walk_forward and overlay.walk_forward:
        print("\n  ── Walk-Forward Window Comparison ──────────────────")
        print(f"  {'Window':<25s} {'Quant':>10s} {'+ TFM':>10s} {'Delta':>10s}")
        print("  " + "-" * 57)
        for bw, ow in zip(baseline.walk_forward, overlay.walk_forward):
            period = f"{bw['test_start']} → {bw['test_end'][:7]}"
            delta = ow["return_pct"] - bw["return_pct"]
            sign = "+" if delta >= 0 else ""
            print(
                f"  {period:<25s} {bw['return_pct']:>9.2f}% {ow['return_pct']:>9.2f}% {sign}{delta:>8.2f}%"
            )

    print("\n" + "=" * 74)


def run_comparison(config_base: BacktestConfig, walk_forward: bool, weight: float):
    """Run baseline and overlay, return both results."""

    # ── Baseline: quant-only ──
    print("\n--- Phase 1: Quant-Only Baseline ---")
    config_base.enable_timesfm = False

    if walk_forward:
        baseline = run_walk_forward(config_base, progress_cb=progress)
    else:
        baseline = run_backtest(config_base, progress_cb=progress)

    if baseline.status == "error":
        print(f"  Baseline failed: {baseline.error}")
        return baseline, None

    print(f"  Baseline: Sharpe={baseline.sharpe}, Return={baseline.total_return_pct}%")

    # ── Overlay: quant + TimesFM ──
    print("\n--- Phase 2: Quant + TimesFM Overlay ---")
    # Copy all config from baseline, just enable TimesFM overlay
    from dataclasses import asdict

    overlay_kwargs = asdict(config_base)
    overlay_kwargs["enable_timesfm"] = True
    overlay_kwargs["timesfm_weight"] = weight
    config_overlay = BacktestConfig(**overlay_kwargs)

    if walk_forward:
        overlay = run_walk_forward(config_overlay, progress_cb=progress)
    else:
        overlay = run_backtest(config_overlay, progress_cb=progress)

    if overlay.status == "error":
        print(f"  Overlay failed: {overlay.error}")

    return baseline, overlay


def main():
    parser = argparse.ArgumentParser(description="TimesFM overlay backtest comparison")
    parser.add_argument(
        "--universe", default="liquid_10", help="Universe name (default: liquid_10)"
    )
    parser.add_argument(
        "--tickers", default="", help="Comma-separated tickers (overrides --universe)"
    )
    parser.add_argument("--start", default="2022-01-01", help="Start date (default: 2022-01-01)")
    parser.add_argument("--end", default="", help="End date (default: today)")
    parser.add_argument("--rebalance", default="monthly", choices=["weekly", "monthly"])
    parser.add_argument("--walk-forward", action="store_true", help="Use walk-forward validation")
    parser.add_argument(
        "--timesfm-weight",
        type=float,
        default=0.15,
        help="Weight for TimesFM signal (default: 0.15)",
    )
    parser.add_argument(
        "--sweep-weights",
        action="store_true",
        help="Sweep TimesFM weights: 0.05, 0.10, 0.15, 0.20, 0.25",
    )
    parser.add_argument(
        "--skip-baseline", action="store_true", help="Skip baseline, only run TimesFM overlay"
    )
    parser.add_argument("--output", default="", help="Save results to JSON file")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Check time-series model is available (TimesFM preferred, Chronos fallback)
    has_model = False
    try:
        import timesfm  # noqa: F401

        print("TimesFM package: found (preferred)")
        has_model = True
    except ImportError:
        pass
    if not has_model:
        try:
            from chronos import ChronosPipeline  # noqa: F401

            print("Chronos package: found (fallback)")
            has_model = True
        except ImportError:
            pass
    if not has_model:
        print("ERROR: No time-series model installed.")
        print("  Install one of:")
        print("    pip install 'timesfm[torch]'          # preferred, needs Linux + GPU")
        print("    pip install chronos-forecasting torch  # fallback, CPU OK")
        sys.exit(1)

    tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers
        else get_universe(args.universe)
    )

    print(f"\nTimesFM Backtest: {len(tickers)} tickers, {args.start} to {args.end or 'today'}")
    print(f"Rebalance: {args.rebalance}")

    config = BacktestConfig(
        tickers=tickers,
        start_date=args.start,
        end_date=args.end,
        rebalance_freq=args.rebalance,
    )

    t0 = time.time()
    all_results = {}

    if args.sweep_weights:
        # Run baseline once, then sweep weights
        weights = [0.05, 0.10, 0.15, 0.20, 0.25]
        print(f"Sweeping TimesFM weights: {weights}")

        # Baseline
        config.enable_timesfm = False
        print("\n--- Baseline (quant-only) ---")
        if args.walk_forward:
            baseline = run_walk_forward(config, progress_cb=progress)
        else:
            baseline = run_backtest(config, progress_cb=progress)

        print(f"  Baseline Sharpe: {baseline.sharpe}")
        all_results["baseline"] = baseline.to_dict()

        # Sweep
        print("\n--- Weight Sweep ---")
        print(
            f"  {'Weight':>8s} {'Sharpe':>8s} {'Return':>10s} {'Alpha':>10s} {'Win%':>8s} {'Trades':>8s}"
        )
        print("  " + "-" * 56)

        for w in weights:
            config_w = BacktestConfig(
                tickers=tickers,
                start_date=args.start,
                end_date=args.end,
                rebalance_freq=args.rebalance,
                enable_timesfm=True,
                timesfm_weight=w,
                initial_capital=config.initial_capital,
                train_months=config.train_months,
                test_months=config.test_months,
            )
            if args.walk_forward:
                result = run_walk_forward(config_w, progress_cb=progress)
            else:
                result = run_backtest(config_w, progress_cb=progress)

            sharpe_str = f"{result.sharpe:.2f}" if result.sharpe else "N/A"
            print(
                f"  {w:>8.0%} {sharpe_str:>8s} {result.total_return_pct:>9.2f}% "
                f"{result.alpha_pct:>9.2f}% {result.win_rate_pct:>7.1f}% {result.total_trades:>8d}"
            )

            all_results[f"weight_{w:.2f}"] = result.to_dict()

    elif args.skip_baseline:
        # Only run TimesFM overlay
        config.enable_timesfm = True
        config.timesfm_weight = args.timesfm_weight
        print(f"\n--- TimesFM Only (weight={args.timesfm_weight}) ---")
        if args.walk_forward:
            overlay = run_walk_forward(config, progress_cb=progress)
        else:
            overlay = run_backtest(config, progress_cb=progress)

        all_results["overlay"] = overlay.to_dict()
        print(
            f"\n  Sharpe: {overlay.sharpe}, Return: {overlay.total_return_pct}%, "
            f"Alpha: {overlay.alpha_pct}%"
        )

    else:
        # Standard A/B comparison
        baseline, overlay = run_comparison(config, args.walk_forward, args.timesfm_weight)
        if baseline:
            all_results["baseline"] = baseline.to_dict()
        if overlay:
            all_results["overlay"] = overlay.to_dict()
            print_comparison(baseline, overlay, args.timesfm_weight)

    elapsed = time.time() - t0
    print(f"\n  Total time: {elapsed:.1f}s")

    # Save
    output_path = args.output or f"backtest_timesfm_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"  Results saved to: {output_path}")


if __name__ == "__main__":
    main()
