#!/usr/bin/env python3
"""
Quant-only backtest CLI.

Runs the technical signal backtest on historical price data — no LLM calls.

Usage:
    # Quick test with 10 stocks, 2 years
    python scripts/run_backtest.py --universe liquid_10 --start 2024-01-01

    # Full backtest with 50 stocks, 10 years
    python scripts/run_backtest.py --universe liquid_50 --start 2016-01-01

    # Walk-forward validation
    python scripts/run_backtest.py --universe liquid_20 --start 2018-01-01 --walk-forward

    # Custom tickers
    python scripts/run_backtest.py --tickers AAPL,MSFT,GOOGL,AMZN,JPM --start 2020-01-01

    # Weekly rebalance with tighter thresholds
    python scripts/run_backtest.py --universe liquid_20 --rebalance weekly --long-threshold 0.30
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from quant.backtest import BacktestConfig, run_backtest, run_walk_forward
from quant.universe import get_universe


def progress(msg: str):
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] {msg}")


def print_summary(result):
    """Print a formatted summary of backtest results."""
    print("\n" + "=" * 70)
    print("  QUANT-ONLY BACKTEST RESULTS")
    print("=" * 70)

    if result.error and result.status == "error":
        print(f"\n  ERROR: {result.error}")
        return

    print(f"\n  Status: {result.status}")
    print(f"  Total trades: {result.total_trades}")
    print(f"  Avg holding: {result.avg_holding_days} days")

    print("\n  ── Performance ──────────────────────────────────")
    print(f"  Total return:    {result.total_return_pct:>8.2f}%")
    print(f"  Annual return:   {result.annual_return_pct:>8.2f}%")
    print(f"  Sharpe ratio:    {result.sharpe if result.sharpe else 'N/A':>8}")
    print(f"  Sortino ratio:   {result.sortino if result.sortino else 'N/A':>8}")
    print(f"  Calmar ratio:    {result.calmar if result.calmar else 'N/A':>8}")
    print(f"  Max drawdown:    {result.max_drawdown_pct:>8.2f}%")
    print(f"  Win rate:        {result.win_rate_pct:>8.1f}%")

    print("\n  ── Benchmark (SPY) ─────────────────────────────")
    print(f"  SPY return:      {result.benchmark_return_pct:>8.2f}%")
    if result.benchmark_sharpe:
        print(f"  SPY Sharpe:      {result.benchmark_sharpe:>8}")
    print(f"  Alpha:           {result.alpha_pct:>8.2f}%")

    if result.conviction_bands:
        print("\n  ── Win Rate by Conviction Band ─────────────────")
        for band, stats in sorted(result.conviction_bands.items()):
            print(f"  {band:>25s}: {stats['win_rate_pct']:5.1f}% "
                  f"({stats['n_trades']} trades, avg {stats['avg_return_pct']:+.2f}%)")

    if result.walk_forward:
        print("\n  ── Walk-Forward Windows ────────────────────────")
        for w in result.walk_forward:
            print(f"  {w['test_start']} → {w['test_end']}: "
                  f"{w['return_pct']:+6.2f}% | {w['n_trades']} trades | "
                  f"win {w['win_rate_pct']:.0f}%")

    # Top 5 best and worst trades
    trades = result.trade_log
    if trades:
        sorted_trades = sorted(trades, key=lambda t: t["pnl_pct"], reverse=True)
        print("\n  ── Top 5 Winners ──────────────────────────────")
        for t in sorted_trades[:5]:
            print(f"  {t['ticker']:>6s} {t['direction']:>5s} {t['entry_date']} → {t['exit_date']}: "
                  f"{t['pnl_pct']:+7.2f}% (score={t['composite_score']:.3f})")
        print("\n  ── Top 5 Losers ───────────────────────────────")
        for t in sorted_trades[-5:]:
            print(f"  {t['ticker']:>6s} {t['direction']:>5s} {t['entry_date']} → {t['exit_date']}: "
                  f"{t['pnl_pct']:+7.2f}% (score={t['composite_score']:.3f})")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Quant-only backtest engine")
    parser.add_argument("--universe", default="liquid_10",
                        help="Universe name: liquid_10, liquid_20, liquid_50 (default: liquid_10)")
    parser.add_argument("--tickers", default="",
                        help="Comma-separated tickers (overrides --universe)")
    parser.add_argument("--start", default="2020-01-01",
                        help="Start date YYYY-MM-DD (default: 2020-01-01)")
    parser.add_argument("--end", default="",
                        help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--rebalance", default="monthly", choices=["weekly", "monthly"],
                        help="Rebalance frequency (default: monthly)")
    parser.add_argument("--long-threshold", type=float, default=0.20,
                        help="Composite score threshold for long (default: 0.20)")
    parser.add_argument("--short-threshold", type=float, default=-0.40,
                        help="Composite score threshold for short (default: -0.40)")
    parser.add_argument("--max-positions", type=int, default=10,
                        help="Max positions per side (default: 10)")
    parser.add_argument("--no-regime-filter", action="store_true",
                        help="Disable regime filter entirely (enabled by default)")
    parser.add_argument("--vix-caution", type=float, default=20.0,
                        help="VIX threshold for cautious regime / reduced sizing (default: 20)")
    parser.add_argument("--vix-risk-off", type=float, default=28.0,
                        help="VIX threshold for risk-off / no new longs (default: 28)")
    parser.add_argument("--no-cross-detection", action="store_true",
                        help="Disable death/golden cross detection (enabled by default)")
    parser.add_argument("--short-min-signals", type=int, default=3,
                        help="Min bearish signals (of 5) to allow a short (default: 3)")
    parser.add_argument("--no-shorts", action="store_true",
                        help="Disable short selling entirely (long-only mode)")
    parser.add_argument("--no-ic-calibration", action="store_true",
                        help="Disable IC-based signal weight calibration (enabled by default)")
    parser.add_argument("--ic-shrinkage", type=float, default=0.90,
                        help="IC calibration shrinkage toward equal weights (default: 0.90)")
    parser.add_argument("--enable-news-sentiment", action="store_true",
                        help="Enable Finnhub news sentiment as an additional signal")
    parser.add_argument("--sentiment-weight", type=float, default=0.10,
                        help="Weight for news sentiment signal (default: 0.10)")
    parser.add_argument("--walk-forward", action="store_true",
                        help="Run walk-forward validation instead of single backtest")
    parser.add_argument("--train-months", type=int, default=24,
                        help="Walk-forward train window months (default: 24)")
    parser.add_argument("--test-months", type=int, default=6,
                        help="Walk-forward test window months (default: 6)")
    parser.add_argument("--output", default="",
                        help="Save full results to JSON file")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Build ticker list
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = get_universe(args.universe)

    regime_on = not args.no_regime_filter
    ic_on = not args.no_ic_calibration
    cross_on = not args.no_cross_detection
    print(f"\nQuant Backtest: {len(tickers)} tickers, {args.start} to {args.end or 'today'}")
    print(f"Rebalance: {args.rebalance} | Thresholds: long={args.long_threshold}, short={args.short_threshold}")
    if regime_on:
        print(f"Regime: VIX caution={args.vix_caution}, risk-off={args.vix_risk_off} | "
              f"Cross detect: {'ON' if cross_on else 'OFF'} | Short min signals: {args.short_min_signals}/5")
    else:
        print("Regime filter: OFF")
    print(f"IC calibration: {'ON' if ic_on else 'OFF'} | Shrinkage: {args.ic_shrinkage}")
    if args.walk_forward:
        print(f"Walk-forward: {args.train_months}mo train / {args.test_months}mo test")
    print()

    config = BacktestConfig(
        tickers=tickers,
        start_date=args.start,
        end_date=args.end,
        rebalance_freq=args.rebalance,
        long_threshold=args.long_threshold,
        short_threshold=-999.0 if args.no_shorts else args.short_threshold,
        enable_regime_filter=regime_on,
        vix_caution_threshold=args.vix_caution,
        vix_risk_off_threshold=args.vix_risk_off,
        enable_death_golden_cross=cross_on,
        short_min_bearish_signals=args.short_min_signals,
        enable_ic_calibration=ic_on,
        ic_shrinkage=args.ic_shrinkage,
        max_long_positions=args.max_positions,
        max_short_positions=args.max_positions,
        enable_news_sentiment=args.enable_news_sentiment,
        news_sentiment_weight=args.sentiment_weight,
    )
    if args.walk_forward:
        config.train_months = args.train_months
        config.test_months = args.test_months

    t0 = time.time()

    if args.walk_forward:
        result = run_walk_forward(config, progress_cb=progress)
    else:
        result = run_backtest(config, progress_cb=progress)

    elapsed = time.time() - t0
    print(f"\n  Completed in {elapsed:.1f}s")

    print_summary(result)

    # Save to JSON
    if args.output:
        output_path = args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        mode = "wf" if args.walk_forward else "bt"
        output_path = f"backtest_{mode}_{ts}.json"

    with open(output_path, "w") as f:
        json.dump(result.to_dict(), f, indent=2, default=str)
    print(f"\n  Full results saved to: {output_path}")


if __name__ == "__main__":
    main()
