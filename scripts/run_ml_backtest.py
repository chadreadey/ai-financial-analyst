#!/usr/bin/env python3
"""
LSTM overlay backtest.

Runs the quant backtest with an LSTM model as the 7th signal.
The LSTM is trained per walk-forward window on the training data,
then used to generate momentum scores during the test period.

Requires:
  - torch: pip install torch
  - TIINGO_API_KEY in env

Usage:
    # A/B: quant-only vs quant+LSTM (single period)
    python scripts/run_ml_backtest.py --universe liquid_10 --start 2022-01-01

    # Walk-forward with per-window LSTM training
    python scripts/run_ml_backtest.py --universe liquid_10 --start 2020-01-01 --walk-forward

    # Sweep LSTM weights
    python scripts/run_ml_backtest.py --universe liquid_10 --start 2022-01-01 --sweep-weights

    # Custom hyperparameters
    python scripts/run_ml_backtest.py --universe liquid_10 --start 2022-01-01 \\
        --lstm-weight 0.20 --hidden-size 128 --lookback 40
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

from quant.backtest import (
    BacktestConfig, BacktestResult,
    run_backtest, run_walk_forward,
    load_universe_data,
    generate_rebalance_dates,
)
from quant.universe import get_universe, BENCHMARK

logger = logging.getLogger(__name__)


def progress(msg: str):
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] {msg}")


def train_lstm_for_window(
    universe_data: dict,
    train_end: str,
    config: BacktestConfig,
) -> "ReturnForecaster":
    """
    Train an LSTM on all available data up to train_end.
    Returns a fitted ReturnForecaster.
    """
    import pandas as pd
    from quant.lstm.model import (
        ReturnForecaster, LSTMConfig,
        build_features, build_target,
    )

    lstm_config = LSTMConfig(
        hidden_size=config.lstm_hidden_size,
        num_layers=config.lstm_num_layers,
        dropout=config.lstm_dropout,
        lookback_days=config.lstm_lookback_days,
        forecast_horizon=config.lstm_forecast_horizon,
        max_epochs=config.lstm_max_epochs,
        patience=config.lstm_patience,
    )

    # Pool training data from all tickers
    all_features = []
    all_targets = []
    cutoff = pd.Timestamp(train_end)

    for ticker, df in universe_data.items():
        train_df = df[df.index <= cutoff]
        if len(train_df) < 300:  # need enough history
            continue

        feats = build_features(train_df)
        tgt = build_target(train_df, horizon=lstm_config.forecast_horizon)
        # Tag with ticker for debugging, then concat
        all_features.append(feats)
        all_targets.append(tgt)

    if not all_features:
        logger.warning("No tickers had enough data for LSTM training")
        return None

    # Concatenate all tickers' data (the LSTM learns cross-stock patterns)
    combined_feats = pd.concat(all_features, axis=0).sort_index()
    combined_target = pd.concat(all_targets, axis=0).sort_index()

    forecaster = ReturnForecaster(lstm_config)
    metrics = forecaster.fit(combined_feats, combined_target)

    if "error" in metrics:
        logger.warning("LSTM training failed: %s", metrics)
        return None

    return forecaster


def run_lstm_single(config: BacktestConfig) -> BacktestResult:
    """
    Train LSTM on first 70% of data, run backtest on full period with LSTM signal.
    """
    import os
    import pandas as pd
    import quant.backtest as bt_module

    api_key = os.getenv("TIINGO_API_KEY", "").strip()
    all_tickers = list(set(config.tickers + [BENCHMARK]))

    progress("Loading price data...")
    universe_data = load_universe_data(all_tickers, config.start_date, api_key, progress)

    # Use first 70% of the date range for training
    all_dates = sorted(set().union(*(df.index for df in universe_data.values())))
    split_idx = int(len(all_dates) * 0.70)
    train_end = all_dates[split_idx].strftime("%Y-%m-%d")

    progress(f"Training LSTM on data up to {train_end}...")
    forecaster = train_lstm_for_window(universe_data, train_end, config)
    if forecaster is None:
        result = BacktestResult()
        result.status = "error"
        result.error = "LSTM training failed"
        return result

    # Set the global forecaster for the backtest engine
    bt_module._lstm_forecaster = forecaster
    config.enable_lstm = True

    progress("Running backtest with LSTM signal...")
    return run_backtest(config, progress_cb=progress)


def run_lstm_walk_forward(config: BacktestConfig) -> BacktestResult:
    """
    Walk-forward with per-window LSTM training.
    Trains LSTM on each training window, then runs the test window.
    """
    import os
    import pandas as pd
    import numpy as np
    import quant.backtest as bt_module
    from quant.backtest import (
        _compute_daily_portfolio_returns,
        compute_signals_at_date,
        build_target_portfolio,
        detect_regime, RegimeState,
        compute_signal_ic, calibrate_weights_from_ic,
        apply_calibrated_weights,
        blend_lstm_into_signals, compute_lstm_scores,
    )

    api_key = os.getenv("TIINGO_API_KEY", "").strip()
    if not api_key:
        result = BacktestResult()
        result.status = "error"
        result.error = "TIINGO_API_KEY not set"
        return result

    # Load data
    all_tickers = list(set(config.tickers + [BENCHMARK]))
    fetch_start = (pd.Timestamp(config.start_date) - pd.DateOffset(months=config.train_months + 6)).strftime("%Y-%m-%d")

    progress("Loading price data...")
    universe_data = load_universe_data(all_tickers, fetch_start, api_key, progress)

    if len(universe_data) < 3:
        result = BacktestResult()
        result.status = "error"
        result.error = f"Only loaded {len(universe_data)} tickers"
        return result

    benchmark_df = universe_data.pop(BENCHMARK, None)

    # Load VIX
    vix_df = None
    if config.enable_regime_filter:
        from quant.backtest import load_vix_data
        vix_df = load_vix_data(fetch_start)

    # Generate walk-forward windows (rolling: advance by test_months each step)
    from datetime import timedelta
    bt_start = pd.Timestamp(config.start_date)
    bt_end = pd.Timestamp(config.end_date)

    windows = []
    cursor = bt_start
    while True:
        train_end = cursor + timedelta(days=config.train_months * 30)
        test_end = train_end + timedelta(days=config.test_months * 30)
        if test_end > bt_end:
            break
        windows.append({
            "train_start": cursor.strftime("%Y-%m-%d"),
            "train_end": train_end.strftime("%Y-%m-%d"),
            "test_start": train_end.strftime("%Y-%m-%d"),
            "test_end": test_end.strftime("%Y-%m-%d"),
        })
        cursor += timedelta(days=config.test_months * 30)

    progress(f"Walk-forward: {len(windows)} windows, train={config.train_months}mo, test={config.test_months}mo")

    result = BacktestResult()
    result.config = {
        "tickers": config.tickers,
        "enable_lstm": True,
        "lstm_weight": config.lstm_weight,
        "walk_forward": True,
        "train_months": config.train_months,
        "test_months": config.test_months,
    }

    all_daily_pnl = pd.Series(dtype=float)
    all_trades = []
    capital = config.initial_capital
    window_results = []

    for wi, window in enumerate(windows):
        progress(f"Window {wi+1}/{len(windows)}: train {window['train_start']}→{window['train_end']}, "
                 f"test {window['test_start']}→{window['test_end']}")

        # Train LSTM on this window's training data
        progress(f"  Training LSTM...")
        forecaster = train_lstm_for_window(universe_data, window["train_end"], config)

        if forecaster is None:
            progress("  LSTM training failed for this window — skipping")
            window_results.append({
                "test_start": window["test_start"],
                "test_end": window["test_end"],
                "return_pct": 0.0,
                "error": "lstm_training_failed",
            })
            continue

        # Set forecaster for this window
        bt_module._lstm_forecaster = forecaster

        # Generate rebalance dates for test period
        all_dates = sorted(set().union(*(df.index for df in universe_data.values())))
        trading_dates = pd.DatetimeIndex(all_dates)
        test_start = pd.Timestamp(window["test_start"])
        test_end_ts = pd.Timestamp(window["test_end"])

        rebalance_dates = generate_rebalance_dates(
            test_start, test_end_ts, config.rebalance_freq, trading_dates,
        )

        if len(rebalance_dates) < 2:
            window_results.append({
                "test_start": window["test_start"],
                "test_end": window["test_end"],
                "return_pct": 0.0,
                "error": "insufficient_rebalance_dates",
            })
            continue

        # Run rebalance loop for this window
        window_trades = []
        window_pnl = pd.Series(dtype=float)

        for i, reb_date in enumerate(rebalance_dates[:-1]):
            next_reb = rebalance_dates[i + 1]
            signals = compute_signals_at_date(universe_data, reb_date, config.lookback_days)
            if not signals:
                continue

            # Blend LSTM scores
            lstm_scores = compute_lstm_scores(universe_data, reb_date, forecaster)
            if lstm_scores:
                signals = blend_lstm_into_signals(signals, lstm_scores, config.lstm_weight)

            # Regime filter
            if config.enable_regime_filter:
                regime = detect_regime(benchmark_df, reb_date, vix_df=vix_df, config=config)
            else:
                regime = RegimeState(level="unknown")

            positions = build_target_portfolio(
                signals, universe_data, reb_date, config, capital, regime=regime,
            )
            if not positions:
                continue

            trades, period_pnl = _compute_daily_portfolio_returns(
                positions, universe_data, reb_date, next_reb, config,
            )
            window_trades.extend(trades)
            window_pnl = pd.concat([window_pnl, period_pnl])

        # Window results
        window_return = float(window_pnl.sum()) if len(window_pnl) > 0 else 0.0
        window_return_pct = round(window_return / capital * 100, 2)
        capital += window_return

        window_results.append({
            "test_start": window["test_start"],
            "test_end": window["test_end"],
            "return_pct": window_return_pct,
            "trades": len(window_trades),
        })
        all_trades.extend(window_trades)
        all_daily_pnl = pd.concat([all_daily_pnl, window_pnl])

        progress(f"  Window return: {window_return_pct:+.2f}%, trades: {len(window_trades)}")

    # Compute aggregate metrics
    from quant import metrics

    if len(all_daily_pnl) > 0:
        cumulative = config.initial_capital + all_daily_pnl.cumsum()
        final_equity = float(cumulative.iloc[-1])
        result.total_return_pct = round((final_equity / config.initial_capital - 1) * 100, 2)
        result.annual_return_pct = metrics.compute_annual_return(cumulative, config.initial_capital)

        daily_returns = all_daily_pnl / config.initial_capital
        result.sharpe = metrics.compute_sharpe(daily_returns)
        result.sortino = metrics.compute_sortino(daily_returns)

        result.max_drawdown_pct = metrics.compute_max_drawdown(cumulative)
        result.calmar = metrics.compute_calmar(result.annual_return_pct, result.max_drawdown_pct)

        # Benchmark
        if benchmark_df is not None:
            bench = benchmark_df[
                (benchmark_df.index >= cumulative.index[0]) &
                (benchmark_df.index <= cumulative.index[-1])
            ]
            if len(bench) > 10:
                result.benchmark_return_pct = round(
                    (float(bench.iloc[-1]["close"]) / float(bench.iloc[0]["close"]) - 1) * 100, 2
                )
                result.alpha_pct = round(result.total_return_pct - result.benchmark_return_pct, 2)

        # Trade stats
        result.total_trades = len(all_trades)
        if all_trades:
            winners = [t for t in all_trades if t.pnl_pct > 0]
            result.win_rate_pct = round(len(winners) / len(all_trades) * 100, 1)
            result.avg_holding_days = round(
                sum(t.holding_days for t in all_trades) / len(all_trades), 1
            )

        # Equity curve
        result.equity_curve = [
            {"date": str(d.date()), "equity": round(float(v), 2)}
            for d, v in cumulative.items()
        ]

        # Trade log
        result.trade_log = [
            {
                "ticker": t.ticker, "direction": t.direction,
                "entry_date": t.entry_date, "entry_price": t.entry_price,
                "exit_date": t.exit_date, "exit_price": t.exit_price,
                "pnl_pct": t.pnl_pct, "pnl_dollar": t.pnl_dollar,
                "exit_reason": t.exit_reason, "composite_score": t.composite_score,
                "holding_days": t.holding_days,
            }
            for t in all_trades
        ]

    result.walk_forward = window_results
    result.status = "completed"
    return result


def print_comparison(baseline: BacktestResult, overlay: BacktestResult, weight: float):
    """Print side-by-side comparison of quant-only vs quant+LSTM."""
    print("\n" + "=" * 74)
    print("  QUANT-ONLY vs QUANT + LSTM COMPARISON")
    print(f"  LSTM weight: {weight:.0%}")
    print("=" * 74)

    rows = [
        ("Total return", baseline.total_return_pct, overlay.total_return_pct, "%"),
        ("Annual return", baseline.annual_return_pct, overlay.annual_return_pct, "%"),
        ("Sharpe", baseline.sharpe, overlay.sharpe, ""),
        ("Sortino", baseline.sortino, overlay.sortino, ""),
        ("Calmar", baseline.calmar, overlay.calmar, ""),
        ("Max drawdown", baseline.max_drawdown_pct, overlay.max_drawdown_pct, "%"),
        ("Win rate", baseline.win_rate_pct, overlay.win_rate_pct, "%"),
        ("Total trades", baseline.total_trades, overlay.total_trades, ""),
        ("SPY alpha", baseline.alpha_pct, overlay.alpha_pct, "%"),
    ]

    print(f"\n  {'Metric':<20s} {'Quant-Only':>12s} {'+ LSTM':>12s} {'Delta':>12s}")
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

    sharpe_delta = None
    if baseline.sharpe is not None and overlay.sharpe is not None:
        sharpe_delta = overlay.sharpe - baseline.sharpe

    print("\n  -- Verdict --")
    if sharpe_delta is not None:
        if sharpe_delta >= 0.1:
            print(f"  LSTM IMPROVES Sharpe by {sharpe_delta:+.2f} — ML signal adds value")
        elif sharpe_delta >= 0:
            print(f"  LSTM has MARGINAL effect on Sharpe ({sharpe_delta:+.2f})")
        else:
            print(f"  LSTM HURTS Sharpe by {sharpe_delta:+.2f} — quant-only is better")

    if baseline.walk_forward and overlay.walk_forward:
        print("\n  -- Walk-Forward Window Comparison --")
        print(f"  {'Window':<25s} {'Quant':>10s} {'+ LSTM':>10s} {'Delta':>10s}")
        print("  " + "-" * 57)
        for bw, ow in zip(baseline.walk_forward, overlay.walk_forward):
            period = f"{bw['test_start']} → {bw['test_end'][:7]}"
            b_ret = bw.get("return_pct", 0)
            o_ret = ow.get("return_pct", 0)
            delta = o_ret - b_ret
            sign = "+" if delta >= 0 else ""
            print(f"  {period:<25s} {b_ret:>9.2f}% {o_ret:>9.2f}% {sign}{delta:>8.2f}%")

    print("\n" + "=" * 74)


def main():
    parser = argparse.ArgumentParser(description="LSTM overlay backtest comparison")
    parser.add_argument("--universe", default="liquid_10",
                        help="Universe name (default: liquid_10)")
    parser.add_argument("--tickers", default="",
                        help="Comma-separated tickers (overrides --universe)")
    parser.add_argument("--start", default="2022-01-01",
                        help="Start date (default: 2022-01-01)")
    parser.add_argument("--end", default="", help="End date (default: today)")
    parser.add_argument("--rebalance", default="monthly", choices=["weekly", "monthly"])
    parser.add_argument("--walk-forward", action="store_true",
                        help="Use walk-forward validation with per-window LSTM training")
    parser.add_argument("--lstm-weight", type=float, default=0.15,
                        help="Weight for LSTM signal (default: 0.15)")
    parser.add_argument("--sweep-weights", action="store_true",
                        help="Sweep LSTM weights: 0.05, 0.10, 0.15, 0.20, 0.25, 0.30")
    parser.add_argument("--skip-baseline", action="store_true",
                        help="Skip baseline, only run LSTM overlay")
    # LSTM hyperparams
    parser.add_argument("--hidden-size", type=int, default=64)
    parser.add_argument("--num-layers", type=int, default=2)
    parser.add_argument("--dropout", type=float, default=0.3)
    parser.add_argument("--lookback", type=int, default=60,
                        help="LSTM sequence length in trading days (default: 60)")
    parser.add_argument("--horizon", type=int, default=20,
                        help="Forward return prediction horizon in days (default: 20)")
    parser.add_argument("--max-epochs", type=int, default=100)
    parser.add_argument("--no-shorts", action="store_true",
                        help="Disable short selling entirely (long-only mode)")
    parser.add_argument("--no-ic-calibration", action="store_true",
                        help="Disable IC-based signal weight calibration")
    parser.add_argument("--train-months", type=int, default=24,
                        help="Walk-forward train window months (default: 24)")
    parser.add_argument("--test-months", type=int, default=6,
                        help="Walk-forward test window months (default: 6)")
    parser.add_argument("--enable-news-sentiment", action="store_true",
                        help="Enable Finnhub news sentiment signal")
    parser.add_argument("--output", default="", help="Save results to JSON file")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Check torch is available
    try:
        import torch
        device = "CUDA" if torch.cuda.is_available() else "CPU"
        print(f"PyTorch: found (device: {device})")
    except ImportError:
        print("ERROR: PyTorch not installed. Run: pip install torch")
        sys.exit(1)

    tickers = ([t.strip().upper() for t in args.tickers.split(",") if t.strip()]
               if args.tickers else get_universe(args.universe))

    print(f"\nLSTM Backtest: {len(tickers)} tickers, {args.start} to {args.end or 'today'}")
    print(f"Rebalance: {args.rebalance}, LSTM hidden={args.hidden_size}, "
          f"layers={args.num_layers}, lookback={args.lookback}d, horizon={args.horizon}d")

    base_config = BacktestConfig(
        tickers=tickers,
        start_date=args.start,
        end_date=args.end,
        rebalance_freq=args.rebalance,
        short_threshold=-999.0 if args.no_shorts else -0.40,
        enable_ic_calibration=not args.no_ic_calibration,
        enable_news_sentiment=args.enable_news_sentiment,
        train_months=args.train_months,
        test_months=args.test_months,
        # LSTM params
        enable_lstm=False,  # start with baseline
        lstm_weight=args.lstm_weight,
        lstm_lookback_days=args.lookback,
        lstm_forecast_horizon=args.horizon,
        lstm_hidden_size=args.hidden_size,
        lstm_num_layers=args.num_layers,
        lstm_dropout=args.dropout,
        lstm_max_epochs=args.max_epochs,
    )

    t0 = time.time()
    all_results = {}

    if args.sweep_weights:
        weights = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
        print(f"Sweeping LSTM weights: {weights}")

        # Baseline
        print("\n--- Baseline (quant-only) ---")
        if args.walk_forward:
            baseline = run_walk_forward(base_config, progress_cb=progress)
        else:
            baseline = run_backtest(base_config, progress_cb=progress)
        print(f"  Baseline Sharpe: {baseline.sharpe}")
        all_results["baseline"] = baseline.to_dict()

        # Sweep
        print(f"\n  {'Weight':>8s} {'Sharpe':>8s} {'Return':>10s} {'Alpha':>10s}")
        print("  " + "-" * 40)

        for w in weights:
            base_config.lstm_weight = w
            base_config.enable_lstm = True
            if args.walk_forward:
                result = run_lstm_walk_forward(base_config)
            else:
                result = run_lstm_single(base_config)

            sharpe_str = f"{result.sharpe:.2f}" if result.sharpe else "N/A"
            ret_str = f"{result.total_return_pct:.2f}%" if result.total_return_pct else "N/A"
            alpha_str = f"{result.alpha_pct:.2f}%" if result.alpha_pct else "N/A"
            print(f"  {w:>8.0%} {sharpe_str:>8s} {ret_str:>10s} {alpha_str:>10s}")
            all_results[f"lstm_weight_{w:.2f}"] = result.to_dict()

    elif args.skip_baseline:
        base_config.enable_lstm = True
        base_config.lstm_weight = args.lstm_weight
        print(f"\n--- LSTM Only (weight={args.lstm_weight}) ---")
        if args.walk_forward:
            overlay = run_lstm_walk_forward(base_config)
        else:
            overlay = run_lstm_single(base_config)
        all_results["overlay"] = overlay.to_dict()
        print(f"\n  Sharpe: {overlay.sharpe}, Return: {overlay.total_return_pct}%")

    else:
        # A/B comparison
        print("\n--- Phase 1: Quant-Only Baseline ---")
        if args.walk_forward:
            baseline = run_walk_forward(base_config, progress_cb=progress)
        else:
            baseline = run_backtest(base_config, progress_cb=progress)
        print(f"  Baseline Sharpe: {baseline.sharpe}")
        all_results["baseline"] = baseline.to_dict()

        print("\n--- Phase 2: Quant + LSTM Overlay ---")
        base_config.enable_lstm = True
        base_config.lstm_weight = args.lstm_weight
        if args.walk_forward:
            overlay = run_lstm_walk_forward(base_config)
        else:
            overlay = run_lstm_single(base_config)
        all_results["overlay"] = overlay.to_dict()

        if overlay.status != "error":
            print_comparison(baseline, overlay, args.lstm_weight)

    elapsed = time.time() - t0
    print(f"\n  Total time: {elapsed:.1f}s")

    output_path = args.output or f"backtest_lstm_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"  Results saved to: {output_path}")


if __name__ == "__main__":
    main()
