"""
Earnings-based signals from WRDS IBES + Compustat.

Three signals with documented IC that survive FF5+Mom adjustment:
  1. ERM (Earnings Revision Momentum) — Novy-Marx 2015, IC 0.04-0.08
  2. SUE (Standardized Unexpected Earnings) — Bernard & Thomas 1989, IC 0.03-0.06
  3. Analyst Dispersion (negative signal) — Diether et al. 2002

These replace the broken technical signals (SMA, MR, BB, RSI) which have
zero cross-sectional IC at monthly frequency.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def compute_erm_score(
    ticker: str,
    provider,
    as_of_date: Optional[date] = None,
    lookback_months: int = 3,
) -> tuple[float, dict]:
    """
    Earnings Revision Momentum (Novy-Marx 2015).

    ERM = (consensus_EPS_now - consensus_EPS_N_months_ago) / |consensus_EPS_N_months_ago|

    Uses IBES monthly consensus snapshots. Compares current FY1 consensus
    to the consensus N months prior. Rising consensus = bullish.

    Documented IC: 0.04-0.08 monthly. Survives FF5+Mom.
    """
    try:
        kwargs = {"limit": lookback_months * 2 + 2}  # request 2x months to ensure coverage
        if as_of_date is not None:
            kwargs["as_of_date"] = as_of_date
        estimates = provider.get_analyst_estimates(ticker, **kwargs)

        if not estimates or len(estimates) < 2:
            return 0.0, {"error": "insufficient estimates"}

        current = estimates[0]
        current_eps = current.get("epsAvg") or current.get("meanest")

        if current_eps is None:
            return 0.0, {"error": "no current EPS estimate"}

        # Find the estimate from ~lookback_months ago (not just the prior month)
        # IBES statpers are monthly snapshots. For 3-month revision, skip to
        # the estimate that is >= lookback_months months before current.
        current_date_str = current.get("date") or current.get("statpers", "")
        prior_eps = None
        prior_date = None
        for est in estimates[1:]:
            est_date = est.get("date") or est.get("statpers", "")
            eps = est.get("epsAvg") or est.get("meanest")
            if eps is None:
                continue
            # Check if this estimate is far enough back
            if current_date_str and est_date:
                try:
                    from datetime import datetime
                    d_current = datetime.strptime(str(current_date_str)[:10], "%Y-%m-%d")
                    d_prior = datetime.strptime(str(est_date)[:10], "%Y-%m-%d")
                    gap_days = (d_current - d_prior).days
                    if gap_days >= (lookback_months * 28):  # ~N months
                        prior_eps = eps
                        prior_date = est_date
                        break
                except (ValueError, TypeError):
                    pass

        # Fallback: if no estimate found at lookback distance, use the oldest available
        if prior_eps is None:
            for est in reversed(estimates[1:]):
                eps = est.get("epsAvg") or est.get("meanest")
                if eps is not None:
                    prior_eps = eps
                    prior_date = est.get("date") or est.get("statpers", "")
                    break

        if prior_eps is None or prior_eps == 0:
            return 0.0, {"error": "no prior EPS estimate"}

        revision_pct = (current_eps - prior_eps) / abs(prior_eps)

        # Score mapping: linear in [-0.10, +0.10] revision range
        # >10% revision = max score, <-10% = min score
        score = float(np.clip(revision_pct / 0.10, -1.0, 1.0))

        # Also compute breadth (up vs down revisions) if available
        num_up = current.get("numUp") or current.get("numup", 0)
        num_down = current.get("numDown") or current.get("numdown", 0)
        num_total = (num_up or 0) + (num_down or 0)
        breadth = ((num_up or 0) - (num_down or 0)) / max(num_total, 1) if num_total > 0 else 0

        # Blend magnitude (70%) and breadth (30%)
        if num_total >= 3:
            score = 0.7 * score + 0.3 * float(np.clip(breadth, -1.0, 1.0))
            score = float(np.clip(score, -1.0, 1.0))

        n_analysts = current.get("numAnalystsEps") or current.get("numest", 0)

        return round(score, 4), {
            "current_eps": round(current_eps, 3),
            "prior_eps": round(prior_eps, 3),
            "revision_pct": round(revision_pct * 100, 2),
            "breadth": round(breadth, 3),
            "n_analysts": int(n_analysts) if n_analysts else 0,
            "current_date": current.get("date") or current.get("statpers", ""),
            "prior_date": prior_date or "",
        }

    except Exception as exc:
        logger.debug("ERM computation failed for %s: %s", ticker, exc)
        return 0.0, {"error": str(exc)}


def compute_sue_score(
    ticker: str,
    provider,
    as_of_date: Optional[date] = None,
) -> tuple[float, dict]:
    """
    Standardized Unexpected Earnings (Bernard & Thomas 1989).

    SUE = (EPS_q - EPS_{q-4}) / std(EPS_q - EPS_{q-4}) over trailing 8 quarters.

    Uses Compustat quarterly EPS (epsfxq). Positive surprise = bullish.
    Captures post-earnings announcement drift (PEAD).
    """
    try:
        kwargs = {"limit": 8}
        if as_of_date is not None:
            kwargs["as_of_date"] = as_of_date
        fundamentals = provider.get_balance_sheet_quarterly(ticker, **kwargs)

        if not fundamentals or len(fundamentals) < 5:
            return 0.0, {"error": "insufficient quarterly data"}

        # Extract EPS from quarterly data
        eps_series = []
        for q in fundamentals:
            eps = q.get("eps") or q.get("epsDiluted") or q.get("epsfxq")
            if eps is not None:
                eps_series.append(float(eps))
            else:
                eps_series.append(None)

        # Need at least current quarter and same-quarter-last-year
        if len(eps_series) < 5 or eps_series[0] is None or eps_series[4] is None:
            return 0.0, {"error": "missing EPS for SUE computation"}

        # Compute seasonal differences (quarter vs same quarter prior year)
        diffs = []
        for i in range(len(eps_series) - 4):
            if eps_series[i] is not None and eps_series[i + 4] is not None:
                diffs.append(eps_series[i] - eps_series[i + 4])

        if not diffs:
            return 0.0, {"error": "no valid seasonal diffs"}

        latest_diff = diffs[0]
        std_diff = float(np.std(diffs)) if len(diffs) > 1 else abs(latest_diff) + 0.01

        if std_diff < 0.001:
            std_diff = 0.01

        sue = latest_diff / std_diff

        # Score: linear mapping, capped at ±3 std
        score = float(np.clip(sue / 3.0, -1.0, 1.0))

        return round(score, 4), {
            "sue": round(sue, 3),
            "latest_eps": round(eps_series[0], 3),
            "year_ago_eps": round(eps_series[4], 3),
            "surprise": round(latest_diff, 3),
            "std_surprise": round(std_diff, 4),
            "n_diffs": len(diffs),
        }

    except Exception as exc:
        logger.debug("SUE computation failed for %s: %s", ticker, exc)
        return 0.0, {"error": str(exc)}


def compute_dispersion_score(
    ticker: str,
    provider,
    as_of_date: Optional[date] = None,
) -> tuple[float, dict]:
    """
    Analyst Dispersion (Diether, Malloy, Scherbina 2002).

    Dispersion = std(analyst EPS estimates) / |mean(analyst EPS estimates)|
    HIGH dispersion → NEGATIVE signal (Miller 1977 overvaluation hypothesis).

    Requires minimum 3 analysts for meaningful dispersion.
    """
    try:
        kwargs = {"limit": 1}
        if as_of_date is not None:
            kwargs["as_of_date"] = as_of_date
        estimates = provider.get_analyst_estimates(ticker, **kwargs)

        if not estimates:
            return 0.0, {"error": "no estimates"}

        current = estimates[0]
        mean_eps = current.get("epsAvg") or current.get("meanest")
        std_eps = current.get("epsStdev") or current.get("stdev")
        n_analysts = current.get("numAnalystsEps") or current.get("numest", 0)

        if mean_eps is None or std_eps is None or n_analysts is None:
            return 0.0, {"error": "missing dispersion fields"}

        n_analysts = int(n_analysts)
        if n_analysts < 3:
            return 0.0, {"error": f"too few analysts ({n_analysts})"}

        if abs(mean_eps) < 0.01:
            return 0.0, {"error": "near-zero mean EPS"}

        dispersion = float(std_eps) / abs(float(mean_eps))

        # Score: HIGH dispersion = NEGATIVE (avoid)
        # Dispersion > 0.20 → strong avoid (-1.0)
        # Dispersion < 0.05 → consensus agreement (+0.5)
        if dispersion > 0.20:
            score = -1.0
        elif dispersion > 0.10:
            score = -0.5 - (dispersion - 0.10) / 0.10 * 0.5
        elif dispersion > 0.05:
            score = 0.0 - (dispersion - 0.05) / 0.05 * 0.5
        else:
            score = 0.5 - dispersion / 0.05 * 0.5

        score = float(np.clip(score, -1.0, 1.0))

        return round(score, 4), {
            "dispersion": round(dispersion, 4),
            "mean_eps": round(float(mean_eps), 3),
            "std_eps": round(float(std_eps), 4),
            "n_analysts": n_analysts,
        }

    except Exception as exc:
        logger.debug("Dispersion computation failed for %s: %s", ticker, exc)
        return 0.0, {"error": str(exc)}


def compute_earnings_signal_scores(
    tickers: list[str],
    provider,
    as_of_date: Optional[date] = None,
    erm_weight: float = 0.40,
    sue_weight: float = 0.35,
    dispersion_weight: float = 0.25,
) -> dict[str, tuple[float, int, dict]]:
    """
    Compute combined earnings signal for each ticker.

    Returns {ticker: (combined_score, n_signals, metadata)}.
    """
    results = {}

    for ticker in tickers:
        erm_score, erm_meta = compute_erm_score(ticker, provider, as_of_date)
        sue_score, sue_meta = compute_sue_score(ticker, provider, as_of_date)
        disp_score, disp_meta = compute_dispersion_score(ticker, provider, as_of_date)

        valid_scores = []
        weights = []

        if "error" not in erm_meta:
            valid_scores.append(erm_score)
            weights.append(erm_weight)
        if "error" not in sue_meta:
            valid_scores.append(sue_score)
            weights.append(sue_weight)
        if "error" not in disp_meta:
            valid_scores.append(disp_score)
            weights.append(dispersion_weight)

        if not valid_scores:
            continue

        # Weighted average, normalized
        total_w = sum(weights)
        combined = sum(s * w for s, w in zip(valid_scores, weights)) / total_w
        combined = float(np.clip(combined, -1.0, 1.0))

        results[ticker] = (
            round(combined, 4),
            len(valid_scores),
            {
                "erm": {"score": erm_score, **erm_meta},
                "sue": {"score": sue_score, **sue_meta},
                "dispersion": {"score": disp_score, **disp_meta},
            },
        )

    return results


def blend_earnings_signals(
    signals: dict,
    earnings_scores: dict[str, tuple[float, int, dict]],
    weight: float = 0.30,
) -> dict:
    """
    Blend earnings signal scores into SignalVector composite scores.

    Same pattern as blend_fundamentals_into_signals.
    """
    if not earnings_scores:
        return signals

    for ticker, sv in signals.items():
        entry = earnings_scores.get(ticker)
        if entry is None:
            continue

        score, n_signals, meta = entry
        effective_weight = weight * (n_signals / 3.0)

        quant_scale = 1.0 - effective_weight
        blended = sv.composite_score * quant_scale + score * effective_weight
        sv.composite_score = float(np.clip(blended, -1.0, 1.0))

        if sv.composite_score >= 0.30:
            sv.composite_direction = "BUY"
        elif sv.composite_score <= -0.30:
            sv.composite_direction = "SELL"
        else:
            sv.composite_direction = "HOLD"
        sv.actionable = abs(sv.composite_score) >= 0.40

        sv.flags.append(f"earnings_w={effective_weight:.3f}(n={n_signals},src=wrds_ibes)")

        # Store raw earnings score for earnings-based ranking (Path A)
        sv.earnings_rank_score = score

    return signals
