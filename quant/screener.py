"""
Lean-quant screener composite (Phase 1 of PLAN_LEAN_QUANT_STRONG_AI).

Purpose: narrow the investable universe from ~500 tickers to ~50 candidates
using only IC-validated signals. Downstream, AI agents choose the actual
portfolio from the top-50 (Phase 2).

Signal survivors (from docs/audit/session-4/ic-summary.md, 495-ticker
2015-2024 walk-forward):
  - qmj:   1M IC = +0.0245 (t=+2.81)  → KEEP
  - sue:   1M IC = +0.0179 (t=+2.04)  → KEEP
  - erm:   3M IC = +0.0209 (t=+2.27)  → KEEP (marginal at 1M, strong at 3M)

Weights are IC-t-stat derived (`t / sum(t)`) rather than hand-tuned. The
composite's job here is *ranking lift*, not producing alpha on its own —
that responsibility moves to the AI layer downstream. See the strategic
memo `docs/MEMO_2026_07_13_LEAN_QUANT_STRONG_AI.md` for framing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from quant.signals import SignalResult, SignalVector

logger = logging.getLogger(__name__)


# t-stats sourced from the 495-universe IC audit. QMJ+SUE at 1M horizon
# (both pass the |t|>=2 significance bar); ERM taken at 3M where it is
# significant (its 1M t=+1.45 is marginal — using the horizon where it
# actually clears the bar avoids weighting on a coin-flip).
_SIGNIFICANT_T_STATS = {
    "qmj_score": 2.81,
    "sue_earnings_score": 2.04,
    "erm_earnings_score": 2.27,
}


def _t_stat_weights(t_stats: dict[str, float]) -> dict[str, float]:
    total = sum(abs(t) for t in t_stats.values())
    if total <= 0:
        n = len(t_stats)
        return {k: 1.0 / n for k in t_stats}
    return {k: abs(t) / total for k, t in t_stats.items()}


# Screener output feeds AI, not the trade blotter. Weights below reflect
# ranking authority only.
SCREENER_WEIGHTS: dict[str, float] = _t_stat_weights(_SIGNIFICANT_T_STATS)

# For runs where only the four v4-qmj-only signals have been populated on
# the SignalVector (e.g. the existing backtest engine populates
# earnings_rank_score which blends ERM+SUE+dispersion but not the two
# split-out ERM / SUE fields), we fall back to the earnings composite
# under the same total weight.
LEGACY_EARNINGS_FALLBACK_FIELD = "earnings_rank_score"


@dataclass
class Candidate:
    ticker: str
    composite: float
    sector: str
    contributions: dict[str, float]  # signal_name -> weighted contribution


def _get_score(sv: SignalVector, field_name: str) -> float:
    val = getattr(sv, field_name, 0.0)
    if isinstance(val, SignalResult):
        return float(val.score)
    if isinstance(val, (int, float)):
        return float(val)
    return 0.0


def _has_signal(sv: SignalVector, field_name: str) -> bool:
    return abs(_get_score(sv, field_name)) > 1e-12


def compute_screener_composite(
    sv: SignalVector,
    weights: Optional[dict[str, float]] = None,
) -> tuple[float, dict[str, float]]:
    """
    Weighted composite over the IC-validated survivor set.

    Returns:
        (composite, contributions) where contributions maps signal_name ->
        signed weighted contribution (score * weight / total_weight).
    """
    if weights is None:
        weights = SCREENER_WEIGHTS

    total_w = 0.0
    total = 0.0
    contributions: dict[str, float] = {}

    for signal_name, weight in weights.items():
        score = _get_score(sv, signal_name)

        # Absorb split-out ERM/SUE weights into the earnings composite
        # when the split-out fields are absent. Keeps the screener usable
        # with the existing backtest engine's populated fields.
        if (
            not _has_signal(sv, signal_name)
            and signal_name in ("erm_earnings_score", "sue_earnings_score")
            and _has_signal(sv, LEGACY_EARNINGS_FALLBACK_FIELD)
        ):
            score = _get_score(sv, LEGACY_EARNINGS_FALLBACK_FIELD)

        weighted = score * weight
        contributions[signal_name] = weighted
        total += weighted
        total_w += weight

    if total_w <= 0:
        return 0.0, contributions

    composite = float(np.clip(total / total_w, -1.0, 1.0))
    contributions = {k: v / total_w for k, v in contributions.items()}
    return composite, contributions


def select_candidates(
    signals: dict[str, SignalVector],
    sector_fn: Callable[[str], str],
    top_n: int = 50,
    max_per_sector: Optional[int] = None,
    min_composite: Optional[float] = None,
    weights: Optional[dict[str, float]] = None,
) -> list[Candidate]:
    """
    Rank all tickers by the screener composite and return the top-N.

    Args:
        signals: {ticker -> SignalVector} — assumed already cross-sectionally
            normalized (call `normalize_signals_cross_sectionally` first).
        sector_fn: t -> GICS sector string (for optional sector caps).
        top_n: how many candidates to emit (default 50).
        max_per_sector: hard cap per sector. `None` disables (recommended
            default: don't sector-cap the *screener* — that shrinks the
            AI's search space unnecessarily).
        min_composite: optional quality floor. Applied *before* top-N slicing.
        weights: override SCREENER_WEIGHTS.

    Returns:
        List of Candidate, ordered highest composite first.
    """
    scored: list[Candidate] = []
    for ticker, sv in signals.items():
        composite, contribs = compute_screener_composite(sv, weights=weights)
        if min_composite is not None and composite < min_composite:
            continue
        scored.append(
            Candidate(
                ticker=ticker,
                composite=composite,
                sector=sector_fn(ticker),
                contributions=contribs,
            )
        )

    scored.sort(key=lambda c: c.composite, reverse=True)

    if max_per_sector is None or max_per_sector <= 0:
        return scored[:top_n]

    kept: list[Candidate] = []
    sector_counts: dict[str, int] = {}
    for cand in scored:
        count = sector_counts.get(cand.sector, 0)
        if count >= max_per_sector:
            continue
        kept.append(cand)
        sector_counts[cand.sector] = count + 1
        if len(kept) >= top_n:
            break
    return kept


def candidates_to_dict(candidates: list[Candidate]) -> list[dict]:
    """Serialize Candidate list for JSON persistence."""
    return [
        {
            "ticker": c.ticker,
            "composite": round(c.composite, 6),
            "sector": c.sector,
            "contributions": {k: round(v, 6) for k, v in c.contributions.items()},
        }
        for c in candidates
    ]


# ── DataFrame-panel API (used by scripts that build IC-audit style panels) ─


# Column names used by the IC-audit panel format (`compute_signal_panel`
# in scripts/run_audit_ic.py). Keys are the panel column names, values
# are the SCREENER_WEIGHTS keys they map to.
_PANEL_COLUMN_MAP = {
    "qmj": "qmj_score",
    "sue": "sue_earnings_score",
    "erm": "erm_earnings_score",
}


def _cross_sectional_zscore(series):
    """Winsorize+zscore a pandas Series, returning [-1,+1]-clipped floats."""
    import pandas as pd

    s = series.dropna()
    if len(s) < 3:
        # not enough cross-section — return uncalibrated (all NaN -> zeros)
        return series.fillna(0.0).clip(-1.0, 1.0)

    lo, hi = s.quantile(0.025), s.quantile(0.975)
    w = s.clip(lo, hi)
    std = w.std()
    if std < 1e-9:
        return pd.Series(0.0, index=series.index)
    z = (w - w.mean()) / std
    z = (z / 3.0).clip(-1.0, 1.0)
    # Fill missing tickers with 0.0 (neutral)
    out = pd.Series(0.0, index=series.index)
    out.loc[z.index] = z
    return out


def select_candidates_from_panel(
    panel_df,
    sector_fn: Callable[[str], str],
    top_n: int = 50,
    max_per_sector: Optional[int] = None,
    weights: Optional[dict[str, float]] = None,
    already_normalized: bool = False,
) -> list[Candidate]:
    """
    Build candidate list from a panel DataFrame indexed by ticker.

    Expected columns (all optional; missing columns are treated as NaN):
      `qmj`, `sue`, `erm` — the IC-audit-format raw signal values.

    Normalizes cross-sectionally per column when `already_normalized=False`
    (default; matches the raw output of run_audit_ic's compute_signal_panel).
    """
    if weights is None:
        weights = SCREENER_WEIGHTS

    df = panel_df.copy()

    # Cross-sectional normalization per signal column
    if not already_normalized:
        for panel_col in _PANEL_COLUMN_MAP:
            if panel_col in df.columns:
                df[panel_col] = _cross_sectional_zscore(df[panel_col])

    scored: list[Candidate] = []
    for ticker in df.index:
        row = df.loc[ticker]
        total_w = 0.0
        total = 0.0
        contributions: dict[str, float] = {}
        for panel_col, weight_key in _PANEL_COLUMN_MAP.items():
            weight = weights.get(weight_key, 0.0)
            if weight <= 0 or panel_col not in df.columns:
                continue
            val = row.get(panel_col, 0.0)
            try:
                score = (
                    0.0 if val is None or (isinstance(val, float) and np.isnan(val)) else float(val)
                )
            except Exception:
                score = 0.0
            weighted = score * weight
            contributions[weight_key] = weighted
            total += weighted
            total_w += weight

        if total_w <= 0:
            composite = 0.0
        else:
            composite = float(np.clip(total / total_w, -1.0, 1.0))
            contributions = {k: v / total_w for k, v in contributions.items()}

        scored.append(
            Candidate(
                ticker=str(ticker),
                composite=composite,
                sector=sector_fn(str(ticker)),
                contributions=contributions,
            )
        )

    scored.sort(key=lambda c: c.composite, reverse=True)

    if max_per_sector is None or max_per_sector <= 0:
        return scored[:top_n]

    kept: list[Candidate] = []
    sector_counts: dict[str, int] = {}
    for cand in scored:
        count = sector_counts.get(cand.sector, 0)
        if count >= max_per_sector:
            continue
        kept.append(cand)
        sector_counts[cand.sector] = count + 1
        if len(kept) >= top_n:
            break
    return kept
