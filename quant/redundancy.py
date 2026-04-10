"""
Signal redundancy diagnostics.

Phase 0 of the Signal Stack Stress Test:
  0.1 — Cross-sectional signal rank correlation matrix
  0.2 — Fama-MacBeth incremental IC
  0.3 — Factor attribution (FF5 + Momentum)

These tests determine whether the signal stack has genuine diversification
or is just the same close-price signal measured 4 different ways.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

from quant.signals import compute_signal_vector

logger = logging.getLogger(__name__)

SIGNAL_NAMES = [
    "obv_trend",
]


def compute_signal_scores_at_date(
    universe_data: dict[str, pd.DataFrame],
    as_of_date: pd.Timestamp,
    lookback_days: int = 252,
) -> Optional[pd.DataFrame]:
    """
    Compute all signal scores cross-sectionally at a single date.

    Returns DataFrame with tickers as rows and signal names as columns.
    Returns None if fewer than 5 tickers have valid signals.
    """
    rows = {}
    for ticker, df in universe_data.items():
        available = df[df.index <= as_of_date]
        if len(available) < 60:
            continue
        window = available.tail(lookback_days)
        try:
            sv = compute_signal_vector(
                close=window["close"],
                volume=window["volume"],
                high=window["high"],
                low=window["low"],
            )
            rows[ticker] = {
                "sma_trend": sv.sma_trend.score,
                "mean_reversion_z": sv.mean_reversion_z.score,
                "bollinger_pctb": sv.bollinger_pctb.score,
                "rsi": sv.rsi.score,
                "obv_trend": sv.obv_trend.score,
                "high_52w": sv.high_52w.score,
            }
        except Exception:
            continue

    if len(rows) < 5:
        return None

    return pd.DataFrame.from_dict(rows, orient="index")


def compute_signal_correlation_matrix(
    universe_data: dict[str, pd.DataFrame],
    rebalance_dates: list[pd.Timestamp],
    lookback_days: int = 252,
    method: str = "spearman",
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Compute time-averaged pairwise signal correlation matrix.

    At each rebalance date, compute cross-sectional signal scores for all
    tickers, then compute pairwise Spearman rank correlation. Average
    across all dates.

    Args:
        universe_data: {ticker: DataFrame} with price/volume data
        rebalance_dates: Dates at which to compute signals
        lookback_days: Price history lookback
        method: "spearman" or "pearson"

    Returns:
        (mean_corr_matrix, std_corr_matrix, diagnostics_dict)
    """
    n_signals = len(SIGNAL_NAMES)
    all_corr_matrices = []
    n_tickers_per_date = []
    dates_used = []

    for date in rebalance_dates:
        scores_df = compute_signal_scores_at_date(universe_data, date, lookback_days)
        if scores_df is None:
            continue

        # Compute pairwise correlation
        if method == "spearman":
            corr = scores_df[SIGNAL_NAMES].corr(method="spearman")
        else:
            corr = scores_df[SIGNAL_NAMES].corr(method="pearson")

        all_corr_matrices.append(corr.values)
        n_tickers_per_date.append(len(scores_df))
        dates_used.append(date)

    if not all_corr_matrices:
        return pd.DataFrame(), pd.DataFrame(), {"error": "no valid dates"}

    # Average across time
    stacked = np.array(all_corr_matrices)
    mean_corr = np.nanmean(stacked, axis=0)
    std_corr = np.nanstd(stacked, axis=0)

    mean_df = pd.DataFrame(mean_corr, index=SIGNAL_NAMES, columns=SIGNAL_NAMES)
    std_df = pd.DataFrame(std_corr, index=SIGNAL_NAMES, columns=SIGNAL_NAMES)

    # Diagnostics
    diag = {
        "n_dates": len(dates_used),
        "avg_tickers_per_date": round(np.mean(n_tickers_per_date), 1),
        "min_tickers": min(n_tickers_per_date),
        "max_tickers": max(n_tickers_per_date),
        "date_range": f"{dates_used[0].strftime('%Y-%m-%d')} to {dates_used[-1].strftime('%Y-%m-%d')}",
    }

    # Identify redundant pairs (|rho| > 0.5)
    redundant_pairs = []
    for i in range(n_signals):
        for j in range(i + 1, n_signals):
            rho = mean_corr[i, j]
            if abs(rho) > 0.5:
                redundant_pairs.append((SIGNAL_NAMES[i], SIGNAL_NAMES[j], round(rho, 3)))
    diag["redundant_pairs"] = redundant_pairs

    # Effective dimensionality: eigenvalue-based
    eigenvalues = np.linalg.eigvalsh(mean_corr)
    eigenvalues = eigenvalues[eigenvalues > 0]  # numerical cleanup
    eigenvalues = eigenvalues / eigenvalues.sum()  # normalize
    effective_dim = float(np.exp(-np.sum(eigenvalues * np.log(eigenvalues + 1e-10))))
    diag["effective_dimensionality"] = round(effective_dim, 2)
    diag["nominal_signals"] = n_signals
    diag["eigenvalues"] = [round(float(e), 4) for e in sorted(eigenvalues, reverse=True)]

    return mean_df, std_df, diag


