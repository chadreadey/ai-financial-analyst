#!/usr/bin/env python3
"""
Phase 0 Diagnostic: Full signal validation pipeline.

Runs all four Phase 0 gates in sequence:
  0a — Signal redundancy analysis (correlation + IC)
  0b — CPCV overfitting detection (16 groups, PBO + DSR)
  0c — Fama-French 5-Factor + Momentum alpha attribution
  0d — Summary verdict: is there genuine alpha?

Usage:
    python scripts/run_phase0.py --universe liquid_20 --start 2016-01-01
    python scripts/run_phase0.py --universe liquid_50 --start 2018-01-01 --cpcv-max-combos 500
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import pandas as pd

from quant.backtest import BacktestConfig, run_walk_forward, run_cpcv, load_universe_data
from quant.universe import get_universe, BENCHMARK
from quant.redundancy import (
    compute_signal_correlation_matrix,
    compute_signal_ic_table,
    print_correlation_report,
)
from quant.factor_attribution import (
    load_french_factors,
    run_ff5_momentum_regression,
    rolling_factor_regression,
    equity_curve_to_daily_returns,
    print_rolling_summary,
)


def progress(msg: str):
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] {msg}")


def main():
    parser = argparse.ArgumentParser(description="Phase 0: Signal Validation Diagnostic")
    parser.add_argument("--universe", default="liquid_20", help="Universe (default: liquid_20)")
    parser.add_argument(
        "--tickers", default="", help="Comma-separated tickers (overrides --universe)"
    )
    parser.add_argument("--start", default="2018-01-01", help="Start date (default: 2018-01-01)")
    parser.add_argument("--end", default="", help="End date (default: today)")
    parser.add_argument(
        "--skip-redundancy", action="store_true", help="Skip Phase 0a (redundancy analysis)"
    )
    parser.add_argument("--skip-cpcv", action="store_true", help="Skip Phase 0b (CPCV validation)")
    parser.add_argument(
        "--skip-ff5", action="store_true", help="Skip Phase 0c (factor attribution)"
    )
    parser.add_argument("--n-groups", type=int, default=16, help="CPCV groups (default: 16)")
    parser.add_argument(
        "--cpcv-max-combos", type=int, default=500, help="CPCV max combos (default: 500, 0=all)"
    )
    parser.add_argument(
        "--train-months", type=int, default=24, help="Walk-forward train window (default: 24)"
    )
    parser.add_argument(
        "--test-months", type=int, default=6, help="Walk-forward test window (default: 6)"
    )
    parser.add_argument(
        "--enable-institutional-flow",
        action="store_true",
        help="Enable institutional flow signal (FMP + Finnhub)",
    )
    parser.add_argument(
        "--institutional-flow-weight",
        type=float,
        default=0.15,
        help="Institutional flow signal weight (default: 0.15)",
    )
    parser.add_argument(
        "--enable-xgb-ranker",
        action="store_true",
        help="Use XGBoost ranking instead of linear composite",
    )
    parser.add_argument("--output", default="", help="Save results to JSON")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Suppress noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers
        else get_universe(args.universe)
    )

    end_date = args.end or datetime.now().strftime("%Y-%m-%d")

    print()
    print("*" * 70)
    print("  PHASE 0: SIGNAL VALIDATION DIAGNOSTIC")
    print("*" * 70)
    print(f"  Universe: {len(tickers)} tickers")
    print(f"  Period: {args.start} to {end_date}")
    print(f"  CPCV groups: {args.n_groups}")
    if args.enable_institutional_flow:
        print(f"  Institutional flow: ENABLED (weight={args.institutional_flow_weight})")
    print("*" * 70)

    results = {"timestamp": datetime.now().isoformat(), "universe_size": len(tickers)}
    t0 = time.time()

    # ── Build config for walk-forward ──────────────────────────────────
    config = BacktestConfig(
        tickers=tickers,
        start_date=args.start,
        end_date=end_date,
        rebalance_freq="monthly",
        long_threshold=0.20,
        short_threshold=-0.40,
        enable_regime_filter=True,
        enable_ic_calibration=True,
        max_long_positions=10,
        max_short_positions=10,
        train_months=args.train_months,
        test_months=args.test_months,
        # Phase 0 orthogonal signals: earnings + sentiment + macro regime
        enable_earnings_signals=True,
        earnings_signal_weight=0.30,
        enable_news_sentiment=True,
        news_sentiment_weight=0.10,
        enable_institutional_flow=args.enable_institutional_flow,
        institutional_flow_weight=args.institutional_flow_weight,
        enable_xgb_ranker=args.enable_xgb_ranker,
    )

    # ── Phase 0: Walk-Forward (always runs — needed for 0b and 0c) ────
    print("\n\n  ═══ WALK-FORWARD BACKTEST ═══")
    wf_result = run_walk_forward(config, progress_cb=progress)

    print(f"\n  Walk-Forward Results:")
    print(f"  Total return:  {wf_result.total_return_pct:+.2f}%")
    print(f"  Annual return: {wf_result.annual_return_pct:+.2f}%")
    print(f"  Sharpe:        {wf_result.sharpe}")
    print(f"  Max drawdown:  {wf_result.max_drawdown_pct:.2f}%")
    print(f"  Alpha vs SPY:  {wf_result.alpha_pct:+.2f}%")
    print(f"  Total trades:  {wf_result.total_trades}")
    print(f"  Win rate:      {wf_result.win_rate_pct:.1f}%")

    if wf_result.walk_forward:
        print(f"\n  Windows:")
        for w in wf_result.walk_forward:
            print(
                f"    {w['test_start']} → {w['test_end']}: "
                f"{w['return_pct']:+6.2f}% | {w['n_trades']} trades | "
                f"win {w['win_rate_pct']:.0f}%"
            )

    results["walk_forward"] = {
        "total_return_pct": wf_result.total_return_pct,
        "annual_return_pct": wf_result.annual_return_pct,
        "sharpe": wf_result.sharpe,
        "max_drawdown_pct": wf_result.max_drawdown_pct,
        "alpha_pct": wf_result.alpha_pct,
        "win_rate_pct": wf_result.win_rate_pct,
        "total_trades": wf_result.total_trades,
    }

    # ── Phase 0a: Redundancy Analysis ──────────────────────────────────
    if not args.skip_redundancy:
        print("\n\n  ═══ PHASE 0a: SIGNAL REDUNDANCY ANALYSIS ═══")
        progress("Loading price data for redundancy analysis...")

        # Load price data
        universe_data = load_universe_data(tickers, args.start, progress_cb=progress)
        progress(f"Loaded {len(universe_data)} tickers for redundancy analysis")

        # Generate monthly rebalance dates
        start_ts = pd.Timestamp(args.start)
        end_ts = pd.Timestamp(end_date)
        rebalance_dates = pd.date_range(start_ts, end_ts, freq="ME")

        if len(universe_data) >= 5 and len(rebalance_dates) >= 3:
            mean_corr, std_corr, diag = compute_signal_correlation_matrix(
                universe_data, list(rebalance_dates)
            )
            ic_table = compute_signal_ic_table(universe_data, list(rebalance_dates))
            report = print_correlation_report(mean_corr, std_corr, diag, ic_table)
            print(report)

            results["redundancy"] = {
                "effective_dimensionality": diag.get("effective_dimensionality"),
                "redundant_pairs": diag.get("redundant_pairs", []),
                "eigenvalues": diag.get("eigenvalues", []),
                "n_dates": diag.get("n_dates"),
            }
            if len(ic_table) > 0:
                ic_means = ic_table.mean()
                ic_stds = ic_table.std()
                ic_tstats = ic_means / (ic_stds / (len(ic_table) ** 0.5))
                results["redundancy"]["ic_summary"] = {
                    sig: {
                        "mean_ic": round(float(ic_means[sig]), 4),
                        "t_stat": round(float(ic_tstats[sig]), 2)
                        if not pd.isna(ic_tstats[sig])
                        else 0,
                    }
                    for sig in ic_table.columns
                }
        else:
            print("  Insufficient data for redundancy analysis")

    # ── Phase 0b: CPCV Validation ──────────────────────────────────────
    if not args.skip_cpcv:
        print("\n\n  ═══ PHASE 0b: CPCV OVERFITTING DETECTION ═══")
        progress(f"Running CPCV with {args.n_groups} groups...")

        max_combos = args.cpcv_max_combos if args.cpcv_max_combos > 0 else None
        cpcv_result = run_cpcv(
            config,
            n_groups=args.n_groups,
            n_test_groups=0,  # default: n_groups // 2
            purge_months=1,
            embargo_months=1,
            max_combinations=max_combos,
            progress_cb=progress,
        )
        print(cpcv_result.print_summary())

        # PBO verdict
        print()
        print("*" * 70)
        print(f"  PROBABILITY OF BACKTEST OVERFITTING (PBO): {cpcv_result.pbo:>8.2%}")
        if cpcv_result.pbo > 0.15:
            print("  *** WARNING: PBO > 15% — HIGH RISK OF OVERFITTING ***")
        else:
            print("  PBO is within acceptable range (<= 15%).")
        print("*" * 70)

        results["cpcv"] = {
            "pbo": round(float(cpcv_result.pbo), 4),
            "n_combinations": cpcv_result.n_combinations,
            "n_combinations_completed": cpcv_result.n_combinations_completed,
            "mean_oos_sharpe": round(float(cpcv_result.mean_oos_sharpe), 4),
            "median_oos_sharpe": round(float(cpcv_result.median_oos_sharpe), 4),
            "std_oos_sharpe": round(float(cpcv_result.std_oos_sharpe), 4),
            "pct_positive_oos": round(float(cpcv_result.pct_positive_oos), 4),
            "deflated_sharpe_ratio": round(float(cpcv_result.deflated_sharpe_ratio), 4),
        }

    # ── Phase 0c: Factor Attribution ───────────────────────────────────
    if not args.skip_ff5:
        print("\n\n  ═══ PHASE 0c: FF5 + MOMENTUM FACTOR ATTRIBUTION ═══")

        if not wf_result.equity_curve or len(wf_result.equity_curve) < 60:
            print("  Insufficient equity curve data for factor attribution")
        else:
            progress("Downloading French factor data...")
            try:
                factors = load_french_factors(start_date=args.start)

                progress("Computing daily returns from equity curve...")
                daily_returns = equity_curve_to_daily_returns(wf_result.equity_curve)
                progress(
                    f"Portfolio returns: {len(daily_returns)} days, "
                    f"{daily_returns.index.min().date()} to {daily_returns.index.max().date()}"
                )

                # Full-sample regression
                progress("Running full-sample FF5+Mom regression...")
                ff5_result = run_ff5_momentum_regression(daily_returns, factors)

                if "error" in ff5_result:
                    print(f"  Error: {ff5_result['error']}")
                else:
                    print(ff5_result["summary_text"])

                    results["factor_attribution"] = {
                        "alpha_annual": ff5_result["alpha_annual"],
                        "alpha_t": ff5_result["alpha_t"],
                        "alpha_p": ff5_result["alpha_p"],
                        "alpha_significant": ff5_result["alpha_significant"],
                        "alpha_ci_annual": ff5_result["alpha_ci_annual"],
                        "r_squared": ff5_result["r_squared"],
                        "factor_betas": ff5_result["factor_betas"],
                        "factor_t_stats": ff5_result["factor_t_stats"],
                    }

                    # Rolling regression (only if enough data)
                    if len(daily_returns) >= 252 * 5:  # 5 years minimum
                        progress("Running rolling 60-month regressions...")
                        rolling = rolling_factor_regression(daily_returns, factors)
                        print(print_rolling_summary(rolling))
                    else:
                        print(
                            f"\n  Skipping rolling regression: need 5+ years, have "
                            f"{len(daily_returns) / 252:.1f} years"
                        )

            except Exception as e:
                print(f"  Factor attribution failed: {e}")
                import traceback

                traceback.print_exc()

    # ── Phase 0d: Summary Verdict ──────────────────────────────────────
    elapsed = time.time() - t0
    print("\n")
    print("=" * 70)
    print("  PHASE 0 VERDICT")
    print("=" * 70)

    # Walk-forward
    wf = results.get("walk_forward", {})
    sharpe = wf.get("sharpe")
    alpha = wf.get("alpha_pct", 0)
    print(f"\n  Walk-Forward Sharpe: {sharpe}")
    print(f"  Walk-Forward Alpha vs SPY: {alpha:+.2f}%")

    # Redundancy
    red = results.get("redundancy", {})
    eff_dim = red.get("effective_dimensionality")
    if eff_dim:
        n_redundant = len(red.get("redundant_pairs", []))
        print(f"  Effective dimensionality: {eff_dim} / 6 signals")
        print(f"  Redundant pairs: {n_redundant}")

    # CPCV
    cpcv = results.get("cpcv", {})
    pbo = cpcv.get("pbo")
    if pbo is not None:
        status = "PASS" if pbo <= 0.15 else "FAIL"
        print(f"  CPCV PBO: {pbo:.2%} [{status}]")

    # Factor attribution
    fa = results.get("factor_attribution", {})
    alpha_t = fa.get("alpha_t")
    if alpha_t is not None:
        alpha_ann = fa.get("alpha_annual", 0)
        sig = fa.get("alpha_significant", False)
        hlz = "PASS" if abs(alpha_t) >= 3.0 else "FAIL"
        trad = "PASS" if sig else "FAIL"
        print(f"  FF5+Mom Alpha: {alpha_ann:+.2f}%/yr (t={alpha_t:.2f})")
        print(f"    Traditional (p<0.05): {trad}")
        print(f"    Harvey-Liu-Zhu (t>3): {hlz}")

    # Overall verdict
    print("\n  ── Decision Gate ──")
    if alpha_t is not None and pbo is not None:
        if fa.get("alpha_significant") and pbo <= 0.15:
            print("  >>> Alpha survives factor adjustment AND overfitting test.")
            print("  >>> PROCEED to Phase 1 (fundamental signal integration).")
        elif pbo > 0.15:
            print("  >>> HIGH overfitting risk. Current signal configuration is suspect.")
            print("  >>> STAY in Phase 0: reduce signals, re-test.")
        elif not fa.get("alpha_significant"):
            print("  >>> Alpha does NOT survive FF5+Mom adjustment.")
            print("  >>> PIVOT to Phase 3a: test whether agent veto adds IC.")
        else:
            print("  >>> Mixed results. Review individual gates above.")
    else:
        print("  >>> Some gates were skipped. Re-run without --skip flags for full verdict.")

    print(f"\n  Elapsed: {elapsed:.1f}s")
    print("=" * 70)

    # Save results
    if args.output:
        output_path = args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"phase0_{ts}.json"

    # Remove non-serializable objects
    save_data = json.loads(json.dumps(results, default=str))
    with open(output_path, "w") as f:
        json.dump(save_data, f, indent=2)
    print(f"\n  Results saved to: {output_path}")


if __name__ == "__main__":
    main()
