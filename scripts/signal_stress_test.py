#!/usr/bin/env python3
"""
Signal Stack Stress Test — Phases 1-5
  1. Signal orthogonalization (residual IC)
  2. 12-1 month momentum as MR replacement
  3. RSI divergence vs BB squeeze conditional IC
  4. 52W high vs SMA substitution
  5. Cost sensitivity sweep
"""

import sys
import time
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import numpy as np
import pandas as pd
from scipy import stats

from quant.backtest import (
    BacktestConfig, run_walk_forward, load_universe_data,
    generate_rebalance_dates, compute_signals_at_date, load_vix_data,
)
from quant.redundancy import (
    SIGNAL_NAMES, compute_signal_scores_at_date, compute_forward_returns,
)
from quant.signals import compute_signal_vector, compute_rsi, compute_bollinger
from quant.universe import get_universe, BENCHMARK

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SHORT_NAMES = {
    "sma_trend": "SMA", "mean_reversion_z": "MR", "bollinger_pctb": "BB",
    "rsi": "RSI", "obv_trend": "OBV", "high_52w": "52W",
}


def progress(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}")


def load_data_and_dates(universe_name="liquid_50", start="2020-01-01", end="2026-04-01"):
    """Load universe data and generate monthly rebalance dates."""
    tickers = get_universe(universe_name)
    all_tickers = list(set(tickers + [BENCHMARK]))

    fetch_start = (pd.Timestamp(start) - pd.Timedelta(days=300)).strftime("%Y-%m-%d")
    progress(f"Loading {len(all_tickers)} tickers from {fetch_start}...")
    universe_data = load_universe_data(all_tickers, fetch_start, progress_cb=progress)
    benchmark_df = universe_data.pop(BENCHMARK, None)

    all_dates = sorted(set().union(*(df.index for df in universe_data.values())))
    trading_dates = pd.DatetimeIndex(all_dates)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    rebalance_dates = generate_rebalance_dates(start_ts, end_ts, "monthly", trading_dates)

    progress(f"Data loaded: {len(universe_data)} tickers, {len(rebalance_dates)} rebalance dates")
    return universe_data, rebalance_dates, benchmark_df


# =======================================================================
# PHASE 1: Signal Orthogonalization
# =======================================================================

def phase1_orthogonalization(universe_data, rebalance_dates):
    """For each signal, regress on all others, keep residual, compute residual IC."""
    print("\n" + "=" * 75)
    print("  PHASE 1: SIGNAL ORTHOGONALIZATION")
    print("=" * 75)

    all_raw_ics = {s: [] for s in SIGNAL_NAMES}
    all_resid_ics = {s: [] for s in SIGNAL_NAMES}
    n_dates_used = 0

    for date in rebalance_dates:
        scores_df = compute_signal_scores_at_date(universe_data, date, lookback_days=252)
        fwd_returns = compute_forward_returns(universe_data, date, forward_days=21)
        if scores_df is None or fwd_returns is None:
            continue

        common = list(set(scores_df.index) & set(fwd_returns.index))
        if len(common) < 10:
            continue

        scores = scores_df.loc[common, SIGNAL_NAMES]
        fwd = fwd_returns.loc[common]
        n_dates_used += 1

        for sig in SIGNAL_NAMES:
            # Raw IC
            if scores[sig].std() < 1e-8:
                all_raw_ics[sig].append(0.0)
                all_resid_ics[sig].append(0.0)
                continue

            rho, _ = stats.spearmanr(scores[sig], fwd)
            all_raw_ics[sig].append(float(rho) if not np.isnan(rho) else 0.0)

            # Residual IC: regress this signal on all others, take residual
            other_sigs = [s for s in SIGNAL_NAMES if s != sig]
            X = scores[other_sigs].values
            y = scores[sig].values

            # Add constant
            X_c = np.column_stack([np.ones(len(X)), X])
            try:
                beta, _, _, _ = np.linalg.lstsq(X_c, y, rcond=None)
                residual = y - X_c @ beta
            except Exception:
                residual = y

            if np.std(residual) < 1e-8:
                all_resid_ics[sig].append(0.0)
            else:
                rho_r, _ = stats.spearmanr(residual, fwd.values)
                all_resid_ics[sig].append(float(rho_r) if not np.isnan(rho_r) else 0.0)

    # Compute stats
    print(f"\n  Dates used: {n_dates_used}")
    print(f"\n  {'Signal':<8s} {'Raw IC':>10s} {'Raw t':>8s} {'Resid IC':>10s} {'Resid t':>8s} {'Verdict':>12s}")
    print(f"  {'-' * 60}")

    results = {}
    for sig in SIGNAL_NAMES:
        raw = np.array(all_raw_ics[sig])
        res = np.array(all_resid_ics[sig])

        raw_mean = np.mean(raw)
        raw_t = raw_mean / (np.std(raw) / np.sqrt(len(raw))) if np.std(raw) > 0 and len(raw) > 1 else 0
        res_mean = np.mean(res)
        res_t = res_mean / (np.std(res) / np.sqrt(len(res))) if np.std(res) > 0 and len(res) > 1 else 0

        if abs(res_t) >= 1.5:
            verdict = "KEEP"
        elif abs(raw_t) >= 1.5:
            verdict = "REDUNDANT"
        else:
            verdict = "DROP"

        results[sig] = {"raw_ic": raw_mean, "raw_t": raw_t, "resid_ic": res_mean, "resid_t": res_t, "verdict": verdict}
        sn = SHORT_NAMES[sig]
        print(f"  {sn:<8s} {raw_mean:>+10.4f} {raw_t:>8.2f} {res_mean:>+10.4f} {res_t:>8.2f} {verdict:>12s}")

    return results


