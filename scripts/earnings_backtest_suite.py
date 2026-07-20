#!/usr/bin/env python3
"""
Comprehensive backtesting suite for IBES earnings signals.

Runs: weight sweep × universe sweep × CPCV validation × factor attribution.
"""

import sys, os, json, time, io, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.chdir(str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(".env")

import numpy as np
import pandas as pd
import requests

from quant.backtest import BacktestConfig, run_walk_forward, run_cpcv
from quant.universe import get_universe
from quant.cpcv import make_cpcv_groups


def progress(msg):
    print(f"    [{time.strftime('%H:%M:%S')}] {msg}")


def fetch_ff_factors():
    def fetch(url):
        r = requests.get(url, timeout=30)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        raw = z.read(z.namelist()[0]).decode("utf-8")
        lines = raw.strip().split("\n")
        header_idx = next(i for i, l in enumerate(lines) if "Mkt-RF" in l or "Mom" in l)
        cleaned = [lines[header_idx]]
        for l in lines[header_idx + 1 :]:
            s = l.strip()
            if not s:
                break
            first = s.split(",")[0].strip()
            if first.isdigit() and len(first) == 8:
                cleaned.append(s)
            else:
                break
        df = pd.read_csv(io.StringIO("\n".join(cleaned)))
        df.columns = [c.strip() for c in df.columns]
        first_col = df.columns[0]
        df.rename(columns={first_col: "date"}, inplace=True)
        df["date"] = pd.to_datetime(df["date"].astype(int).astype(str), format="%Y%m%d")
        df.set_index("date", inplace=True)
        return df / 100

    ff5 = fetch(
        "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
    )
    mom = fetch(
        "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip"
    )
    return ff5.join(mom, how="inner")


def factor_attribute(result, factors):
    eq = pd.DataFrame(result.equity_curve)
    if not eq.size:
        return {"alpha_ann": 0, "alpha_t": 0, "r2": 0, "resid_sharpe": 0}
    eq["date"] = pd.to_datetime(eq["date"])
    eq = eq.set_index("date").sort_index()
    eq["daily_return"] = eq["equity"].pct_change()
    strat = eq["daily_return"].dropna()

    common = strat.index.intersection(factors.index)
    if len(common) < 30:
        return {"alpha_ann": 0, "alpha_t": 0, "r2": 0, "resid_sharpe": 0}

    s = strat.loc[common].values
    ff = factors.loc[common]
    y = s - ff["RF"].values

    factor_cols = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]
    X = np.column_stack([np.ones(len(y)), ff[factor_cols].values])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta
    r2 = 1 - np.var(resid) / np.var(y)
    se = np.sqrt(np.diagonal(np.var(resid) * np.linalg.inv(X.T @ X)))
    t_stats = beta / se

    return {
        "alpha_ann": round(beta[0] * 252 * 100, 2),
        "alpha_t": round(t_stats[0], 2),
        "r2": round(r2, 4),
        "resid_sharpe": round(float(np.mean(resid) / np.std(resid) * np.sqrt(252)), 2)
        if np.std(resid) > 0
        else 0,
        "mom_beta": round(beta[6], 4),
        "mom_t": round(t_stats[6], 2),
        "rmw_beta": round(beta[4], 4),
        "rmw_t": round(t_stats[4], 2),
    }


def make_config(tickers, enable_earnings=False, earnings_weight=0.30):
    return BacktestConfig(
        tickers=tickers,
        start_date="2020-01-01",
        rebalance_freq="monthly",
        long_threshold=0.20,
        short_threshold=-999.0,
        enable_regime_filter=True,
        vix_caution_threshold=30.0,
        vix_risk_off_threshold=40.0,
        enable_ic_calibration=False,
        enable_death_golden_cross=True,
        enable_earnings_signals=enable_earnings,
        earnings_signal_weight=earnings_weight,
        fundamental_provider="wrds",
        train_months=24,
        test_months=6,
    )