def compute_forward_returns(
    universe_data: dict[str, pd.DataFrame],
    date: pd.Timestamp,
    forward_days: int = 21,
) -> Optional[pd.Series]:
    """Compute forward N-day returns for each ticker from a given date."""
    returns = {}
    for ticker, df in universe_data.items():
        future = df[df.index > date]
        current = df[df.index <= date]
        if len(current) < 1 or len(future) < forward_days:
            continue
        price_now = float(current.iloc[-1]["close"])
        price_future = float(future.iloc[forward_days - 1]["close"])
        if price_now > 0:
            returns[ticker] = (price_future / price_now - 1)

    if len(returns) < 5:
        return None
    return pd.Series(returns)


def compute_signal_ic_table(
    universe_data: dict[str, pd.DataFrame],
    rebalance_dates: list[pd.Timestamp],
    lookback_days: int = 252,
    forward_days: int = 21,
) -> pd.DataFrame:
    """
    Compute per-signal Information Coefficient (rank IC) at each date.

    Returns DataFrame with dates as rows and signal names as columns,
    where each cell is the Spearman correlation between that signal's
    cross-sectional scores and forward returns.
    """
    rows = []
    for date in rebalance_dates:
        scores_df = compute_signal_scores_at_date(universe_data, date, lookback_days)
        fwd_returns = compute_forward_returns(universe_data, date, forward_days)

        if scores_df is None or fwd_returns is None:
            continue

        common = list(set(scores_df.index) & set(fwd_returns.index))
        if len(common) < 5:
            continue

        row = {"date": date}
        for sig in SIGNAL_NAMES:
            sig_scores = scores_df.loc[common, sig]
            fwd = fwd_returns.loc[common]
            if sig_scores.std() < 1e-8:
                row[sig] = 0.0
            else:
                rho, _ = stats.spearmanr(sig_scores, fwd)
                row[sig] = round(float(rho), 4) if not np.isnan(rho) else 0.0
        rows.append(row)

    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def print_correlation_report(
    mean_corr: pd.DataFrame,
    std_corr: pd.DataFrame,
    diag: dict,
    ic_table: Optional[pd.DataFrame] = None,
) -> str:
    """Format a human-readable correlation and IC report."""
    lines = [
        "",
        "=" * 80,
        "  SIGNAL REDUNDANCY ANALYSIS",
        "=" * 80,
        "",
        f"  Dates analyzed: {diag.get('n_dates', 0)}",
        f"  Date range: {diag.get('date_range', 'N/A')}",
        f"  Avg tickers per date: {diag.get('avg_tickers_per_date', 0)}",
        f"  Effective dimensionality: {diag.get('effective_dimensionality', '?')} "
        f"(nominal: {diag.get('nominal_signals', '?')})",
        "",
    ]

    # Eigenvalues
    eigs = diag.get("eigenvalues", [])
    if eigs:
        lines.append("  Eigenvalue spectrum (normalized):")
        cumulative = 0.0
        for i, e in enumerate(eigs):
            cumulative += e
            bar = "█" * int(e * 60)
            lines.append(f"    PC{i+1}: {e:.3f} (cumul {cumulative:.3f}) {bar}")
        lines.append("")

    # Correlation matrix
    lines.append("  ── Spearman Rank Correlation Matrix (time-averaged) ──")
    lines.append("")

    # Header
    short = {"sma_trend": "SMA", "mean_reversion_z": "MR", "bollinger_pctb": "BB",
             "rsi": "RSI", "obv_trend": "OBV", "high_52w": "52W"}
    header = "         " + "  ".join(f"{short[s]:>6s}" for s in SIGNAL_NAMES)
    lines.append(f"  {header}")
    lines.append(f"  {'-' * len(header)}")

    for row_sig in SIGNAL_NAMES:
        vals = []
        for col_sig in SIGNAL_NAMES:
            v = mean_corr.loc[row_sig, col_sig]
            if row_sig == col_sig:
                vals.append("  1.00")
            else:
                marker = " *" if abs(v) > 0.5 else "  "
                vals.append(f"{v:+.2f}{marker[1]}")

        line = f"  {short[row_sig]:>6s}   " + "  ".join(f"{v:>6s}" for v in vals)
        lines.append(line)

    lines.append("")
    lines.append("  (* = |ρ| > 0.50, flagged as redundant)")

    # Redundant pairs
    pairs = diag.get("redundant_pairs", [])
    if pairs:
        lines.append("")
        lines.append(f"  ── Redundant Pairs ({len(pairs)} found) ──")
        for s1, s2, rho in pairs:
            lines.append(f"    {short[s1]:>5s} ↔ {short[s2]:<5s}: ρ = {rho:+.3f}")
    else:
        lines.append("")
        lines.append("  No redundant pairs found (all |ρ| ≤ 0.50)")

    # IC table
    if ic_table is not None and len(ic_table) > 0:
        lines.append("")
        lines.append("  ── Per-Signal Information Coefficient (rank IC vs 21-day forward returns) ──")
        lines.append("")

        ic_means = ic_table.mean()
        ic_stds = ic_table.std()
        ic_tstats = ic_means / (ic_stds / np.sqrt(len(ic_table))) if len(ic_table) > 1 else ic_means * 0
        ic_pct_pos = (ic_table > 0).mean() * 100

        header2 = f"  {'Signal':<20s} {'Mean IC':>8s} {'Std':>8s} {'t-stat':>8s} {'%pos':>6s} {'Verdict':>12s}"
        lines.append(header2)
        lines.append(f"  {'-' * 70}")

        for sig in SIGNAL_NAMES:
            if sig not in ic_table.columns:
                continue
            m = ic_means[sig]
            s = ic_stds[sig]
            t = ic_tstats[sig] if not np.isnan(ic_tstats[sig]) else 0
            pp = ic_pct_pos[sig]

            if abs(t) >= 2:
                verdict = "SIGNIFICANT" if m > 0 else "SIG (wrong sign)"
            elif abs(t) >= 1.5:
                verdict = "marginal"
            else:
                verdict = "NO SIGNAL"

            lines.append(f"  {short[sig]:<20s} {m:>+8.4f} {s:>8.4f} {t:>8.2f} {pp:>5.0f}% {verdict:>12s}")

        lines.append("")
        lines.append(f"  IC computed across {len(ic_table)} rebalance dates")
        lines.append("  t-stat > 2 = signal has statistically significant predictive power")
        lines.append("  t-stat < 2 = signal adds no cross-sectional information")

    lines.append("")
    lines.append("=" * 80)
    return "\n".join(lines)