# =======================================================================
# PHASE 2: 12-1 Month Momentum
# =======================================================================

def phase2_momentum(universe_data, rebalance_dates):
    """Test 12-1 month momentum as a new signal candidate."""
    print("\n" + "=" * 75)
    print("  PHASE 2: 12-1 MONTH MOMENTUM")
    print("=" * 75)

    mom_ics = []
    mom_sma_corrs = []
    mom_resid_ics = []
    n_used = 0

    for date in rebalance_dates:
        fwd_returns = compute_forward_returns(universe_data, date, forward_days=21)
        scores_df = compute_signal_scores_at_date(universe_data, date, lookback_days=252)
        if fwd_returns is None or scores_df is None:
            continue

        # Compute 12-1 month momentum for each ticker
        mom_scores = {}
        for ticker, df in universe_data.items():
            available = df[df.index <= date]
            if len(available) < 252:
                continue
            # close[-21] / close[-252] - 1 (skip most recent month)
            try:
                close_21 = float(available.iloc[-21]["close"])
                close_252 = float(available.iloc[-252]["close"])
                if close_252 > 0:
                    mom_scores[ticker] = close_21 / close_252 - 1
            except (IndexError, KeyError):
                continue

        common = list(set(mom_scores.keys()) & set(fwd_returns.index) & set(scores_df.index))
        if len(common) < 10:
            continue

        n_used += 1
        mom_vals = pd.Series({t: mom_scores[t] for t in common})
        fwd = fwd_returns.loc[common]
        sma_vals = scores_df.loc[common, "sma_trend"]

        # IC
        rho, _ = stats.spearmanr(mom_vals, fwd)
        mom_ics.append(float(rho) if not np.isnan(rho) else 0.0)

        # Correlation with SMA
        rho_sma, _ = stats.spearmanr(mom_vals, sma_vals)
        mom_sma_corrs.append(float(rho_sma) if not np.isnan(rho_sma) else 0.0)

        # Residual IC after regressing on SMA
        X = np.column_stack([np.ones(len(common)), sma_vals.values])
        y = mom_vals.values
        try:
            beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
            residual = y - X @ beta
            rho_r, _ = stats.spearmanr(residual, fwd.values)
            mom_resid_ics.append(float(rho_r) if not np.isnan(rho_r) else 0.0)
        except Exception:
            mom_resid_ics.append(0.0)

    mom_ics = np.array(mom_ics)
    mom_sma_corrs = np.array(mom_sma_corrs)
    mom_resid_ics = np.array(mom_resid_ics)

    ic_mean = np.mean(mom_ics)
    ic_t = ic_mean / (np.std(mom_ics) / np.sqrt(len(mom_ics))) if np.std(mom_ics) > 0 else 0
    corr_mean = np.mean(mom_sma_corrs)
    resid_mean = np.mean(mom_resid_ics)
    resid_t = resid_mean / (np.std(mom_resid_ics) / np.sqrt(len(mom_resid_ics))) if np.std(mom_resid_ics) > 0 else 0

    print(f"\n  Dates used: {n_used}")
    print(f"  12-1 Mom IC:            {ic_mean:+.4f}  (t = {ic_t:.2f})")
    print(f"  Corr with SMA:          {corr_mean:+.4f}")
    print(f"  Residual IC (vs SMA):   {resid_mean:+.4f}  (t = {resid_t:.2f})")

    if abs(ic_t) >= 2:
        verdict = "STRONG CANDIDATE"
    elif abs(ic_t) >= 1.5:
        verdict = "MARGINAL CANDIDATE"
    else:
        verdict = "NO IMPROVEMENT"
    print(f"  Verdict: {verdict}")

    return {
        "ic": ic_mean, "ic_t": ic_t,
        "corr_sma": corr_mean,
        "resid_ic": resid_mean, "resid_t": resid_t,
        "verdict": verdict,
    }


