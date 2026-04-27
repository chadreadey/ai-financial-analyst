"""
Signal redundancy diagnostics.

Phase 0 of the Signal Stack Stress Test:
  0.1 — Cross-sectional signal rank correlation matrix
  0.2 — Fama-MacBeth incremental IC
  0.3 — Factor attribution (FF5 + Momentum)

These tests determine whether the signal stack has genuine diversification
or is just the same close-price signal measured 4 different ways.

Audit session 2 (IC-1) extension:
  - Fundamental signals are wired in alongside technical signals so
    `compute_signal_scores_at_date` returns a panel covering the full
    composite. Missing values are propagated as NaN (NOT silent zeros)
    so cross-sectional rank IC is computed only over tickers with
    real data per the `project_silent_zeros` memory rule.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

from quant.signals import compute_signal_vector

logger = logging.getLogger(__name__)

# Technical signals that have always been in the IC harness. Kept as
# the default for the legacy redundancy report (correlation matrix).
TECHNICAL_SIGNAL_NAMES = [
    "obv_trend",
    "institutional_flow",
]

# Fundamental signals wired in by the audit (IC-1). These are the
# fundamental layer that has historically carried weight in the
# composite without ever being individually IC-validated.
FUNDAMENTAL_SIGNAL_NAMES = [
    "erm",                  # earnings revision momentum
    "sue",                  # standardized unexpected earnings
    "analyst_dispersion",   # consensus dispersion (NEGATIVE signal)
    "quality_score",        # ROIC + gross margin blend
    "price_momentum",       # 12-1M classic momentum
    "insider_mspr",         # insider buying/selling
]

# Default IC harness scope used by the audit runner.
SIGNAL_NAMES = TECHNICAL_SIGNAL_NAMES + FUNDAMENTAL_SIGNAL_NAMES


def compute_signal_scores_at_date(
    universe_data: dict[str, pd.DataFrame],
    as_of_date: pd.Timestamp,
    lookback_days: int = 252,
    *,
    wrds_provider=None,
    finnhub_client=None,
    sentiment_cache=None,
    include_fundamentals: bool = True,
) -> Optional[pd.DataFrame]:
    """
    Compute all signal scores cross-sectionally at a single date.

    Returns DataFrame with tickers as rows and signal names as columns.
    Returns None if fewer than 5 tickers have valid signals.

    Signal columns:
        Technical (from compute_signal_vector):
            sma_trend, mean_reversion_z, bollinger_pctb, rsi, obv_trend,
            high_52w
        Cross-sectional add-on:
            institutional_flow (FMP cache, if available)
        Fundamentals (audit IC-1, opt-in via include_fundamentals):
            erm, sue, analyst_dispersion (WRDS IBES via wrds_provider)
            quality_score (WRDS Compustat via wrds_provider)
            price_momentum (price cache only)
            insider_mspr (Finnhub if client/cache provided)

    Missing fundamental values are propagated as NaN per `project_silent_zeros`
    memory rule — never silently zeroed.
    """
    # ── Cross-sectional precompute pass for vectorized signals ─────────
    # Institutional flow (FMP cache)
    inst_flow_scores = {}
    try:
        from quant.institutional_flow import compute_institutional_flow_scores
        from quant.fmp_cache import FMPFundamentalCache
        fmp_cache = FMPFundamentalCache()
        as_of = as_of_date.date() if hasattr(as_of_date, 'date') else as_of_date
        inst_flow_scores = compute_institutional_flow_scores(
            list(universe_data.keys()),
            as_of_date=as_of,
            fmp_cache=fmp_cache,
        )
    except Exception:
        pass

    # Price momentum (cross-sectional, requires the full universe)
    momentum_scores: dict[str, float] = {}
    if include_fundamentals:
        try:
            from quant.additional_signals import compute_price_momentum_scores
            momentum_scores = compute_price_momentum_scores(
                universe_data, as_of_date,
            )
        except Exception as exc:
            logger.debug("price_momentum precompute failed at %s: %s", as_of_date, exc)

    # Quality (per-ticker but via single provider)
    quality_scores: dict[str, float] = {}
    if include_fundamentals and wrds_provider is not None:
        try:
            from quant.additional_signals import compute_quality_scores
            as_of_d = (
                as_of_date.date()
                if hasattr(as_of_date, "date")
                else as_of_date
            )
            quality_scores = compute_quality_scores(
                list(universe_data.keys()),
                wrds_provider,
                as_of_d,
            )
        except Exception as exc:
            logger.debug("quality precompute failed at %s: %s", as_of_date, exc)

    # Insider MSPR (Finnhub cache)
    insider_scores: dict[str, float] = {}
    if include_fundamentals and (finnhub_client is not None or sentiment_cache is not None):
        try:
            from quant.additional_signals import compute_insider_scores
            insider_scores = compute_insider_scores(
                list(universe_data.keys()),
                as_of_date,
                finnhub_client=finnhub_client,
                sentiment_cache=sentiment_cache,
            )
        except Exception as exc:
            logger.debug("insider precompute failed at %s: %s", as_of_date, exc)

    # ── Per-ticker pass ────────────────────────────────────────────────
    as_of_d = as_of_date.date() if hasattr(as_of_date, "date") else as_of_date

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
        except Exception:
            continue

        inst_entry = inst_flow_scores.get(ticker)
        # NaN propagation: institutional_flow is opt-in; missing cache => NaN
        inst_score = float(inst_entry[0]) if inst_entry else float("nan")

        row = {
            "sma_trend": sv.sma_trend.score,
            "mean_reversion_z": sv.mean_reversion_z.score,
            "bollinger_pctb": sv.bollinger_pctb.score,
            "rsi": sv.rsi.score,
            "obv_trend": sv.obv_trend.score,
            "high_52w": sv.high_52w.score,
            "institutional_flow": inst_score,
        }

        if include_fundamentals:
            erm_score = _maybe_score_erm(ticker, wrds_provider, as_of_d)
            sue_score = _maybe_score_sue(ticker, wrds_provider, as_of_d)
            disp_score = _maybe_score_dispersion(ticker, wrds_provider, as_of_d)
            row["erm"] = erm_score
            row["sue"] = sue_score
            row["analyst_dispersion"] = disp_score
            row["quality_score"] = float(
                quality_scores[ticker]
            ) if ticker in quality_scores else float("nan")
            row["price_momentum"] = float(
                momentum_scores[ticker]
            ) if ticker in momentum_scores else float("nan")
            row["insider_mspr"] = float(
                insider_scores[ticker]
            ) if ticker in insider_scores else float("nan")

        rows[ticker] = row

    if len(rows) < 5:
        return None

    return pd.DataFrame.from_dict(rows, orient="index")


def _maybe_score_erm(ticker: str, provider, as_of_d) -> float:
    """Return ERM score or NaN if not computable / no provider."""
    if provider is None:
        return float("nan")
    try:
        from quant.earnings_signals import compute_erm_score
        score, meta = compute_erm_score(ticker, provider, as_of_d)
        if "error" in meta:
            return float("nan")
        return float(score)
    except Exception:
        return float("nan")


def _maybe_score_sue(ticker: str, provider, as_of_d) -> float:
    """Return SUE score or NaN."""
    if provider is None:
        return float("nan")
    try:
        from quant.earnings_signals import compute_sue_score
        score, meta = compute_sue_score(ticker, provider, as_of_d)
        if "error" in meta:
            return float("nan")
        return float(score)
    except Exception:
        return float("nan")


def _maybe_score_dispersion(ticker: str, provider, as_of_d) -> float:
    """Return analyst dispersion score or NaN."""
    if provider is None:
        return float("nan")
    try:
        from quant.earnings_signals import compute_dispersion_score
        score, meta = compute_dispersion_score(ticker, provider, as_of_d)
        if "error" in meta:
            return float("nan")
        return float(score)
    except Exception:
        return float("nan")


def compute_signal_correlation_matrix(
    universe_data: dict[str, pd.DataFrame],
    rebalance_dates: list[pd.Timestamp],
    lookback_days: int = 252,
    method: str = "spearman",
    signal_names: Optional[list[str]] = None,
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
        signal_names: Subset of signals to analyze. Defaults to the
            technical-only set (the legacy behavior). Pass SIGNAL_NAMES
            to include fundamentals.

    Returns:
        (mean_corr_matrix, std_corr_matrix, diagnostics_dict)
    """
    if signal_names is None:
        signal_names = TECHNICAL_SIGNAL_NAMES
    n_signals = len(signal_names)
    all_corr_matrices = []
    n_tickers_per_date = []
    dates_used = []

    for date in rebalance_dates:
        scores_df = compute_signal_scores_at_date(universe_data, date, lookback_days)
        if scores_df is None:
            continue

        # Compute pairwise correlation
        if method == "spearman":
            corr = scores_df[signal_names].corr(method="spearman")
        else:
            corr = scores_df[signal_names].corr(method="pearson")

        all_corr_matrices.append(corr.values)
        n_tickers_per_date.append(len(scores_df))
        dates_used.append(date)

    if not all_corr_matrices:
        return pd.DataFrame(), pd.DataFrame(), {"error": "no valid dates"}

    # Average across time
    stacked = np.array(all_corr_matrices)
    mean_corr = np.nanmean(stacked, axis=0)
    std_corr = np.nanstd(stacked, axis=0)

    mean_df = pd.DataFrame(mean_corr, index=signal_names, columns=signal_names)
    std_df = pd.DataFrame(std_corr, index=signal_names, columns=signal_names)

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
                redundant_pairs.append((signal_names[i], signal_names[j], round(rho, 3)))
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
    signal_names: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Compute per-signal Information Coefficient (rank IC) at each date.

    Returns DataFrame with dates as rows and signal names as columns,
    where each cell is the Spearman correlation between that signal's
    cross-sectional scores and forward returns.

    NaN-aware: rows where the signal is missing for a ticker are dropped
    from that signal's IC computation (only). Cells with too few non-NaN
    observations (<5) are written as NaN, NOT zero, so downstream summary
    stats can drop them honestly.
    """
    if signal_names is None:
        signal_names = TECHNICAL_SIGNAL_NAMES

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
        for sig in signal_names:
            if sig not in scores_df.columns:
                row[sig] = float("nan")
                continue
            sig_scores = scores_df.loc[common, sig]
            fwd = fwd_returns.loc[common]
            # Drop NaN pairs for this signal only
            mask = sig_scores.notna() & fwd.notna()
            sig_scores = sig_scores[mask]
            fwd = fwd[mask]
            if len(sig_scores) < 5 or sig_scores.std() < 1e-8:
                row[sig] = float("nan")
            else:
                rho, _ = stats.spearmanr(sig_scores, fwd)
                row[sig] = round(float(rho), 4) if not np.isnan(rho) else float("nan")
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

    # Use the matrix's own index — works for both technical-only and
    # extended fundamental signal sets.
    sigs_in_report = list(mean_corr.index)
    short = {
        "sma_trend": "SMA", "mean_reversion_z": "MR", "bollinger_pctb": "BB",
        "rsi": "RSI", "obv_trend": "OBV", "high_52w": "52W",
        "institutional_flow": "INST",
        "erm": "ERM", "sue": "SUE", "analyst_dispersion": "DISP",
        "quality_score": "QUAL", "price_momentum": "MOM", "insider_mspr": "MSPR",
    }

    def _label(name: str) -> str:
        return short.get(name, name[:6].upper())

    header = "         " + "  ".join(f"{_label(s):>6s}" for s in sigs_in_report)
    lines.append(f"  {header}")
    lines.append(f"  {'-' * len(header)}")

    for row_sig in sigs_in_report:
        vals = []
        for col_sig in sigs_in_report:
            v = mean_corr.loc[row_sig, col_sig]
            if row_sig == col_sig:
                vals.append("  1.00")
            else:
                marker = " *" if (not np.isnan(v) and abs(v) > 0.5) else "  "
                if np.isnan(v):
                    vals.append("   nan")
                else:
                    vals.append(f"{v:+.2f}{marker[1]}")

        line = f"  {_label(row_sig):>6s}   " + "  ".join(f"{v:>6s}" for v in vals)
        lines.append(line)

    lines.append("")
    lines.append("  (* = |ρ| > 0.50, flagged as redundant)")

    # Redundant pairs
    pairs = diag.get("redundant_pairs", [])
    if pairs:
        lines.append("")
        lines.append(f"  ── Redundant Pairs ({len(pairs)} found) ──")
        for s1, s2, rho in pairs:
            lines.append(f"    {_label(s1):>5s} ↔ {_label(s2):<5s}: ρ = {rho:+.3f}")
    else:
        lines.append("")
        lines.append("  No redundant pairs found (all |ρ| ≤ 0.50)")

    # IC table
    if ic_table is not None and len(ic_table) > 0:
        lines.append("")
        lines.append("  ── Per-Signal Information Coefficient (rank IC vs forward returns) ──")
        lines.append("")

        ic_means = ic_table.mean(skipna=True)
        ic_stds = ic_table.std(skipna=True)
        ic_counts = ic_table.count()
        ic_tstats = ic_means / (ic_stds / np.sqrt(ic_counts.replace(0, np.nan)))
        ic_pct_pos = (ic_table > 0).sum() / ic_counts.replace(0, np.nan) * 100

        header2 = (
            f"  {'Signal':<20s} {'Mean IC':>8s} {'Std':>8s} "
            f"{'N':>5s} {'t-stat':>8s} {'%pos':>6s} {'Verdict':>16s}"
        )
        lines.append(header2)
        lines.append(f"  {'-' * (len(header2) - 2)}")

        for sig in ic_table.columns:
            m = ic_means[sig]
            s = ic_stds[sig]
            n = int(ic_counts[sig])
            t = ic_tstats[sig] if not np.isnan(ic_tstats[sig]) else 0
            pp = ic_pct_pos[sig] if not np.isnan(ic_pct_pos[sig]) else 0

            if n < 5:
                verdict = "INSUFFICIENT"
            elif abs(t) >= 2:
                verdict = "SIGNIFICANT" if m > 0 else "SIG(wrong sign)"
            elif abs(t) >= 1.5:
                verdict = "marginal"
            else:
                verdict = "NO SIGNAL"

            lines.append(
                f"  {_label(sig):<20s} {m:>+8.4f} {s:>8.4f} "
                f"{n:>5d} {t:>8.2f} {pp:>5.0f}% {verdict:>16s}"
            )

        lines.append("")
        lines.append(f"  IC computed across {len(ic_table)} rebalance dates")
        lines.append("  t-stat > 2 = signal has statistically significant predictive power")
        lines.append("  t-stat < 2 = signal adds no cross-sectional information")

    lines.append("")
    lines.append("=" * 80)
    return "\n".join(lines)