def compute_cpcv_alpha(cpcv_result, group_spy):
    details = cpcv_result.combination_details
    if not details:
        return 0, 0, 0
    alphas = [c["return_pct"] - sum(group_spy[gi] for gi in c["test_groups"]) for c in details]
    arr = np.array(alphas)
    return (
        round(float(np.mean(arr)), 2),
        round(float(np.median(arr)), 2),
        round(float(np.mean(arr > 0) * 100), 1),
    )


def main():
    t0 = time.time()

    # Load factors once
    print("Loading Fama-French factors...")
    factors = fetch_ff_factors()

    # Load SPY for alpha computation
    spy = pd.read_csv(".price_cache/SPY.csv", parse_dates=["date"], index_col="date").sort_index()
    spy_2020 = spy[spy.index >= "2020-01-01"]
    trading_dates = pd.DatetimeIndex(sorted(spy_2020.index))
    groups = make_cpcv_groups("2020-01-01", "2026-04-07", 10, trading_dates)
    group_spy = [
        (
            float(spy[(spy.index >= s) & (spy.index <= e)].iloc[-1]["close"])
            / float(spy[(spy.index >= s) & (spy.index <= e)].iloc[0]["close"])
            - 1
        )
        * 100
        if len(spy[(spy.index >= s) & (spy.index <= e)]) > 1
        else 0
        for s, e in groups
    ]

    all_results = []

    # ── 1. WEIGHT SWEEP on liquid_10 (CPCV 50 paths each) ──
    print(f"\n{'=' * 100}")
    print("  SECTION 1: EARNINGS SIGNAL WEIGHT SWEEP (liquid_10, CPCV 50 paths)")
    print(f"{'=' * 100}")

    tickers = get_universe("liquid_10")
    for w in [0.00, 0.05, 0.10, 0.15, 0.20, 0.30]:
        label = f"w={w:.2f}" + (" (baseline)" if w == 0 else "")
        print(f"\n  --- {label} ---")
        config = make_config(tickers, enable_earnings=(w > 0), earnings_weight=w)

        # Walk-forward
        wf = run_walk_forward(config, progress_cb=progress)
        fa = factor_attribute(wf, factors)

        # CPCV
        cpcv = run_cpcv(config, n_groups=10, max_combinations=50, progress_cb=progress)
        mean_alpha, med_alpha, pct_pos_alpha = compute_cpcv_alpha(cpcv, group_spy)

        row = {
            "section": "weight_sweep",
            "label": label,
            "universe": "liquid_10",
            "wf_sharpe": wf.sharpe,
            "wf_return": wf.total_return_pct,
            "alpha_ann": fa["alpha_ann"],
            "alpha_t": fa["alpha_t"],
            "resid_sharpe": fa["resid_sharpe"],
            "r2": fa["r2"],
            "cpcv_pbo": round(cpcv.pbo * 100, 1),
            "cpcv_med_sharpe": cpcv.median_oos_sharpe,
            "cpcv_pct_pos": cpcv.pct_positive_oos,
            "cpcv_mean_alpha": mean_alpha,
            "cpcv_pct_pos_alpha": pct_pos_alpha,
        }
        all_results.append(row)
        print(
            f"    WF: Sharpe={wf.sharpe} Return={wf.total_return_pct}% | "
            f"FF6 Alpha={fa['alpha_ann']:+.1f}% (t={fa['alpha_t']:.2f}) | "
            f"CPCV: PBO={cpcv.pbo * 100:.0f}% MedSR={cpcv.median_oos_sharpe:.2f} "
            f"Alpha={mean_alpha:+.1f}%"
        )

    # ── 2. UNIVERSE SWEEP at best weight from section 1 ──
    best_w = 0.10  # conservative default
    best_row = max(
        [
            r
            for r in all_results
            if r["section"] == "weight_sweep" and r["label"] != "w=0.00 (baseline)"
        ],
        key=lambda r: r["cpcv_med_sharpe"],
        default=None,
    )
    if best_row:
        best_w = float(best_row["label"].split("=")[1].split(" ")[0])
    print(f"\n{'=' * 100}")
    print(f"  SECTION 2: UNIVERSE SWEEP at w={best_w:.2f} (CPCV 50 paths)")
    print(f"{'=' * 100}")

    for uni_name in ["liquid_10", "liquid_20", "liquid_50"]:
        uni_tickers = get_universe(uni_name)
        label = f"{uni_name} ({len(uni_tickers)})"
        print(f"\n  --- {label} ---")
        config = make_config(uni_tickers, enable_earnings=True, earnings_weight=best_w)

        wf = run_walk_forward(config, progress_cb=progress)
        fa = factor_attribute(wf, factors)

        cpcv = run_cpcv(config, n_groups=10, max_combinations=50, progress_cb=progress)
        mean_alpha, med_alpha, pct_pos_alpha = compute_cpcv_alpha(cpcv, group_spy)

        row = {
            "section": "universe_sweep",
            "label": label,
            "universe": uni_name,
            "wf_sharpe": wf.sharpe,
            "wf_return": wf.total_return_pct,
            "alpha_ann": fa["alpha_ann"],
            "alpha_t": fa["alpha_t"],
            "resid_sharpe": fa["resid_sharpe"],
            "r2": fa["r2"],
            "cpcv_pbo": round(cpcv.pbo * 100, 1),
            "cpcv_med_sharpe": cpcv.median_oos_sharpe,
            "cpcv_pct_pos": cpcv.pct_positive_oos,
            "cpcv_mean_alpha": mean_alpha,
            "cpcv_pct_pos_alpha": pct_pos_alpha,
        }
        all_results.append(row)
        print(
            f"    WF: Sharpe={wf.sharpe} Return={wf.total_return_pct}% | "
            f"FF6 Alpha={fa['alpha_ann']:+.1f}% (t={fa['alpha_t']:.2f}) | "
            f"CPCV: PBO={cpcv.pbo * 100:.0f}% MedSR={cpcv.median_oos_sharpe:.2f}"
        )

    # ── 3. FULL CPCV at best config (252 paths) ──
    print(f"\n{'=' * 100}")
    print(f"  SECTION 3: FULL 252-PATH CPCV — Best Config")
    print(f"{'=' * 100}")

    config = make_config(get_universe("liquid_10"), enable_earnings=True, earnings_weight=best_w)
    cpcv_full = run_cpcv(config, n_groups=10, progress_cb=progress)
    mean_alpha, med_alpha, pct_pos_alpha = compute_cpcv_alpha(cpcv_full, group_spy)
    print(cpcv_full.print_summary())
    print(f"  Alpha: mean={mean_alpha:+.1f}%, median={med_alpha:+.1f}%, α>0={pct_pos_alpha:.0f}%")

    # ── FINAL REPORT ──
    elapsed = time.time() - t0
    print(f"\n{'=' * 100}")
    print(f"  COMPREHENSIVE EARNINGS SIGNAL REPORT ({elapsed:.0f}s)")
    print(f"{'=' * 100}")

    print(
        f"\n  {'Config':<30s} {'WF SR':>6s} {'WF Ret':>8s} {'α ann':>7s} {'α t':>6s} {'PBO':>6s} {'CPCV SR':>8s} {'CPCV α':>8s} {'α>0%':>6s}"
    )
    print(f"  {'-' * 95}")

    for r in all_results:
        print(
            f"  {r['label']:<30s} {r['wf_sharpe'] or 0:>5.2f} {r['wf_return']:>+7.1f}% "
            f"{r['alpha_ann']:>+6.1f}% {r['alpha_t']:>5.2f} {r['cpcv_pbo']:>5.1f}% "
            f"{r['cpcv_med_sharpe']:>7.2f} {r['cpcv_mean_alpha']:>+7.1f}% {r['cpcv_pct_pos_alpha']:>5.0f}%"
        )

    # Save
    outpath = f"backtests/earnings_suite_{time.strftime('%Y%m%d_%H%M%S')}.json"
    with open(outpath, "w") as f:
        json.dump(
            {
                "results": all_results,
                "full_cpcv": cpcv_full.to_dict(),
                "elapsed_seconds": elapsed,
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\n  Results saved to: {outpath}")
    print(f"{'=' * 100}")


if __name__ == "__main__":
    main()
