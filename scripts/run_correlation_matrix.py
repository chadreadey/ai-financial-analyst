"""
Audit Session 2: cross-signal correlation matrix (extended IC harness).

Computes pairwise Spearman rank correlation between signal scores at every
monthly rebalance, then averages across dates. Produces a square
mean-correlation and std-correlation matrix.

Walk-forward only (NO CPCV).

Universe / dates / signals are aligned with `scripts/run_audit_ic.py` so
the correlation findings are directly comparable to the IC findings in
`docs/audit/session-2/ic-summary.md`.

Outputs:
  - docs/audit/session-2/correlation-matrix.json  (numeric data)
  - docs/audit/session-2/correlation-matrix.md    (table + interpretation)

Signals included:
  Fundamental: erm, sue, analyst_dispersion, quality_score, price_momentum
  Baselines:   piotroski, qmj, hml_bm
  Technical:   obv_trend  (cross-sectional baseline from compute_signal_vector)

Excluded: insider_mspr (0% coverage — Finnhub MSPR cache not on disk;
documented in the IC summary, INSUFFICIENT verdict).

Excluded: institutional_flow (FMP cache may be partially populated; we
include only signals with documented IC-1 coverage to keep the matrix
honest).

Usage:
    python3 scripts/run_correlation_matrix.py
    python3 scripts/run_correlation_matrix.py --limit-tickers 50
    python3 scripts/run_correlation_matrix.py --start 2018-01-01 --end 2024-12-31
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import sys
import time
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd

# Make `quant` importable when running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.wrds_store import WRDSPointInTimeStore  # noqa: E402
from quant.fundamental_provider import WRDSFundamentalProvider  # noqa: E402
from quant.factor_baselines import (  # noqa: E402
    compute_piotroski_score,
    compute_qmj_score,
    compute_hml_score,
)
from quant.earnings_signals import (  # noqa: E402
    compute_erm_score,
    compute_sue_score,
    compute_dispersion_score,
)
from quant.additional_signals import (  # noqa: E402
    compute_quality_scores,
    compute_price_momentum_scores,
)
from quant.signals import compute_signal_vector  # noqa: E402

logger = logging.getLogger(__name__)


# ── Configuration ───────────────────────────────────────────────────────

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICE_CACHE_DIR = os.path.join(REPO_ROOT, ".price_cache")
WRDS_DB_PATH = os.path.join(REPO_ROOT, ".wrds_pit.db")
OUT_DIR = os.path.join(REPO_ROOT, "docs", "audit", "session-2")

# Order matters here — it controls row/column order in the output matrix.
SIGNAL_NAMES = [
    "erm",
    "sue",
    "analyst_dispersion",
    "quality_score",
    "price_momentum",
    "piotroski",
    "qmj",
    "hml_bm",
    "obv_trend",
]


def load_universe_prices(tickers: list[str]) -> dict[str, pd.DataFrame]:
    data = {}
    for t in tickers:
        path = os.path.join(PRICE_CACHE_DIR, f"{t}.csv")
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_csv(path, parse_dates=["date"], index_col="date")
            df.index = df.index.normalize()
            data[t] = df
        except Exception as exc:
            logger.debug("price load failed for %s: %s", t, exc)
    return data


def get_wrds_universe() -> list[str]:
    conn = sqlite3.connect(WRDS_DB_PATH)
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM compustat_quarterly ORDER BY ticker"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def generate_monthly_rebalance_dates(
    start: pd.Timestamp, end: pd.Timestamp, trading_dates: pd.DatetimeIndex,
) -> list[pd.Timestamp]:
    candidates = pd.date_range(start, end, freq="BME")
    out = []
    for c in candidates:
        mask = trading_dates <= c
        if mask.any():
            out.append(trading_dates[mask][-1])
    return sorted(set(out))


def compute_signal_panel(
    universe_data: dict[str, pd.DataFrame],
    as_of: pd.Timestamp,
    wrds_store: WRDSPointInTimeStore,
    provider: WRDSFundamentalProvider,
    lookback_days: int = 252,
) -> Optional[pd.DataFrame]:
    """Compute one row per ticker, one column per signal, NaN-aware."""
    as_of_d = as_of.date() if hasattr(as_of, "date") else as_of
    tickers = list(universe_data.keys())

    # Cross-sectional precompute
    momentum_scores = compute_price_momentum_scores(universe_data, as_of)
    quality_scores = compute_quality_scores(tickers, provider, as_of_d)

    rows = {}
    for t in tickers:
        df = universe_data[t]
        avail = df[df.index <= as_of]
        if len(avail) < 60:
            continue
        row = {sig: float("nan") for sig in SIGNAL_NAMES}

        # Per-ticker fundamentals
        try:
            s, m = compute_erm_score(t, provider, as_of_date=as_of_d)
            if "error" not in m:
                row["erm"] = float(s)
        except Exception:
            pass
        try:
            s, m = compute_sue_score(t, provider, as_of_date=as_of_d)
            if "error" not in m:
                row["sue"] = float(s)
        except Exception:
            pass
        try:
            s, m = compute_dispersion_score(t, provider, as_of_date=as_of_d)
            if "error" not in m:
                row["analyst_dispersion"] = float(s)
        except Exception:
            pass

        if t in quality_scores:
            row["quality_score"] = float(quality_scores[t])
        if t in momentum_scores:
            row["price_momentum"] = float(momentum_scores[t])

        # Baselines
        try:
            p = compute_piotroski_score(t, as_of_d, wrds_store)
            if p is not None:
                row["piotroski"] = float(p)
        except Exception:
            pass
        try:
            q = compute_qmj_score(t, as_of_d, wrds_store)
            if q is not None:
                row["qmj"] = float(q)
        except Exception:
            pass
        try:
            price = float(avail.iloc[-1]["close"]) if len(avail) else None
            if price and price > 0:
                h = compute_hml_score(t, as_of_d, wrds_store, price=price)
                if h is not None:
                    row["hml_bm"] = float(h)
        except Exception:
            pass

        # Technical baseline (OBV trend)
        try:
            window = avail.tail(lookback_days)
            sv = compute_signal_vector(
                close=window["close"],
                volume=window["volume"],
                high=window["high"],
                low=window["low"],
            )
            row["obv_trend"] = float(sv.obv_trend.score)
        except Exception:
            pass

        rows[t] = row

    if not rows:
        return None
    return pd.DataFrame.from_dict(rows, orient="index")


def correlation_at_date(panel: pd.DataFrame, signal_names: list[str]) -> Optional[np.ndarray]:
    """Pairwise Spearman rho on a single date's panel. NaN-aware (pandas)."""
    sub = panel[signal_names]
    # Need at least 10 non-NaN pairs for a meaningful rank correlation
    if sub.dropna(how="all").shape[0] < 10:
        return None
    corr = sub.corr(method="spearman").values
    return corr


