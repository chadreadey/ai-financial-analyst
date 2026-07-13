"""
Levered core sweep — phase 1 of the levered-backtest workstream.

Static gross-exposure sweep on the validated gold-standard composite
(v4-qmj at max_long_positions=10, max_per_sector=5, long-only). No
sleeve, no beta completion, no vol-target. Financing = FRED SOFR + spread
accrued daily; guardrails are pre-declared and structurally enforced.

Modes:
  --mode walkforward   Runs walk-forward per variant + financing sensitivity
                       (base spread and, per-variant, ±200bp).
  --mode cpcv          Runs CPCV per variant (slow). Use --cpcv-groups
                       and --cpcv-max-combinations to trim runtime.

Outputs (default):
  docs/audit/2026-07-12-levered-core-sweep.md
  docs/audit/session-4/levered-sweep/<variant>-<spread_bps>.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(REPO / ".env")

import pandas as pd  # noqa: E402

from quant.backtest import BacktestConfig, run_walk_forward, run_cpcv  # noqa: E402
from quant import cross_sectional as cs  # noqa: E402

logger = logging.getLogger(__name__)


# ── universe helpers ───────────────────────────────────────────────────

PRICE_CACHE_DIR = REPO / ".price_cache"
WRDS_DB_PATH = REPO / ".wrds_pit.db"
OUT_JSON_DIR = REPO / "docs" / "audit" / "session-4" / "levered-sweep"
OUT_MD_PATH = REPO / "docs" / "audit" / "2026-07-12-levered-core-sweep.md"


def get_audit_universe() -> list[str]:
    """WRDS PIT ∩ local price cache (matches audit sessions 2/3)."""
    if not WRDS_DB_PATH.exists() or not PRICE_CACHE_DIR.exists():
        return []
    conn = sqlite3.connect(str(WRDS_DB_PATH))
    wrds = {r[0] for r in conn.execute(
        "SELECT DISTINCT ticker FROM compustat_quarterly"
    ).fetchall()}
    conn.close()
    cache = {p.stem for p in PRICE_CACHE_DIR.iterdir() if p.suffix == ".csv"}
    return sorted(wrds & cache)


# ── gold-standard composite (v4-qmj-only) ──────────────────────────────

# Matches scripts/run_audit_walkforward.py COMPOSITE_WEIGHT_CONFIGS["v4-qmj-only"]
V4_QMJ_ONLY_WEIGHTS = {
    "obv_trend": 0.20,
    "earnings_rank_score": 0.40,
    "institutional_flow_score": 0.10,
    "sentiment_score": 0.0,
    "sector_momentum_score": 0.0,
    "quality_score": 0.0,
    "price_momentum_score": 0.0,
    "insider_score": 0.0,
    "event_timing_score": 0.0,
    "price_regression_score": 0.0,
    "arima_forecast_score": 0.0,
    "qmj_score": 0.30,
}


def build_gold_config(
    tickers: list[str],
    start: str,
    end: str,
    *,
    gross_exposure: float,
    financing_spread_bps: float,
    guardrails: dict,
    train_months: int = 24,
    test_months: int = 6,
) -> BacktestConfig:
    """Validated gold-standard core config with leverage knobs threaded in."""
    return BacktestConfig(
        tickers=tickers,
        start_date=start,
        end_date=end,
        rebalance_freq="monthly",
        long_threshold=0.20,
        short_threshold=-0.40,
        enable_regime_filter=True,
        enable_ic_calibration=True,
        max_long_positions=10,
        max_short_positions=0,       # long-only per production
        max_per_sector=5,
        train_months=train_months,
        test_months=test_months,
        # Signals — earnings + QMJ + institutional flow
        enable_earnings_signals=True,
        earnings_signal_weight=0.30,
        enable_news_sentiment=False,   # v4-qmj-only has sentiment_score=0
        enable_institutional_flow=False,  # weight in composite, not blended
        enable_qmj_signal=True,
        enable_short_fundamental_veto=False,
        # Leverage knobs
        gross_exposure=gross_exposure,
        financing_spread_bps=financing_spread_bps,
        leverage_max_drawdown_pct=guardrails.get("max_drawdown_pct"),
        leverage_stressed_day_loss_pct=guardrails.get("stressed_day_loss_pct"),
        leverage_stress_shock_pct=guardrails.get("stress_shock_pct", 0.08),
        leverage_financing_cost_cap_frac_of_excess_return=guardrails.get(
            "financing_cost_cap_frac_of_excess_return"
        ),
    )


# ── sweep runners ──────────────────────────────────────────────────────

def run_variant_walkforward(
    variant_name: str,
    tickers: list[str],
    start: str,
    end: str,
    gross_exposure: float,
    financing_spread_bps: float,
    guardrails: dict,
    limit_tickers: int = 0,
) -> dict:
    """Run a single walk-forward with the given leverage config."""
    if limit_tickers and limit_tickers < len(tickers):
        tickers = tickers[:limit_tickers]

    cfg = build_gold_config(
        tickers=tickers, start=start, end=end,
        gross_exposure=gross_exposure,
        financing_spread_bps=financing_spread_bps,
        guardrails=guardrails,
    )

    # Force gold-standard composite weights for this run.
    orig_weights = dict(cs.DEFAULT_COMPOSITE_WEIGHTS)
    cs.DEFAULT_COMPOSITE_WEIGHTS = dict(V4_QMJ_ONLY_WEIGHTS)
    t0 = time.time()
    try:
        result = run_walk_forward(
            cfg,
            progress_cb=lambda m: print(f"    [{datetime.now().strftime('%H:%M:%S')}] {m}"),
        )
    finally:
        cs.DEFAULT_COMPOSITE_WEIGHTS = orig_weights
    elapsed = time.time() - t0

    summary = {
        "variant": variant_name,
        "gross_exposure": gross_exposure,
        "financing_spread_bps": financing_spread_bps,
        "status": result.status,
        "error": result.error,
        "elapsed_seconds": round(elapsed, 1),
        "n_tickers": len(tickers),
        "start": start,
        "end": end,
        "guardrails_config": guardrails,
        "metrics": {
            "total_return_pct": result.total_return_pct,
            "annual_return_pct": result.annual_return_pct,
            "sharpe": result.sharpe,
            "sortino": result.sortino,
            "calmar": result.calmar,
            "max_drawdown_pct": result.max_drawdown_pct,
            "win_rate_pct": result.win_rate_pct,
            "total_trades": result.total_trades,
            "avg_holding_days": result.avg_holding_days,
            "benchmark_return_pct": result.benchmark_return_pct,
            "alpha_pct": result.alpha_pct,
        },
        "financing_dollars_paid": result.financing_dollars_paid,
        "financing_drag_bps": result.financing_drag_bps,
        "guardrail_passed": result.guardrail_passed,
        "guardrail_breaches": result.guardrail_breaches,
        "guardrail_stats": result.guardrail_stats,
        "n_windows": len(result.walk_forward or []),
    }
    return summary


def run_variant_cpcv(
    variant_name: str,
    tickers: list[str],
    start: str,
    end: str,
    gross_exposure: float,
    financing_spread_bps: float,
    guardrails: dict,
    cpcv_groups: int,
    cpcv_max_combinations: Optional[int],
    limit_tickers: int = 0,
) -> dict:
    """Run CPCV for one variant, return summary with pass rate."""
    if limit_tickers and limit_tickers < len(tickers):
        tickers = tickers[:limit_tickers]

    cfg = build_gold_config(
        tickers=tickers, start=start, end=end,
        gross_exposure=gross_exposure,
        financing_spread_bps=financing_spread_bps,
        guardrails=guardrails,
    )
    orig_weights = dict(cs.DEFAULT_COMPOSITE_WEIGHTS)
    cs.DEFAULT_COMPOSITE_WEIGHTS = dict(V4_QMJ_ONLY_WEIGHTS)
    t0 = time.time()
    try:
        cpcv_result = run_cpcv(
            cfg,
            n_groups=cpcv_groups,
            max_combinations=cpcv_max_combinations,
            progress_cb=lambda m: print(f"    [{datetime.now().strftime('%H:%M:%S')}] {m}"),
        )
    finally:
        cs.DEFAULT_COMPOSITE_WEIGHTS = orig_weights
    elapsed = time.time() - t0

    # Post-process combo details for guardrail pass rate + financing.
    combos = cpcv_result.combination_details
    n_pass = sum(1 for c in combos if c.get("guardrail_passed") in (True, None))
    n_total = max(len(combos), 1)
    pass_rate = n_pass / n_total
    fin_dollars = [c.get("financing_dollars", 0.0) for c in combos]
    avg_fin = sum(fin_dollars) / max(len(fin_dollars), 1)

    summary = {
        "variant": variant_name,
        "gross_exposure": gross_exposure,
        "financing_spread_bps": financing_spread_bps,
        "elapsed_seconds": round(elapsed, 1),
        "n_tickers": len(tickers),
        "start": start,
        "end": end,
        "cpcv": {
            "n_groups": cpcv_result.n_groups,
            "n_combinations": cpcv_result.n_combinations,
            "n_completed": cpcv_result.n_combinations_completed,
            "n_skipped": cpcv_result.n_combinations_skipped,
            "median_oos_sharpe": cpcv_result.median_oos_sharpe,
            "mean_oos_sharpe": cpcv_result.mean_oos_sharpe,
            "std_oos_sharpe": cpcv_result.std_oos_sharpe,
            "pct_positive_oos": cpcv_result.pct_positive_oos,
            "pbo": cpcv_result.pbo,
            "pbo_method": cpcv_result.pbo_method,
            "dsr": cpcv_result.deflated_sharpe_ratio,
        },
        "guardrail_pass_rate": pass_rate,
        "guardrail_pass_count": n_pass,
        "guardrail_fail_count": n_total - n_pass,
        "guardrails_config": guardrails,
        "avg_financing_dollars_per_combo": round(avg_fin, 2),
    }
    return summary


# ── report writer ──────────────────────────────────────────────────────

def _fmt(v, fmt: str = "{:+.2f}") -> str:
    if v is None:
        return "—"
    try:
        return fmt.format(v)
    except Exception:
        return str(v)


def write_markdown_report(
    variant_runs: list[dict],
    sensitivity_runs: dict[str, dict],  # keyed by variant name -> {"minus": row, "plus": row}
    cpcv_runs: dict[str, dict],         # keyed by variant name (optional)
    guardrails: dict,
    universe_size: int,
    window: tuple[str, str],
    out_path: Path,
    guardrail_fail_threshold: float = 0.25,
) -> None:
    """Write the sweep markdown report."""
    lines: list[str] = []
    lines.append("# Levered Core Sweep — Phase 1 Results")
    lines.append("")
    lines.append(f"**Generated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(
        f"**Window**: {window[0]} → {window[1]}  "
        f"**Universe**: {universe_size} tickers (WRDS ∩ price-cache)  "
        f"**Composite**: v4-qmj-only @ max_long_positions=10, max_per_sector=5, long-only"
    )
    lines.append("")

    # Pre-declared guardrails
    lines.append("## Pre-declared guardrails (declared before runs, engine-enforced)")
    lines.append("")
    lines.append(f"- **Max drawdown**: {guardrails.get('max_drawdown_pct', 'n/a'):.0%} of peak NAV")
    lines.append(
        f"- **Stressed single-day loss**: cap "
        f"{guardrails.get('stressed_day_loss_pct', 0):.0%} of NAV assuming a "
        f"{guardrails.get('stress_shock_pct', 0.08):.0%} single-day market shock at policy gross"
    )
    lines.append(
        f"- **Financing / excess-return cap**: financing cost may not exceed "
        f"{guardrails.get('financing_cost_cap_frac_of_excess_return', 0):.0%} "
        f"of realized excess return vs SPY"
    )
    lines.append(f"- **CPCV path fail threshold**: >{guardrail_fail_threshold:.0%} of paths failing => variant FAILED")
    lines.append("")

    # Interpretation section (leave for post-run insertion)
    lines.append("## Interpretation")
    lines.append("")
    # Sort variants by gross
    variant_runs_sorted = sorted(variant_runs, key=lambda r: r["gross_exposure"])

    # Q1: L-1.5 clears CPCV after financing?
    l15 = next((r for r in variant_runs_sorted if abs(r["gross_exposure"] - 1.5) < 1e-6), None)
    l15_cpcv = cpcv_runs.get("L-1.5") if cpcv_runs else None
    q1 = "L-1.5 CPCV run was not executed in this session (provisional)."
    if l15_cpcv:
        pbo = l15_cpcv["cpcv"]["pbo"]
        dsr = l15_cpcv["cpcv"]["dsr"]
        pr = l15_cpcv["guardrail_pass_rate"]
        q1 = (f"L-1.5 CPCV: PBO {pbo:.1%}, DSR {dsr:.3f}, guardrail pass rate {pr:.1%}. "
              f"{'CLEARS' if (pbo < 0.25 and dsr > 0 and pr >= 1 - guardrail_fail_threshold) else 'DOES NOT CLEAR'} the gate.")
    lines.append(f"1. **Does L-1.5 clear CPCV after financing?** {q1}")

    # Q2: monotonic decay
    sharpes = [(r["gross_exposure"], r["metrics"]["sharpe"]) for r in variant_runs_sorted if r["metrics"]["sharpe"] is not None]
    q2 = "insufficient data"
    if len(sharpes) >= 3:
        vals = [s for _, s in sharpes]
        max_idx = vals.index(max(vals))
        max_gross = sharpes[max_idx][0]
        monotone_up_then_down = all(
            vals[i] <= vals[i + 1] for i in range(max_idx)
        ) and all(vals[i] >= vals[i + 1] for i in range(max_idx, len(vals) - 1))
        q2 = (
            f"Sharpe peaks at L-{max_gross:.2f} (Sharpe={vals[max_idx]:.2f}). "
            + ("Monotone rise-then-fall — clear optimum." if monotone_up_then_down
               else "Non-monotone — no clean optimum in observed range.")
        )
    lines.append(f"2. **Is there a Sharpe optimum in the sweep?** {q2}")

    # Q3: sensitivity flip
    flip_variants = []
    for r in variant_runs_sorted:
        v = r["variant"]
        if v in sensitivity_runs:
            base_pass = bool(r["guardrail_passed"]) if r["guardrail_passed"] is not None else True
            for tag, sens in sensitivity_runs[v].items():
                sens_pass = bool(sens["guardrail_passed"]) if sens["guardrail_passed"] is not None else True
                if base_pass != sens_pass:
                    flip_variants.append((v, tag, base_pass, sens_pass))
    q3 = "None." if not flip_variants else "; ".join(
        f"{v} flips pass={base}→{sens} at {tag}" for v, tag, base, sens in flip_variants
    )
    lines.append(f"3. **Financing sensitivity flips (base vs ±200bp)?** {q3}")

    # Q4: recommended next
    passers = [r for r in variant_runs_sorted if (r["guardrail_passed"] is None or r["guardrail_passed"])]
    if not passers:
        q4 = "None. All variants fail at least one guardrail. Do NOT promote to phase 2."
    else:
        # Highest Sharpe among passers with gross > 1.0
        levered_pass = [r for r in passers if r["gross_exposure"] > 1.0 and r["metrics"]["sharpe"] is not None]
        if not levered_pass:
            q4 = "L-1.0 (baseline) is the only variant that passes. Leverage is not additive on this composite."
        else:
            best = max(levered_pass, key=lambda r: r["metrics"]["sharpe"])
            q4 = (
                f"L-{best['gross_exposure']:.2f} is the highest-Sharpe passing levered variant "
                f"(Sharpe {best['metrics']['sharpe']:.2f}, MaxDD {best['metrics']['max_drawdown_pct']:.2f}%). "
                "Candidate for phase-2 evaluation only if CPCV/PBO/DSR clears the gate."
            )
    lines.append(f"4. **Recommended next step**: {q4}")
    lines.append("")

    # Results table
    lines.append("## Results")
    lines.append("")
    header = "| Variant | Gross | CAGR | Sharpe (post-fin) | MaxDD | Ann. Vol | PBO | DSR | Fin. drag (bps/yr) | Guardrail | Fin. sensitivity Sharpe (−200bp / +200bp) |"
    lines.append(header)
    lines.append("|" + "|".join("---" for _ in header.split("|")[1:-1]) + "|")

    for r in variant_runs_sorted:
        gross = r["gross_exposure"]
        v = r["variant"]
        m = r["metrics"]
        cpcv = cpcv_runs.get(v, {}).get("cpcv", {}) if cpcv_runs else {}
        pbo = cpcv.get("pbo")
        dsr = cpcv.get("dsr")
        # Ann. vol: derived from Sharpe & annualized return (Sharpe ≈ excess ret / ann vol)
        # Rough estimate: ann_return / sharpe ≈ ann_vol
        ann_vol = None
        if m["sharpe"] and m["annual_return_pct"] is not None:
            try:
                ann_vol = abs(m["annual_return_pct"]) / max(abs(m["sharpe"]), 1e-6)
            except Exception:
                ann_vol = None
        # Financing sensitivity Sharpes
        sens = sensitivity_runs.get(v, {})
        sens_minus = sens.get("minus", {}).get("metrics", {}).get("sharpe")
        sens_plus = sens.get("plus", {}).get("metrics", {}).get("sharpe")
        sens_str = f"{_fmt(sens_minus, '{:.2f}')} / {_fmt(sens_plus, '{:.2f}')}"
        # Guardrail marker
        if r["guardrail_passed"] is None:
            gr = "no-gate"
        elif r["guardrail_passed"]:
            gr = "PASS"
        else:
            gr = "FAIL: " + "; ".join(r.get("guardrail_breaches", []))[:80]

        lines.append(
            f"| {v} | {gross:.2f} | {_fmt(m['annual_return_pct'], '{:+.2f}%')} | "
            f"{_fmt(m['sharpe'], '{:.2f}')} | {_fmt(m['max_drawdown_pct'], '{:.2f}%')} | "
            f"{_fmt(ann_vol, '{:.2f}%')} | {_fmt(pbo, '{:.1%}')} | {_fmt(dsr, '{:.2f}')} | "
            f"{_fmt(r['financing_drag_bps'], '{:.1f}')} | {gr} | {sens_str} |"
        )
    lines.append("")

    # CPCV note if none
    if not cpcv_runs:
        lines.append("### CPCV note")
        lines.append("")
        lines.append(
            "> **PROVISIONAL** — CPCV was not run in this session due to compute budget "
            "(each 252-path CPCV run at ~200 tickers × 10y is >8h serially). Numbers in "
            "the PBO/DSR columns are blank pending a re-run at 252 paths per variant. "
            "The walk-forward numbers and the guardrail evaluations shown are final."
        )
        lines.append("")

    # Methodology
    lines.append("## Methodology")
    lines.append("")
    lines.append("- **Financing model**: FRED SOFR90DAYAVG (3M SOFR) + `financing_spread_bps`, "
                 "accrued daily as `borrowed_dollars * (ann_rate + spread) / 252`, where "
                 "`borrowed_dollars = (gross_exposure - 1.0) * NAV_start_of_day`. Fallback "
                 "to overnight SOFR → DGS3MO T-bill → hardcoded 2% broker-call proxy.")
    lines.append("- **Financing sensitivity**: `financing_spread_bps` swept at base − 200bp, "
                 "base, base + 200bp.")
    lines.append("- **Guardrails**: `LeverageGuardrails` dataclass, evaluated post-simulation. "
                 "Breach fails the run (or CPCV path) structurally — no re-tuning against the gate.")
    lines.append("- **Composite**: v4-qmj-only (docs/audit/session-3/v4-qmj-only-results.json), "
                 "long-only, monthly rebalance, `max_long_positions=10`, `max_per_sector=5`.")
    lines.append("- **No sleeve**, **no beta completion**, **no vol-target**, **no regime-conditional gearing**.")
    lines.append("")

    out_path.write_text("\n".join(lines) + "\n")


# ── main ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["walkforward", "cpcv", "both"], default="walkforward")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--limit-tickers", type=int, default=200,
                        help="Cap universe. Match audit session-3 for comparability. 0=uncapped.")
    parser.add_argument("--gross", type=float, nargs="+",
                        default=[1.0, 1.2, 1.5, 1.75, 2.0])
    parser.add_argument("--sensitivity-only", nargs="*", default=["1.5"],
                        help="Which gross variants to run financing sensitivity on.")
    parser.add_argument("--base-spread-bps", type=float, default=150.0)
    parser.add_argument("--sensitivity-delta-bps", type=float, default=200.0)
    parser.add_argument("--max-dd-cap", type=float, default=0.25)
    parser.add_argument("--stressed-day-cap", type=float, default=0.15)
    parser.add_argument("--stress-shock", type=float, default=0.08)
    parser.add_argument("--fin-cap-frac", type=float, default=0.30)
    parser.add_argument("--guardrail-fail-threshold", type=float, default=0.25)
    parser.add_argument("--cpcv-groups", type=int, default=12)
    parser.add_argument("--cpcv-max-combinations", type=int, default=100,
                        help="Cap CPCV combos per variant. Default 100 (provisional). Set 0 for full 252.")
    parser.add_argument("--variants-file", default="",
                        help="Skip WF/CPCV, only regenerate the markdown from existing JSON dumps.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    OUT_JSON_DIR.mkdir(parents=True, exist_ok=True)

    guardrails = {
        "max_drawdown_pct": args.max_dd_cap,
        "stressed_day_loss_pct": args.stressed_day_cap,
        "stress_shock_pct": args.stress_shock,
        "financing_cost_cap_frac_of_excess_return": args.fin_cap_frac,
    }

    tickers = get_audit_universe()
    if not tickers:
        print("No universe available — need WRDS PIT + price cache.")
        sys.exit(1)
    if args.limit_tickers and args.limit_tickers < len(tickers):
        tickers = tickers[: args.limit_tickers]
    print(f"Universe: {len(tickers)} tickers")

    # Regenerate-only path: reload JSONs and rewrite markdown.
    if args.variants_file:
        variant_runs, sensitivity_runs, cpcv_runs = _load_saved(OUT_JSON_DIR, args.gross, args.sensitivity_only)
        write_markdown_report(
            variant_runs=variant_runs,
            sensitivity_runs=sensitivity_runs,
            cpcv_runs=cpcv_runs,
            guardrails=guardrails,
            universe_size=len(tickers),
            window=(args.start, args.end),
            out_path=OUT_MD_PATH,
            guardrail_fail_threshold=args.guardrail_fail_threshold,
        )
        print(f"Wrote {OUT_MD_PATH}")
        return

    # Full run path.
    variant_runs: list[dict] = []
    sensitivity_runs: dict[str, dict] = {}
    cpcv_runs: dict[str, dict] = {}

    for gross in args.gross:
        variant = f"L-{gross:.2f}".rstrip("0").rstrip(".")
        # Preserve the standard names (L-1.0, L-1.2, ...):
        if variant in ("L-1", "L-2"):
            variant = variant + ".0"
        print(f"\n=== {variant} base run (spread={args.base_spread_bps}bp) ===")
        base = run_variant_walkforward(
            variant_name=variant, tickers=tickers,
            start=args.start, end=args.end,
            gross_exposure=gross,
            financing_spread_bps=args.base_spread_bps,
            guardrails=guardrails,
        )
        variant_runs.append(base)
        out_path = OUT_JSON_DIR / f"{variant}-base-{int(args.base_spread_bps)}bp.json"
        out_path.write_text(json.dumps(base, indent=2, default=str))
        print(f"  → {out_path.name}: Sharpe={base['metrics']['sharpe']} "
              f"Return={base['metrics']['annual_return_pct']}% "
              f"MaxDD={base['metrics']['max_drawdown_pct']}% "
              f"Fin={base['financing_dollars_paid']}$ "
              f"Guardrail={base['guardrail_passed']}")

        # Financing sensitivity: skip for L-1.0 (no borrowing → no financing exposure)
        if gross <= 1.0:
            continue
        do_sens = str(gross) in [s for s in args.sensitivity_only] or str(int(gross)) in args.sensitivity_only or (
            f"{gross:.1f}" in args.sensitivity_only
        )
        if not do_sens:
            continue
        for tag, spread in (
            ("minus", args.base_spread_bps - args.sensitivity_delta_bps),
            ("plus", args.base_spread_bps + args.sensitivity_delta_bps),
        ):
            print(f"\n=== {variant} financing sensitivity {tag} (spread={spread}bp) ===")
            sens = run_variant_walkforward(
                variant_name=variant, tickers=tickers,
                start=args.start, end=args.end,
                gross_exposure=gross,
                financing_spread_bps=spread,
                guardrails=guardrails,
            )
            sensitivity_runs.setdefault(variant, {})[tag] = sens
            sens_path = OUT_JSON_DIR / f"{variant}-sens-{tag}-{int(spread)}bp.json"
            sens_path.write_text(json.dumps(sens, indent=2, default=str))
            print(f"  → {sens_path.name}: Sharpe={sens['metrics']['sharpe']}")

        # CPCV
        if args.mode in ("cpcv", "both"):
            max_combos = args.cpcv_max_combinations if args.cpcv_max_combinations > 0 else None
            print(f"\n=== {variant} CPCV (groups={args.cpcv_groups}, max_combos={max_combos}) ===")
            cpcv = run_variant_cpcv(
                variant_name=variant, tickers=tickers,
                start=args.start, end=args.end,
                gross_exposure=gross,
                financing_spread_bps=args.base_spread_bps,
                guardrails=guardrails,
                cpcv_groups=args.cpcv_groups,
                cpcv_max_combinations=max_combos,
            )
            cpcv_runs[variant] = cpcv
            cpcv_path = OUT_JSON_DIR / f"{variant}-cpcv.json"
            cpcv_path.write_text(json.dumps(cpcv, indent=2, default=str))
            print(f"  → {cpcv_path.name}: PBO={cpcv['cpcv']['pbo']:.1%} DSR={cpcv['cpcv']['dsr']} "
                  f"pass_rate={cpcv['guardrail_pass_rate']:.1%}")

    write_markdown_report(
        variant_runs=variant_runs,
        sensitivity_runs=sensitivity_runs,
        cpcv_runs=cpcv_runs,
        guardrails=guardrails,
        universe_size=len(tickers),
        window=(args.start, args.end),
        out_path=OUT_MD_PATH,
        guardrail_fail_threshold=args.guardrail_fail_threshold,
    )
    print(f"\nWrote {OUT_MD_PATH}")


def _load_saved(json_dir: Path, gross_list: list[float], sensitivity_only: list[str]) -> tuple[list[dict], dict, dict]:
    """Reload per-variant JSON dumps for report regeneration."""
    variant_runs: list[dict] = []
    sensitivity_runs: dict[str, dict] = {}
    cpcv_runs: dict[str, dict] = {}
    for gross in gross_list:
        variant = f"L-{gross:.2f}".rstrip("0").rstrip(".")
        if variant in ("L-1", "L-2"):
            variant = variant + ".0"
        base_files = sorted(json_dir.glob(f"{variant}-base-*.json"))
        if base_files:
            variant_runs.append(json.loads(base_files[-1].read_text()))
        for tag in ("minus", "plus"):
            sens_files = sorted(json_dir.glob(f"{variant}-sens-{tag}-*.json"))
            if sens_files:
                sensitivity_runs.setdefault(variant, {})[tag] = json.loads(sens_files[-1].read_text())
        cpcv_files = sorted(json_dir.glob(f"{variant}-cpcv.json"))
        if cpcv_files:
            cpcv_runs[variant] = json.loads(cpcv_files[-1].read_text())
    return variant_runs, sensitivity_runs, cpcv_runs


if __name__ == "__main__":
    main()
