#!/usr/bin/env python3
"""
Statistical-rigor audit runner.

This is the batch side of the stochastic assumption logger
(:mod:`quant.assumption_audit`). It walks the evidence the system has
*already produced* — the IC tables, walk-forward runs and composite-reweight
comparisons under ``docs/audit/`` — and checks the statistical assumptions
that the headline numbers silently rely on, **using whatever information is
available in each artifact**.

It answers, mechanically and reproducibly:

  * Are the IC t-stats computed on overlapping forward-return windows? If so,
    by how much are they inflated, and does the "SIGNIFICANT" verdict survive
    a Newey-West-style deflation?
  * How many strategy configurations were compared before a "winner" was
    chosen, and what does that do to the significance threshold?
  * Are the reported Sharpes backed by enough (independent) observations?
  * Can distributional assumptions (normality of OOS Sharpes, etc.) even be
    verified from what the artifact stored? Where they cannot, that gap is
    logged explicitly rather than passed over.

Usage:
    python3 scripts/run_statistical_rigor_audit.py \
        --audit-dir docs/audit \
        --out docs/audit/session-4-statistical-rigor

Outputs:
    <out>/assumption_log.jsonl   full machine-readable record stream
    <out>/assumption_report.md   human-readable summary + per-artifact detail
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from typing import Any, Optional

# Make ``quant`` importable when run from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.assumption_audit import (  # noqa: E402
    AssumptionLog,
    AssumptionSeverity,
    AssumptionStatus,
)

# Monthly rebalancing is the system's stated cadence (NORTHSTAR / configs).
MONTHLY_STEP_DAYS = 21
# Verdicts the IC tables use to claim a signal "works".
POSITIVE_VERDICTS = {"significant", "marginal"}


def _load_json(path: str) -> Optional[Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        print(f"  ! could not read {path}: {exc}")
        return None


# ── IC tables ────────────────────────────────────────────────────────────
def audit_ic_file(log: AssumptionLog, path: str, data: dict) -> None:
    meta = data.get("meta", {})
    horizons = meta.get("horizons", {})  # {"1M": 21, "3M": 63, ...}
    ic = data.get("ic", {})
    if not isinstance(ic, dict):
        return

    # Count total IC tests in this file for the multiple-testing context.
    n_tests = sum(len(v) for v in ic.values() if isinstance(v, list))

    with log.context(module="ic_table", artifact=os.path.basename(path)):
        # Multiple-testing context for the whole IC sweep.
        log.multiple_testing("ic_sweep", n_trials=n_tests)

        for horizon_label, entries in ic.items():
            if not isinstance(entries, list):
                continue
            horizon_days = horizons.get(horizon_label)
            for e in entries:
                if not isinstance(e, dict):
                    continue
                sig = e.get("signal", "?")
                target = f"{sig}@{horizon_label}"
                n_dates = e.get("n_dates")
                t_stat = e.get("t_stat")
                verdict = str(e.get("verdict", "")).lower()

                with log.context(signal=sig, horizon=horizon_label,
                                 reported_verdict=verdict):
                    log.min_sample(target, n=n_dates, min_n=36,
                                   severity=AssumptionSeverity.MEDIUM)

                    # The central IC finding: overlapping windows.
                    ov = log.overlapping_windows(
                        target, step_days=MONTHLY_STEP_DAYS,
                        horizon_days=horizon_days,
                    )
                    # If overlapping, deflate the reported t-stat and re-judge.
                    if (ov.status == AssumptionStatus.VIOLATED
                            and t_stat is not None
                            and horizon_days):
                        inflation = math.sqrt(horizon_days / MONTHLY_STEP_DAYS)
                        adj_t = float(t_stat) / inflation
                        survives = abs(adj_t) >= 2.0
                        status = (AssumptionStatus.PASS if survives
                                  else AssumptionStatus.VIOLATED)
                        # Only a problem if the artifact *claimed* significance.
                        claimed_sig = verdict in POSITIVE_VERDICTS or abs(float(t_stat)) >= 2.0
                        if claimed_sig and not survives:
                            status = AssumptionStatus.VIOLATED
                        log.record(
                            "ic_significance_survives_overlap", target, status,
                            AssumptionSeverity.HIGH,
                            (f"reported t={float(t_stat):.2f} -> overlap-adjusted "
                             f"t~={adj_t:.2f} (÷{inflation:.2f}); "
                             + ("still significant" if survives
                                else "NO LONGER significant at |t|>=2")),
                            {"reported_t": float(t_stat),
                             "adjusted_t": round(adj_t, 3),
                             "inflation_factor": round(inflation, 3),
                             "reported_verdict": verdict},
                        )

                    # We cannot test normality/independence of the IC series
                    # itself: only summary stats were stored. Log that gap.
                    log.record(
                        "ic_series_available", target,
                        AssumptionStatus.SKIPPED, AssumptionSeverity.LOW,
                        "artifact stored only mean/std/t of IC, not the per-date "
                        "IC series — cannot verify IID/normality of the IC draws",
                        {},
                    )


# ── Walk-forward / composite runs ────────────────────────────────────────
def audit_run_file(log: AssumptionLog, path: str, data: dict) -> None:
    runs = data.get("runs")
    if not isinstance(runs, list):
        return
    window = data.get("window", {})
    with log.context(module="walkforward_run", artifact=os.path.basename(path)):
        for run in runs:
            if not isinstance(run, dict):
                continue
            name = run.get("name", "?")
            metrics = run.get("metrics", {}) or {}
            n_windows = run.get("n_windows")
            yearly = run.get("yearly") or []
            with log.context(run=name):
                sharpe = metrics.get("sharpe")
                total_trades = metrics.get("total_trades")
                win_rate = metrics.get("win_rate_pct")
                alpha = metrics.get("alpha_pct")
                bench_sharpe = metrics.get("benchmark_sharpe")

                log.finite(f"{name}.sharpe", sharpe,
                           severity=AssumptionSeverity.LOW)
                # Independent-year sample behind the Sharpe.
                log.min_sample(f"{name}.sharpe_years", n=len(yearly), min_n=10,
                               severity=AssumptionSeverity.HIGH)
                if n_windows is not None:
                    log.min_sample(f"{name}.wf_windows", n=n_windows, min_n=20,
                                   severity=AssumptionSeverity.MEDIUM)
                log.value_in_range(f"{name}.win_rate", win_rate, 0.0, 100.0,
                                   severity=AssumptionSeverity.LOW)

                # Benchmark Sharpe missing -> information-ratio / relative
                # significance cannot be assessed.
                log.record(
                    "benchmark_comparable", f"{name}.alpha",
                    (AssumptionStatus.SKIPPED if bench_sharpe is None
                     else AssumptionStatus.PASS),
                    AssumptionSeverity.MEDIUM,
                    ("alpha is reported as an arithmetic return spread; "
                     "benchmark Sharpe is null so no risk-adjusted / regression "
                     "alpha (beta-neutral) comparison is possible"
                     if bench_sharpe is None else "benchmark Sharpe present"),
                    {"alpha_pct": alpha, "benchmark_sharpe": bench_sharpe},
                )


def audit_config_selection(log: AssumptionLog, run_files: list[str]) -> None:
    """The composite-reweight comparison chose a production config from many
    result files in the same directory. That is a multiple-comparison over
    configurations — the reason ``compute_deflated_sharpe`` exists."""
    by_dir: dict[str, list[str]] = {}
    for f in run_files:
        by_dir.setdefault(os.path.dirname(f), []).append(f)
    for d, files in by_dir.items():
        # Count distinct configs by reading each file's runs.
        n_configs = 0
        for f in files:
            data = _load_json(f)
            if isinstance(data, dict) and isinstance(data.get("runs"), list):
                n_configs += max(len(data["runs"]), 1)
        if n_configs <= 1:
            continue
        with log.context(module="config_selection", audit_dir=os.path.basename(d)):
            log.multiple_testing(
                "composite_config_selection", n_trials=n_configs,
                severity=AssumptionSeverity.HIGH,
            )


# ── Live demonstration on the canonical metric ───────────────────────────
def demo_live_metric_instrumentation(log: AssumptionLog) -> None:
    """Show the logger operating in-pipeline, not just on artifacts: build a
    synthetic-but-realistic return stream, compute a Sharpe, and check the
    assumptions the Sharpe formula makes (min sample, IID, normality)."""
    try:
        import numpy as np
        import pandas as pd
    except Exception:
        return
    rng = np.random.default_rng(7)
    # Momentum-like returns with positive autocorrelation + fat tails: exactly
    # the case where sqrt(252) annualisation and IID t-stats mislead.
    n = 252
    e = rng.standard_t(4, size=n) * 0.01
    r = np.zeros(n)
    for i in range(1, n):
        r[i] = 0.15 * r[i - 1] + e[i] + 0.0004
    returns = pd.Series(r)

    with log.context(module="metrics.compute_sharpe", scenario="demo"):
        log.min_sample("sharpe_returns", n=len(returns), min_n=252)
        log.nonzero_variance("sharpe_returns", returns)
        log.iid_no_autocorrelation("sharpe_returns", returns)
        log.normality("sharpe_returns", returns)


# ── Report ────────────────────────────────────────────────────────────────
def write_markdown_report(log: AssumptionLog, out_dir: str, jsonl_path: str) -> str:
    counts = log.counts()
    recs = log.records
    lines: list[str] = []
    lines.append("# Statistical-Rigor Assumption Audit — Machine Report\n")
    lines.append(
        "Generated by `scripts/run_statistical_rigor_audit.py`. Each row is an "
        "assumption checked **against the information actually available** in "
        "the system's own evidence artifacts. `SKIPPED` means the information "
        "needed to test the assumption was not present — it is logged, never "
        "silently passed.\n"
    )
    lines.append("## Totals\n")
    lines.append(f"- checks logged: **{len(recs)}**")
    lines.append(f"- pass: **{counts['pass']}**")
    lines.append(f"- VIOLATED: **{counts['violated']}**")
    lines.append(f"- skipped (no info): **{counts['skipped_insufficient_information']}**")
    lines.append(f"- error: **{counts['error']}**")
    lines.append(f"\nFull record stream: `{os.path.basename(jsonl_path)}`\n")

    sev_order = [AssumptionSeverity.CRITICAL, AssumptionSeverity.HIGH,
                 AssumptionSeverity.MEDIUM, AssumptionSeverity.LOW]
    viols = log.violations()
    lines.append("## Violations by severity\n")
    if not viols:
        lines.append("_No violations recorded._\n")
    for sev in sev_order:
        group = [v for v in viols if v.severity == sev]
        if not group:
            continue
        lines.append(f"### {sev.value.upper()} ({len(group)})\n")
        lines.append("| assumption | target | context | finding |")
        lines.append("|---|---|---|---|")
        for v in group:
            ctx = v.context
            ctx_str = ", ".join(
                f"{k}={ctx[k]}" for k in ("artifact", "run", "signal", "horizon")
                if k in ctx
            )
            msg = v.message.replace("|", "\\|")
            lines.append(f"| `{v.assumption}` | `{v.target}` | {ctx_str} | {msg} |")
        lines.append("")

    # Information-gap section: what we could NOT check and why.
    skipped = [r for r in recs if r.status == AssumptionStatus.SKIPPED]
    lines.append("## Information gaps (checks that could not be evaluated)\n")
    lines.append(
        "These are assumptions the audit *tried* to verify but the stored "
        "evidence was insufficient. Each one is a place where the system is "
        "asserting a statistical property it never records enough data to "
        "confirm.\n"
    )
    # De-duplicate by (assumption, message) for readability.
    seen: set[tuple[str, str]] = set()
    for r in skipped:
        key = (r.assumption, r.message)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- `{r.assumption}`: {r.message}")
    lines.append("")

    report_path = os.path.join(out_dir, "assumption_report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return report_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audit-dir", default="docs/audit",
                    help="Directory tree of audit artifacts to scan.")
    ap.add_argument("--out", default="docs/audit/session-4-statistical-rigor",
                    help="Output directory for the assumption log + report.")
    ap.add_argument("--no-demo", action="store_true",
                    help="Skip the live in-pipeline metric demonstration.")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    jsonl_path = os.path.join(args.out, "assumption_log.jsonl")
    # Stream every record to disk as it is logged.
    log = AssumptionLog(jsonl_path=jsonl_path)
    # Truncate any prior stream.
    open(jsonl_path, "w").close()

    all_json = glob.glob(os.path.join(args.audit_dir, "**", "*.json"), recursive=True)
    ic_files, run_files = [], []
    for path in sorted(all_json):
        data = _load_json(path)
        if not isinstance(data, dict):
            continue
        if "ic" in data and isinstance(data.get("ic"), dict):
            ic_files.append(path)
            audit_ic_file(log, path, data)
        if isinstance(data.get("runs"), list):
            run_files.append(path)
            audit_run_file(log, path, data)

    audit_config_selection(log, run_files)

    if not args.no_demo:
        demo_live_metric_instrumentation(log)

    report_path = write_markdown_report(log, args.out, jsonl_path)

    print(log.summary())
    print(f"\nScanned {len(ic_files)} IC artifact(s), {len(run_files)} run artifact(s).")
    print(f"JSONL : {jsonl_path}")
    print(f"Report: {report_path}")
    # Non-zero exit if any CRITICAL/HIGH violation, so this can gate CI.
    high = log.violations(min_severity=AssumptionSeverity.HIGH)
    return 1 if high else 0


if __name__ == "__main__":
    raise SystemExit(main())