def run(
    start: str,
    end: str,
    limit_tickers: Optional[int],
    out_dir: str,
) -> dict:
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)

    wrds_tickers = set(get_wrds_universe())
    price_tickers = {f.replace(".csv", "")
                     for f in os.listdir(PRICE_CACHE_DIR) if f.endswith(".csv")}
    universe = sorted(wrds_tickers & price_tickers)
    print(f"[universe] WRDS={len(wrds_tickers)}  price-cache={len(price_tickers)}  "
          f"intersection={len(universe)}")

    if limit_tickers is not None:
        universe = universe[:limit_tickers]
        print(f"[universe] --limit-tickers={limit_tickers} -> {len(universe)} tickers")

    universe_data = load_universe_prices(universe)
    print(f"[load] loaded {len(universe_data)} ticker price series")

    all_idx = pd.DatetimeIndex(sorted(set().union(*[df.index for df in universe_data.values()])))
    rebalance_dates = generate_monthly_rebalance_dates(
        pd.Timestamp(start), pd.Timestamp(end), all_idx,
    )
    # No forward-buffer needed for correlation (no forward returns), but we keep
    # the same date range as the IC run for direct comparability.
    print(f"[dates] {len(rebalance_dates)} monthly rebalance dates")

    store = WRDSPointInTimeStore()
    provider = WRDSFundamentalProvider(store)

    n_sig = len(SIGNAL_NAMES)
    matrices: list[np.ndarray] = []
    used_dates: list[pd.Timestamp] = []
    panel_n: list[int] = []

    for i, d in enumerate(rebalance_dates):
        if i % 12 == 0:
            print(f"[rebalance] {i+1}/{len(rebalance_dates)} {d.date()}")
        panel = compute_signal_panel(universe_data, d, store, provider)
        if panel is None or panel.empty:
            continue
        c = correlation_at_date(panel, SIGNAL_NAMES)
        if c is None:
            continue
        matrices.append(c)
        used_dates.append(d)
        panel_n.append(len(panel))

    if not matrices:
        raise RuntimeError("No correlation matrices computed; aborting.")

    stacked = np.stack(matrices)  # shape (T, S, S)
    mean_corr = np.nanmean(stacked, axis=0)
    std_corr = np.nanstd(stacked, axis=0, ddof=1) if stacked.shape[0] > 1 else np.zeros_like(mean_corr)

    # Coverage diagnostics — for each signal, count how many dates had any
    # non-NaN value contributing to the correlation row.
    sig_coverage = {}
    for i, sig in enumerate(SIGNAL_NAMES):
        # Count rebalance dates where this signal had a finite mean-corr row
        nonnan_dates = sum(1 for m in matrices if not np.all(np.isnan(m[i, :])))
        sig_coverage[sig] = round(100.0 * nonnan_dates / len(matrices), 1)

    # Pair-wise statistics (only off-diagonal upper triangle)
    pairs = []
    for i in range(n_sig):
        for j in range(i + 1, n_sig):
            mc = mean_corr[i, j]
            sc = std_corr[i, j]
            if math.isnan(mc):
                continue
            ratio = (sc / abs(mc)) if abs(mc) > 1e-6 else float("nan")
            pairs.append({
                "a": SIGNAL_NAMES[i],
                "b": SIGNAL_NAMES[j],
                "mean": round(float(mc), 4),
                "std": round(float(sc), 4),
                "abs_mean": round(abs(float(mc)), 4),
                "instability_ratio": round(float(ratio), 3) if not math.isnan(ratio) else None,
            })

    # Effective dimensionality (entropy of the eigenvalue spectrum)
    sym = np.nan_to_num(mean_corr, nan=0.0)
    eigvals = np.linalg.eigvalsh((sym + sym.T) / 2)
    eigvals = eigvals[eigvals > 1e-9]
    norm_eig = eigvals / eigvals.sum() if eigvals.size else np.array([])
    entropy = -np.sum(norm_eig * np.log(norm_eig + 1e-12)) if norm_eig.size else 0.0
    eff_dim = float(np.exp(entropy))

    out = {
        "meta": {
            "start": start,
            "end": end,
            "universe_size": len(universe_data),
            "n_rebalance_dates": len(used_dates),
            "signals": SIGNAL_NAMES,
            "method": "spearman",
            "walk_forward_only": True,
            "cpcv_used": False,
            "runtime_seconds": round(time.time() - t0, 1),
            "wrds_tickers_total": len(wrds_tickers),
            "price_cache_tickers_total": len(price_tickers),
            "intersection_universe_total": len(wrds_tickers & price_tickers),
            "limit_tickers": limit_tickers,
            "exclusions": {
                "insider_mspr": "0% coverage (Finnhub MSPR cache not on disk).",
                "institutional_flow": "Excluded for honesty — partial cache only.",
            },
        },
        "signal_coverage_pct": sig_coverage,
        "mean_correlation": pd.DataFrame(
            mean_corr, index=SIGNAL_NAMES, columns=SIGNAL_NAMES,
        ).round(4).to_dict(),
        "std_correlation": pd.DataFrame(
            std_corr, index=SIGNAL_NAMES, columns=SIGNAL_NAMES,
        ).round(4).to_dict(),
        "pairs": pairs,
        "effective_dimensionality": round(eff_dim, 2),
        "nominal_signals": n_sig,
    }

    json_path = os.path.join(out_dir, "correlation-matrix.json")
    with open(json_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"[write] {json_path}")

    md_path = os.path.join(out_dir, "correlation-matrix.md")
    with open(md_path, "w") as f:
        f.write(render_markdown(out, mean_corr, std_corr))
    print(f"[write] {md_path}")

    print(f"[done] {round(time.time() - t0, 1)}s")
    return out


