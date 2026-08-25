"""Re-judge signal IC significance with overlap-honest statistics.

Reads an ic-results.json produced by scripts/run_audit_ic.py (must contain
the raw "ic_series" field) and, for every signal x horizon:

  * naive t        — what the harness reported historically (inflated under
                     overlap x signal persistence; see
                     docs/audit/2026-08-25-hac-sharpe-validation.md)
  * HAC t          — Newey-West corrected (quant.ic_stats)
  * IC lag-1 rho   — measured persistence of the IC series; the naive t is
                     only trustworthy when this is ~0
  * MBB p-value    — moving-block bootstrap of the centered IC series, which
                     respects each signal's actual dependence structure with
                     no distributional assumption
  * verdict        — SIGNIFICANT / MARGINAL / NO_SIGNAL (+ _WRONG_SIGN),
                     driven by the MBB p-value

Usage:
    python3 scripts/rejudge_ic_signals.py --in docs/audit/2026-08-25-rejudge/ic-results.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from quant.ic_stats import newey_west_tstat  # noqa: E402

MONTHS_PER_HORIZON = {"1M": 1, "3M": 3, "6M": 6, "12M": 12}
N_BOOT = 4000


def lag_autocorr(x: np.ndarray, lag: int) -> float:
    if len(x) <= lag + 1:
        return float("nan")
    a, b = x[:-lag], x[lag:]
    if a.std() < 1e-12 or b.std() < 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def mbb_pvalue(x: np.ndarray, overlap: int, n_boot: int = N_BOOT, seed: int = 0) -> float:
    """Moving-block bootstrap p-value for H0: mean == 0.

    Blocks of length ~2x the overlap preserve the serial dependence of the
    IC series; the series is centered so resampled means are draws from the
    null. p = P(|bootstrap mean| >= |observed mean|).
    """
    rng = np.random.default_rng(seed)
    n = len(x)
    obs = x.mean()
    centered = x - obs
    b = max(3, min(n // 2, 2 * overlap))
    n_blocks = math.ceil(n / b)
    starts = rng.integers(0, n - b + 1, size=(n_boot, n_blocks))
    # build all bootstrap series at once: (n_boot, n_blocks*b)
    idx = starts[:, :, None] + np.arange(b)[None, None, :]
    samples = centered[idx.reshape(n_boot, -1)[:, :n]]
    boot_means = samples.mean(axis=1)
    return float((np.abs(boot_means) >= abs(obs)).mean())


def verdict(mean_ic: float, p: float) -> str:
    if p < 0.05:
        base = "SIGNIFICANT"
    elif p < 0.15:
        base = "MARGINAL"
    else:
        base = "NO_SIGNAL"
    if base != "NO_SIGNAL" and mean_ic < 0:
        base += "_WRONG_SIGN"
    return base


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", default=None)
    args = ap.parse_args()

    data = json.load(open(args.inp))
    if "ic_series" not in data:
        sys.exit("input JSON has no 'ic_series' — regenerate with the updated run_audit_ic.py")

    old_verdicts = {
        (h, e["signal"]): e.get("verdict", "?")
        for h, entries in data["ic"].items()
        for e in entries
    }

    lines = ["# IC significance re-judgment (overlap-honest)", ""]
    lines.append(f"Source: `{args.inp}`  |  MBB resamples: {N_BOOT}")
    lines.append("")
    rows_out = {}
    for h, series_by_signal in data["ic_series"].items():
        overlap = MONTHS_PER_HORIZON[h]
        lines.append(f"## Horizon {h} (overlap {overlap})")
        lines.append("")
        lines.append(
            "| signal | n | mean IC | naive t | HAC t | IC lag-1 ρ | MBB p | old verdict | new verdict |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|")
        rows_out[h] = {}
        for sig, d in sorted(series_by_signal.items()):
            x = np.asarray(d["ics"], dtype=float)
            x = x[np.isfinite(x)]
            n = len(x)
            if n < 12:
                continue
            mean_ic = x.mean()
            naive_t = mean_ic / (x.std(ddof=1) / np.sqrt(n))
            hac_t, lag_used = newey_west_tstat(x, horizon_over_step=overlap)
            rho1 = lag_autocorr(x, 1)
            p = mbb_pvalue(x, overlap)
            v = verdict(mean_ic, p)
            old_v = old_verdicts.get((h, sig), "?")
            flag = " ⬇" if ("SIGNIF" in str(old_v) and "SIGNIF" not in v) else ""
            lines.append(
                f"| {sig} | {n} | {mean_ic:+.4f} | {naive_t:+.2f} | {hac_t:+.2f} "
                f"| {rho1:+.2f} | {p:.3f} | {old_v} | **{v}**{flag} |"
            )
            rows_out[h][sig] = {
                "n": n,
                "mean_ic": round(float(mean_ic), 5),
                "naive_t": round(float(naive_t), 3),
                "hac_t": round(float(hac_t), 3),
                "hac_lag": int(lag_used),
                "ic_lag1_autocorr": round(float(rho1), 3) if np.isfinite(rho1) else None,
                "mbb_p": round(p, 4),
                "old_verdict": old_v,
                "new_verdict": v,
            }
        lines.append("")

    report = "\n".join(lines)
    print(report)
    if args.out:
        with open(args.out, "w") as f:
            f.write(report + "\n")
        json_out = os.path.splitext(args.out)[0] + ".json"
        with open(json_out, "w") as f:
            json.dump(rows_out, f, indent=2)
        print(f"\n[write] {args.out}\n[write] {json_out}")


if __name__ == "__main__":
    main()