# =======================================================================
# PHASE 3: RSI Divergence vs BB Squeeze
# =======================================================================

def phase3_conditional_signals(universe_data, rebalance_dates):
    """Compare RSI divergence IC vs BB squeeze IC on conditional dates."""
    print("\n" + "=" * 75)
    print("  PHASE 3: RSI DIVERGENCE vs BB SQUEEZE (CONDITIONAL IC)")
    print("=" * 75)

    rsi_div_ics = []
    bb_squeeze_ics = []
    rsi_div_count = 0
    bb_squeeze_count = 0

    for date in rebalance_dates:
        fwd_returns = compute_forward_returns(universe_data, date, forward_days=21)
        if fwd_returns is None:
            continue

        # Compute RSI and BB for each ticker
        rsi_div_tickers = {}  # ticker -> rsi_score where divergence detected
        bb_squeeze_tickers = {}  # ticker -> bb_score where squeeze detected

        for ticker, df in universe_data.items():
            available = df[df.index <= date]
            if len(available) < 126:
                continue

            close = available["close"]

            # RSI with divergence
            rsi_result = compute_rsi(close)
            if rsi_result.metadata.get("divergence", ""):
                rsi_div_tickers[ticker] = rsi_result.score

            # BB with squeeze
            bb_result = compute_bollinger(close)
            if bb_result.metadata.get("squeeze", False):
                bb_squeeze_tickers[ticker] = bb_result.score

        # RSI divergence IC
        rsi_common = list(set(rsi_div_tickers.keys()) & set(fwd_returns.index))
        if len(rsi_common) >= 5:
            rsi_scores = pd.Series({t: rsi_div_tickers[t] for t in rsi_common})
            fwd_rsi = fwd_returns.loc[rsi_common]
            rho, _ = stats.spearmanr(rsi_scores, fwd_rsi)
            if not np.isnan(rho):
                rsi_div_ics.append(float(rho))
                rsi_div_count += len(rsi_common)

        # BB squeeze IC
        bb_common = list(set(bb_squeeze_tickers.keys()) & set(fwd_returns.index))
        if len(bb_common) >= 5:
            bb_scores = pd.Series({t: bb_squeeze_tickers[t] for t in bb_common})
            fwd_bb = fwd_returns.loc[bb_common]
            rho, _ = stats.spearmanr(bb_scores, fwd_bb)
            if not np.isnan(rho):
                bb_squeeze_ics.append(float(rho))
                bb_squeeze_count += len(bb_common)

    rsi_arr = np.array(rsi_div_ics) if rsi_div_ics else np.array([0.0])
    bb_arr = np.array(bb_squeeze_ics) if bb_squeeze_ics else np.array([0.0])

    rsi_mean = np.mean(rsi_arr)
    rsi_t = rsi_mean / (np.std(rsi_arr) / np.sqrt(len(rsi_arr))) if np.std(rsi_arr) > 0 and len(rsi_arr) > 1 else 0
    bb_mean = np.mean(bb_arr)
    bb_t = bb_mean / (np.std(bb_arr) / np.sqrt(len(bb_arr))) if np.std(bb_arr) > 0 and len(bb_arr) > 1 else 0

    print(f"\n  RSI divergence dates with >= 5 tickers: {len(rsi_div_ics)}, total observations: {rsi_div_count}")
    print(f"  BB squeeze dates with >= 5 tickers:     {len(bb_squeeze_ics)}, total observations: {bb_squeeze_count}")
    print(f"\n  RSI divergence IC:  {rsi_mean:+.4f}  (t = {rsi_t:.2f})")
    print(f"  BB squeeze IC:      {bb_mean:+.4f}  (t = {bb_t:.2f})")

    if abs(rsi_t) > abs(bb_t):
        winner = "RSI DIVERGENCE"
    elif abs(bb_t) > abs(rsi_t):
        winner = "BB SQUEEZE"
    else:
        winner = "TIE"
    print(f"  Winner: {winner}")

    return {
        "rsi_div_ic": rsi_mean, "rsi_div_t": rsi_t, "rsi_div_dates": len(rsi_div_ics),
        "bb_squeeze_ic": bb_mean, "bb_squeeze_t": bb_t, "bb_squeeze_dates": len(bb_squeeze_ics),
        "winner": winner,
    }