def render_markdown(
    res: dict, mean_corr: np.ndarray, std_corr: np.ndarray,
) -> str:
    meta = res["meta"]
    sigs = SIGNAL_NAMES
    n = len(sigs)
    pairs = res["pairs"]

    # Sorted views
    sorted_by_abs = sorted(pairs, key=lambda p: -p["abs_mean"])
    high_corr = [p for p in sorted_by_abs if p["abs_mean"] > 0.5]
    valid_inst = [p for p in pairs if p.get("instability_ratio") is not None
                  and p["abs_mean"] >= 0.05]
    sorted_by_inst = sorted(valid_inst, key=lambda p: -p["instability_ratio"])

    L = []
    L.append("# Audit Session 2 — Cross-Signal Correlation Matrix")
    L.append("")
    L.append(f"**Generated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  ")
    L.append(
        f"**Window**: {meta['start']} → {meta['end']}  "
        f"**Universe**: {meta['universe_size']} tickers (WRDS ∩ price-cache)  "
    )
    L.append(
        f"**Rebalance dates**: {meta['n_rebalance_dates']}  "
        f"**Method**: pairwise Spearman rank correlation, time-averaged.  "
        f"**Runtime**: {meta['runtime_seconds']}s"
    )
    L.append("")
    L.append(
        f"**Effective dimensionality**: {res['effective_dimensionality']} "
        f"(of {res['nominal_signals']} nominal signals)"
    )
    L.append("")

    # Exclusions
    L.append("## Exclusions")
    L.append("")
    for k, v in meta["exclusions"].items():
        L.append(f"- `{k}` — {v}")
    L.append("")

    # Coverage
    L.append("## Per-Signal Coverage (rebalances with ≥1 non-NaN value)")
    L.append("")
    L.append("| Signal | % of rebalance dates with data |")
    L.append("|---|---:|")
    for s in sigs:
        L.append(f"| `{s}` | {res['signal_coverage_pct'][s]}% |")
    L.append("")

    # Mean correlation matrix
    L.append("## Mean Spearman Rank Correlation (time-averaged)")
    L.append("")
    header_cells = ["    "] + [f"`{s[:10]}`" for s in sigs]
    L.append("| " + " | ".join(header_cells) + " |")
    sep_cells = ["---"] + ["---:" for _ in sigs]
    L.append("| " + " | ".join(sep_cells) + " |")
    for i, s in enumerate(sigs):
        cells = [f"**`{s}`**"]
        for j in range(n):
            v = mean_corr[i, j]
            if math.isnan(v):
                cells.append("n/a")
            else:
                marker = "*" if (i != j and abs(v) > 0.5) else ""
                cells.append(f"{v:+.2f}{marker}")
        L.append("| " + " | ".join(cells) + " |")
    L.append("")
    L.append("`*` = |ρ| > 0.50 (redundancy candidate)")
    L.append("")

    # Std correlation matrix
    L.append("## Std-Dev of Correlation Across Dates")
    L.append("")
    L.append("| " + " | ".join(header_cells) + " |")
    L.append("| " + " | ".join(sep_cells) + " |")
    for i, s in enumerate(sigs):
        cells = [f"**`{s}`**"]
        for j in range(n):
            v = std_corr[i, j]
            if math.isnan(v):
                cells.append("n/a")
            else:
                cells.append(f"{v:.2f}")
        L.append("| " + " | ".join(cells) + " |")
    L.append("")

    # Top 5 highest |corr| pairs
    L.append("## Top 5 Highest |corr| Pairs")
    L.append("")
    L.append("| Rank | Pair | mean ρ | std ρ | std / |mean| |")
    L.append("|---:|---|---:|---:|---:|")
    for k, p in enumerate(sorted_by_abs[:5], 1):
        ratio = p.get("instability_ratio")
        ratio_str = f"{ratio:.2f}" if ratio is not None else "n/a"
        L.append(
            f"| {k} | `{p['a']}` ↔ `{p['b']}` | {p['mean']:+.3f} | "
            f"{p['std']:.3f} | {ratio_str} |"
        )
    L.append("")

    # Redundancy candidates (|mean ρ| > 0.5)
    L.append("## Redundancy Candidates (|mean ρ| > 0.5)")
    L.append("")
    if not high_corr:
        L.append(
            "_No pairs exceed the 0.5 redundancy threshold._ The signal "
            "stack is well-diversified at the cross-sectional level — "
            "**no signal is the same close-price signal measured twice**, "
            "and effective dimensionality of "
            f"{res['effective_dimensionality']:.1f}/{res['nominal_signals']} "
            "confirms the stack is genuinely multi-dimensional."
        )
    else:
        L.append("| Pair | mean ρ | std ρ | Suggested treatment |")
        L.append("|---|---:|---:|---|")
        for p in high_corr:
            suggest = _suggest_treatment(p["a"], p["b"], p["mean"], p["std"])
            L.append(
                f"| `{p['a']}` ↔ `{p['b']}` | {p['mean']:+.3f} | "
                f"{p['std']:.3f} | {suggest} |"
            )
    L.append("")

    # Top 5 most UNSTABLE pairs (high std / |mean|)
    L.append("## Top 5 Most Unstable Pairs (divergence-as-signal candidates)")
    L.append("")
    L.append(
        "Pairs whose correlation has high variability across dates relative "
        "to its average. Stable redundancy (low std) means the same thing "
        "is being measured twice; unstable redundancy (high std) means the "
        "RELATIONSHIP itself moves through time and the divergence between "
        "the two signals could be a separate alpha source."
    )
    L.append("")
    L.append("| Rank | Pair | mean ρ | std ρ | std / |mean| |")
    L.append("|---:|---|---:|---:|---:|")
    for k, p in enumerate(sorted_by_inst[:5], 1):
        ratio = p["instability_ratio"]
        L.append(
            f"| {k} | `{p['a']}` ↔ `{p['b']}` | {p['mean']:+.3f} | "
            f"{p['std']:.3f} | {ratio:.2f} |"
        )
    L.append("")
    L.append(
        "**Filter**: only pairs with |mean ρ| ≥ 0.05 are included (otherwise "
        "ratio is dominated by floating-point noise on near-zero correlations)."
    )
    L.append("")

    # Targeted comparisons asked for in the spec
    L.append("## Targeted Pair Discussion")
    L.append("")

    def _pair_value(a: str, b: str) -> tuple[Optional[float], Optional[float]]:
        if a not in sigs or b not in sigs:
            return None, None
        i = sigs.index(a); j = sigs.index(b)
        m = mean_corr[i, j]; s = std_corr[i, j]
        return (None if math.isnan(m) else float(m),
                None if math.isnan(s) else float(s))

    targeted = [
        ("qmj", "quality_score",
         "Both quality factors. QMJ profitability pillar uses gross-profit/assets; "
         "quality_score uses gross margin + ROIC. Likely to overlap meaningfully."),
        ("erm", "sue",
         "Both earnings-based but different mechanisms (consensus revisions vs "
         "actual quarterly surprise). Should be moderately correlated, not "
         "redundant."),
        ("piotroski", "qmj",
         "Both fundamental quality formulations. Piotroski is a 9-binary score "
         "across profitability/leverage/efficiency; QMJ is z-scored across four "
         "pillars. Cross-sectionally these often disagree."),
        ("price_momentum", "erm",
         "Price momentum vs earnings revisions — testing whether revisions "
         "front-run price (or vice versa)."),
        ("price_momentum", "qmj",
         "Momentum vs quality — should be near-zero (orthogonal academic factors)."),
        ("price_momentum", "obv_trend",
         "Both technical, but OBV adds volume. Should be modestly correlated."),
        ("hml_bm", "qmj",
         "Value (HML) vs quality (QMJ) — academic factor stack should show "
         "small or negative correlation."),
    ]
    L.append("| Pair | mean ρ | std ρ | Comment |")
    L.append("|---|---:|---:|---|")
    for a, b, comment in targeted:
        m, s = _pair_value(a, b)
        if m is None:
            L.append(f"| `{a}` ↔ `{b}` | n/a | n/a | {comment} |")
        else:
            verdict_seed = ""
            if abs(m) > 0.5:
                verdict_seed = " **REDUNDANCY CANDIDATE.**"
            elif abs(m) > 0.3:
                verdict_seed = " Moderate overlap."
            elif abs(m) > 0.1:
                verdict_seed = " Mildly related."
            else:
                verdict_seed = " ~Orthogonal."
            L.append(f"| `{a}` ↔ `{b}` | {m:+.3f} | {s:.3f} | "
                     f"{comment}{verdict_seed} |")
    L.append("")

    # Methodology
    L.append("## Methodology")
    L.append("")
    L.append("- **Walk-forward only**, NO CPCV.")
    L.append(
        "- Monthly rebalance dates (last trading day of each month), "
        "matching `scripts/run_audit_ic.py`."
    )
    L.append(
        "- At each date, every signal is scored cross-sectionally with "
        "missing values propagated as **NaN** (never silently zeroed — see "
        "`project_silent_zeros` memory rule)."
    )
    L.append(
        "- Pairwise Spearman rank correlation per date (pandas `.corr(method='spearman')` "
        "is NaN-aware: pairs with NaN on either side are dropped)."
    )
    L.append(
        "- Mean and std are taken across the rebalance dates."
    )
    L.append(
        "- Effective dimensionality = `exp(-Σ pᵢ log pᵢ)` where `p` is "
        "the normalized eigenvalue spectrum of the mean-correlation matrix. "
        "A value near `nominal_signals` ⇒ orthogonal stack; a value much "
        "smaller ⇒ multiple signals collapse onto a single principal axis."
    )
    L.append("")

    return "\n".join(L)


def _suggest_treatment(a: str, b: str, mean_rho: float, std_rho: float) -> str:
    """Heuristic suggestion: keep+IC-weight, residualize, or divergence-signal."""
    instability = std_rho / abs(mean_rho) if abs(mean_rho) > 1e-6 else float("inf")
    if instability > 1.5:
        return ("(c) Unstable — divergence between the two could become a "
                "separate signal in Session 3.")
    if abs(mean_rho) > 0.7:
        return ("(b) Strongly redundant — replace one with the residual of "
                "the other, or drop the lower-IC member.")
    return ("(a) Keep both, IC-weight the composite — overlap is real but "
            "not crippling.")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--start", default="2015-01-01")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument("--limit-tickers", type=int, default=None)
    p.add_argument("--out-dir", default=OUT_DIR)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    run(
        start=args.start,
        end=args.end,
        limit_tickers=args.limit_tickers,
        out_dir=args.out_dir,
    )


if __name__ == "__main__":
    main()