# =======================================================================
# PHASE 4: 52W High vs SMA
# =======================================================================

def phase4_52w_vs_sma(universe_data, rebalance_dates):
    """Test whether 52W high subsumes SMA or vice versa."""
    print("\n" + "=" * 75)
    print("  PHASE 4: 52W HIGH vs SMA")
    print("=" * 75)

    sma_ics = []
    h52_ics = []
    sma_resid_ics = []  # SMA residual after regressing on 52W
    h52_resid_ics = []  # 52W residual after regressing on SMA
    corrs = []
    n_used = 0

    for date in rebalance_dates:
        scores_df = compute_signal_scores_at_date(universe_data, date, lookback_days=252)
        fwd_returns = compute_forward_returns(universe_data, date, forward_days=21)
        if scores_df is None or fwd_returns is None:
            continue

        common = list(set(scores_df.index) & set(fwd_returns.index))
        if len(common) < 10:
            continue
        n_used += 1

        sma = scores_df.loc[common, "sma_trend"]
        h52 = scores_df.loc[common, "high_52w"]
        fwd = fwd_returns.loc[common]

        # Raw ICs
        rho_sma, _ = stats.spearmanr(sma, fwd)
        rho_h52, _ = stats.spearmanr(h52, fwd)
        sma_ics.append(float(rho_sma) if not np.isnan(rho_sma) else 0.0)
        h52_ics.append(float(rho_h52) if not np.isnan(rho_h52) else 0.0)

        # Correlation
        rho_pair, _ = stats.spearmanr(sma, h52)
        corrs.append(float(rho_pair) if not np.isnan(rho_pair) else 0.0)

        # Residual: 52W after regressing on SMA
        X = np.column_stack([np.ones(len(common)), sma.values])
        y = h52.values
        try:
            beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
            resid = y - X @ beta
            rho_r, _ = stats.spearmanr(resid, fwd.values)
            h52_resid_ics.append(float(rho_r) if not np.isnan(rho_r) else 0.0)
        except Exception:
            h52_resid_ics.append(0.0)

        # Residual: SMA after regressing on 52W
        X2 = np.column_stack([np.ones(len(common)), h52.values])
        y2 = sma.values
        try:
            beta2, _, _, _ = np.linalg.lstsq(X2, y2, rcond=None)
            resid2 = y2 - X2 @ beta2
            rho_r2, _ = stats.spearmanr(resid2, fwd.values)
            sma_resid_ics.append(float(rho_r2) if not np.isnan(rho_r2) else 0.0)
        except Exception:
            sma_resid_ics.append(0.0)

    def summarize(arr, label):
        a = np.array(arr)
        m = np.mean(a)
        t = m / (np.std(a) / np.sqrt(len(a))) if np.std(a) > 0 and len(a) > 1 else 0
        return m, t

    sma_m, sma_t = summarize(sma_ics, "SMA raw")
    h52_m, h52_t = summarize(h52_ics, "52W raw")
    sma_r_m, sma_r_t = summarize(sma_resid_ics, "SMA resid")
    h52_r_m, h52_r_t = summarize(h52_resid_ics, "52W resid")
    corr_mean = np.mean(corrs)

    print(f"\n  Dates used: {n_used}")
    print(f"  SMA <-> 52W correlation: {corr_mean:+.4f}")
    print(f"\n  {'Signal':<18s} {'IC':>10s} {'t':>8s}")
    print(f"  {'-' * 40}")
    print(f"  {'SMA raw':<18s} {sma_m:>+10.4f} {sma_t:>8.2f}")
    print(f"  {'52W raw':<18s} {h52_m:>+10.4f} {h52_t:>8.2f}")
    print(f"  {'SMA resid (vs 52W)':<18s} {sma_r_m:>+10.4f} {sma_r_t:>8.2f}")
    print(f"  {'52W resid (vs SMA)':<18s} {h52_r_m:>+10.4f} {h52_r_t:>8.2f}")

    if abs(h52_r_t) < 1.0 and abs(sma_r_t) < 1.0:
        verdict = "BOTH SUBSUMED — keep one, drop other"
    elif abs(h52_r_t) >= 1.5:
        verdict = "52W adds info beyond SMA — consider replacing"
    elif abs(sma_r_t) >= 1.5:
        verdict = "SMA adds info beyond 52W — keep SMA"
    else:
        verdict = "Neither adds significant info after controlling for the other"
    print(f"\n  Verdict: {verdict}")

    return {
        "sma_ic": sma_m, "sma_t": sma_t,
        "h52_ic": h52_m, "h52_t": h52_t,
        "sma_resid_ic": sma_r_m, "sma_resid_t": sma_r_t,
        "h52_resid_ic": h52_r_m, "h52_resid_t": h52_r_t,
        "corr": corr_mean, "verdict": verdict,
    }


# =======================================================================
# PHASE 5: Cost Sensitivity
# =======================================================================

def phase5_cost_sensitivity():
    """Run walk-forward at different transaction cost levels."""
    print("\n" + "=" * 75)
    print("  PHASE 5: COST SENSITIVITY")
    print("=" * 75)

    tickers = get_universe("liquid_10")
    cost_levels = [0, 5, 10, 15, 20, 30, 50]
    results = []

    for cost_bps in cost_levels:
        progress(f"Running walk-forward at {cost_bps} bps...")
        config = BacktestConfig(
            tickers=tickers,
            start_date="2020-01-01",
            end_date="2026-04-01",
            rebalance_freq="monthly",
            long_threshold=0.20,
            short_threshold=-999.0,  # long-only (no-shorts)
            enable_regime_filter=True,
            vix_caution_threshold=30.0,
            vix_risk_off_threshold=40.0,
            enable_ic_calibration=True,
            ic_shrinkage=0.90,
            max_long_positions=10,
            transaction_cost_bps=float(cost_bps),
            train_months=24,
            test_months=6,
        )

        result = run_walk_forward(config, progress_cb=progress)

        sharpe = result.sharpe if result.sharpe else 0.0
        ret = result.total_return_pct
        results.append({"cost_bps": cost_bps, "sharpe": sharpe, "return_pct": ret})
        progress(f"  {cost_bps} bps -> Sharpe {sharpe:.2f}, Return {ret:.1f}%")

    print(f"\n  {'Cost (bps)':>10s} {'Sharpe':>8s} {'Return %':>10s}")
    print(f"  {'-' * 32}")
    for r in results:
        print(f"  {r['cost_bps']:>10d} {r['sharpe']:>8.2f} {r['return_pct']:>+10.1f}")

    # Find break-even cost via interpolation
    sharpes = [(r["cost_bps"], r["sharpe"]) for r in results]
    breakeven = None
    for i in range(len(sharpes) - 1):
        c1, s1 = sharpes[i]
        c2, s2 = sharpes[i + 1]
        if s1 > 0 and s2 <= 0:
            # Linear interpolation
            breakeven = c1 + (0 - s1) / (s2 - s1) * (c2 - c1)
            break
    if breakeven is None and sharpes[-1][1] > 0:
        breakeven = "> 50 bps"
    elif breakeven is None:
        breakeven = "< 0 bps (strategy unprofitable)"

    print(f"\n  Break-even cost: {breakeven} bps" if isinstance(breakeven, str) else f"\n  Break-even cost: {breakeven:.0f} bps")

    return results, breakeven


# =======================================================================
# MAIN
# =======================================================================

if __name__ == "__main__":
    t0 = time.time()

    # Load data once for phases 1-4
    progress("Loading universe data for phases 1-4...")
    universe_data, rebalance_dates, benchmark_df = load_data_and_dates(
        universe_name="liquid_50", start="2020-01-01", end="2026-04-01"
    )

    # Phase 1: Orthogonalization
    ortho_results = phase1_orthogonalization(universe_data, rebalance_dates)

    # Phase 2: 12-1 Momentum
    mom_results = phase2_momentum(universe_data, rebalance_dates)

    # Phase 3: RSI divergence vs BB squeeze
    cond_results = phase3_conditional_signals(universe_data, rebalance_dates)

    # Phase 4: 52W vs SMA
    sma_52w_results = phase4_52w_vs_sma(universe_data, rebalance_dates)

    # Phase 5: Cost sensitivity (separate data load per run)
    cost_results, breakeven = phase5_cost_sensitivity()

    # =======================================================================
    # FINAL SUMMARY
    # =======================================================================
    elapsed = time.time() - t0
    print("\n" + "=" * 75)
    print("  SIGNAL STRESS TEST — FINAL SUMMARY")
    print("=" * 75)

    print(f"\n  Total runtime: {elapsed:.0f}s")

    print("\n  SIGNAL ORTHOGONALIZATION")
    print(f"  {'Signal':<8s} {'Raw IC(t)':>12s} {'Resid IC(t)':>14s} {'Verdict':>12s}")
    print(f"  {'-' * 50}")
    for sig in SIGNAL_NAMES:
        r = ortho_results[sig]
        sn = SHORT_NAMES[sig]
        print(f"  {sn:<8s} {r['raw_ic']:+.4f}({r['raw_t']:+.1f}) {r['resid_ic']:+.4f}({r['resid_t']:+.1f}) {r['verdict']:>12s}")

    print(f"\n  NEW SIGNAL CANDIDATES")
    print(f"  12-1 Mom | IC(t)={mom_results['ic']:+.4f}({mom_results['ic_t']:+.1f}) | "
          f"Corr SMA={mom_results['corr_sma']:+.3f} | "
          f"Resid IC(t)={mom_results['resid_ic']:+.4f}({mom_results['resid_t']:+.1f}) | "
          f"{mom_results['verdict']}")

    print(f"\n  CONDITIONAL SIGNAL TESTS")
    print(f"  RSI divergence IC={cond_results['rsi_div_ic']:+.4f} (t={cond_results['rsi_div_t']:.2f}, N={cond_results['rsi_div_dates']})")
    print(f"  BB squeeze IC=    {cond_results['bb_squeeze_ic']:+.4f} (t={cond_results['bb_squeeze_t']:.2f}, N={cond_results['bb_squeeze_dates']})")
    print(f"  Winner: {cond_results['winner']}")

    print(f"\n  52W vs SMA")
    print(f"  Correlation: {sma_52w_results['corr']:+.3f}")
    print(f"  SMA resid IC(t) after 52W: {sma_52w_results['sma_resid_ic']:+.4f}({sma_52w_results['sma_resid_t']:+.1f})")
    print(f"  52W resid IC(t) after SMA: {sma_52w_results['h52_resid_ic']:+.4f}({sma_52w_results['h52_resid_t']:+.1f})")
    print(f"  {sma_52w_results['verdict']}")

    print(f"\n  COST SENSITIVITY")
    print(f"  {'Cost':>6s} {'Sharpe':>8s} {'Return':>8s}")
    for r in cost_results:
        print(f"  {r['cost_bps']:>4d}bp {r['sharpe']:>8.2f} {r['return_pct']:>+7.1f}%")
    be_str = f"{breakeven:.0f}" if isinstance(breakeven, (int, float)) else str(breakeven)
    print(f"  Break-even: {be_str} bps")

    print("\n" + "=" * 75)
    print("  END OF STRESS TEST")
    print("=" * 75)
