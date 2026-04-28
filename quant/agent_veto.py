"""
Quantified Agent Veto — deterministic proxy for LLM agent risk screening.

Approximates what the RiskAgent and EarningsAgent would flag as "avoid"
using structured WRDS data. Fully backtestable and CPCV-compatible.

Three veto signals (LONG side — `apply_agent_veto`):
  1. Balance sheet deterioration (RiskAgent proxy)
     - D/E ratio spiking QoQ
     - Cash burn (cheq declining)
     - Equity erosion
  2. Earnings momentum collapse (EarningsAgent proxy)
     - ERM turning sharply negative
     - Revenue declining YoY
  3. Analyst flight (RiskAgent proxy)
     - Analyst coverage dropping
     - Dispersion spiking (disagreement = uncertainty)

A stock is vetoed if it triggers 2+ of 3 signals. Vetoed stocks are
removed from the candidate list before position selection.

SHORT side — `apply_short_fundamental_veto`:
  Mirrors the long-side logic with INVERTED checks. A short candidate
  scoring poorly on the technical/composite layer may still have strong
  underlying fundamentals (NVDA-2022 type — bullish ERM, high quality,
  positive SUE despite a temporary technical drawdown). For these names,
  shorting is a structural bet against the fundamentals, which carries
  high carry risk in a bull market.

  Three "fundamental strength" flags:
    - ERM > threshold (analyst upgrades / positive revisions)
    - quality_score > threshold (high ROIC + margin vs cross-section)
    - SUE > threshold (recent positive earnings surprise)

  A short candidate is vetoed (= removed from the short list) if it
  trips `min_strong_signals` or more flags. Default is 1 — even a single
  fundamental-strength signal is enough to skip the short. "Innocent
  until proven guilty": when ALL inputs are missing/error, the candidate
  is NOT vetoed (we don't know it's strong, so we let the technical
  layer decide), matching the conservative pattern in `apply_agent_veto`.
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def compute_balance_sheet_veto(
    ticker: str,
    provider,
    as_of_date: Optional[date] = None,
) -> tuple[bool, dict]:
    """
    Check for balance sheet deterioration (RiskAgent proxy).

    Veto if 2+ of:
      - D/E ratio increased >20% QoQ
      - Cash declined >15% QoQ
      - Equity declined >10% QoQ
    """
    try:
        kwargs = {"limit": 2}
        if as_of_date is not None:
            kwargs["as_of_date"] = as_of_date
        quarters = provider.get_balance_sheet_quarterly(ticker, **kwargs)

        if not quarters or len(quarters) < 2:
            return False, {"reason": "insufficient data"}

        current = quarters[0]
        prior = quarters[1]

        flags = []

        # D/E change
        equity_now = current.get("totalStockholdersEquity") or 0
        equity_prior = prior.get("totalStockholdersEquity") or 0
        debt_now = (current.get("totalDebt") or
                    ((current.get("shortTermDebt") or 0) + (current.get("longTermDebt") or 0)))
        debt_prior = (prior.get("totalDebt") or
                      ((prior.get("shortTermDebt") or 0) + (prior.get("longTermDebt") or 0)))

        if equity_now > 0 and equity_prior > 0:
            de_now = debt_now / equity_now
            de_prior = debt_prior / equity_prior
            if de_prior > 0 and (de_now - de_prior) / de_prior > 0.20:
                flags.append(f"D/E spike: {de_prior:.2f}→{de_now:.2f}")

        # Cash decline
        cash_now = current.get("cashAndCashEquivalents") or 0
        cash_prior = prior.get("cashAndCashEquivalents") or 0
        if cash_prior > 0 and (cash_now - cash_prior) / cash_prior < -0.15:
            flags.append(f"cash burn: {cash_prior/1e6:.0f}M→{cash_now/1e6:.0f}M")

        # Equity erosion
        if equity_prior > 0 and (equity_now - equity_prior) / abs(equity_prior) < -0.10:
            flags.append(f"equity erosion: {equity_prior/1e6:.0f}M→{equity_now/1e6:.0f}M")

        veto = len(flags) >= 2
        return veto, {"flags": flags, "n_flags": len(flags)}

    except Exception as exc:
        logger.debug("BS veto failed for %s: %s", ticker, exc)
        return False, {"error": str(exc)}


def compute_earnings_momentum_veto(
    ticker: str,
    provider,
    as_of_date: Optional[date] = None,
) -> tuple[bool, dict]:
    """
    Check for earnings momentum collapse (EarningsAgent proxy).

    Veto if:
      - ERM is strongly negative (< -5% revision over 3 months)
      AND revenue is declining YoY
    """
    try:
        # Get IBES consensus for ERM
        est_kwargs = {"limit": 8}
        if as_of_date is not None:
            est_kwargs["as_of_date"] = as_of_date
        estimates = provider.get_analyst_estimates(ticker, **est_kwargs)

        erm_negative = False
        if estimates and len(estimates) >= 4:
            current_eps = estimates[0].get("epsAvg") or estimates[0].get("meanest")
            # Find estimate ~3 months back
            prior_eps = None
            for est in estimates[3:]:
                eps = est.get("epsAvg") or est.get("meanest")
                if eps is not None:
                    prior_eps = eps
                    break
            if current_eps and prior_eps and abs(prior_eps) > 0.01:
                revision = (current_eps - prior_eps) / abs(prior_eps)
                erm_negative = revision < -0.05

        # Revenue decline YoY
        fund_kwargs = {"limit": 5}
        if as_of_date is not None:
            fund_kwargs["as_of_date"] = as_of_date
        fundamentals = provider.get_balance_sheet_quarterly(ticker, **fund_kwargs)

        rev_declining = False
        if fundamentals and len(fundamentals) >= 5:
            rev_now = fundamentals[0].get("revenue") or 0
            rev_yago = fundamentals[4].get("revenue") or 0
            if rev_yago > 0:
                rev_declining = (rev_now - rev_yago) / rev_yago < -0.05

        veto = erm_negative and rev_declining
        return veto, {
            "erm_negative": erm_negative,
            "rev_declining": rev_declining,
        }

    except Exception as exc:
        logger.debug("Earnings veto failed for %s: %s", ticker, exc)
        return False, {"error": str(exc)}


def compute_analyst_flight_veto(
    ticker: str,
    provider,
    as_of_date: Optional[date] = None,
) -> tuple[bool, dict]:
    """
    Check for analyst coverage deterioration (RiskAgent proxy).

    Veto if:
      - Analyst count dropped >25% over 3 months
      OR dispersion spiked above 0.20 (high disagreement)
    """
    try:
        est_kwargs = {"limit": 4}
        if as_of_date is not None:
            est_kwargs["as_of_date"] = as_of_date
        estimates = provider.get_analyst_estimates(ticker, **est_kwargs)

        if not estimates or len(estimates) < 2:
            return False, {"reason": "insufficient estimates"}

        current = estimates[0]
        n_now = current.get("numAnalystsEps") or current.get("numest") or 0
        stdev = current.get("epsStdev") or current.get("stdev") or 0
        mean_eps = current.get("epsAvg") or current.get("meanest") or 0

        # Find analyst count ~3 months ago
        n_prior = n_now
        for est in estimates[2:]:
            n = est.get("numAnalystsEps") or est.get("numest")
            if n is not None and n > 0:
                n_prior = n
                break

        coverage_drop = False
        if n_prior > 3 and n_now > 0:
            coverage_drop = (n_now - n_prior) / n_prior < -0.25

        high_dispersion = False
        if abs(mean_eps) > 0.01 and n_now >= 3:
            dispersion = float(stdev) / abs(float(mean_eps))
            high_dispersion = dispersion > 0.20

        veto = coverage_drop or high_dispersion
        return veto, {
            "coverage_drop": coverage_drop,
            "n_now": int(n_now),
            "n_prior": int(n_prior),
            "high_dispersion": high_dispersion,
        }

    except Exception as exc:
        logger.debug("Analyst veto failed for %s: %s", ticker, exc)
        return False, {"error": str(exc)}


def apply_agent_veto(
    candidates: list[tuple],
    provider,
    as_of_date: Optional[date] = None,
    min_flags: int = 2,
) -> tuple[list[tuple], list[dict]]:
    """
    Apply quantified agent veto to a list of candidates.

    Args:
        candidates: list of (ticker, score, signal_vector) tuples from build_target_portfolio
        provider: FundamentalProvider (WRDS or FMP)
        as_of_date: point-in-time date
        min_flags: minimum veto signals to trigger removal (default: 2 of 3)

    Returns:
        (surviving_candidates, veto_log)
    """
    survivors = []
    veto_log = []

    for ticker, score, sv in candidates:
        bs_veto, bs_meta = compute_balance_sheet_veto(ticker, provider, as_of_date)
        earn_veto, earn_meta = compute_earnings_momentum_veto(ticker, provider, as_of_date)
        analyst_veto, analyst_meta = compute_analyst_flight_veto(ticker, provider, as_of_date)

        n_vetos = sum([bs_veto, earn_veto, analyst_veto])

        if n_vetos >= min_flags:
            veto_log.append({
                "ticker": ticker,
                "score": round(score, 3),
                "n_vetos": n_vetos,
                "bs_veto": bs_veto,
                "earn_veto": earn_veto,
                "analyst_veto": analyst_veto,
                "bs_detail": bs_meta,
                "earn_detail": earn_meta,
                "analyst_detail": analyst_meta,
            })
            sv.flags.append(f"VETOED(n={n_vetos})")
        else:
            survivors.append((ticker, score, sv))

    if veto_log:
        vetoed_tickers = [v["ticker"] for v in veto_log]
        logger.info("Agent veto removed %d/%d candidates: %s",
                     len(veto_log), len(candidates), ", ".join(vetoed_tickers))

    return survivors, veto_log


# ── Short-side fundamental-strength veto ───────────────────────────────


def _safe_float(val) -> Optional[float]:
    """Convert to float, returning None for NaN / non-numeric / None."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def compute_fundamental_strength_veto(
    ticker: str,
    provider,
    sv,
    as_of_date: Optional[date] = None,
    erm_threshold: float = 0.20,
    quality_threshold: float = 0.30,
    sue_threshold: float = 0.50,
) -> tuple[bool, dict]:
    """
    For SHORT candidates: return (should_veto=True, meta) if the ticker
    has *strong* fundamentals — i.e. it is NOT a clean short despite a
    low composite score. Inverts the long-side trap-detection logic.

    Veto fires if ANY of:
      - ERM > erm_threshold (analysts upgrading consensus)
      - quality_score > quality_threshold (ROIC+margin vs cross-section)
      - SUE > sue_threshold (recent positive earnings surprise)

    Reads quality from `sv.quality_score` (already cross-sectionally
    normalized). Reads ERM/SUE directly from the provider via
    `compute_erm_score` / `compute_sue_score` since the composite
    `earnings_rank_score` blends them with dispersion and we want
    each lever clean for short-side risk control.

    Conservative behavior: when ALL three inputs are unavailable
    (all errored / returned None), returns `(False, {...})` — i.e.
    we do NOT veto on missing data. "Innocent until proven guilty"
    matches the long-side `apply_agent_veto` pattern.

    Returns (should_skip_short, metadata_dict).
    """
    flags: list[str] = []
    erm_score: Optional[float] = None
    quality: Optional[float] = None
    sue_score: Optional[float] = None
    erm_meta: dict = {}
    sue_meta: dict = {}

    # ERM via earnings_signals
    try:
        from quant.earnings_signals import compute_erm_score
        erm_score, erm_meta = compute_erm_score(ticker, provider, as_of_date)
        # compute_erm_score returns 0.0 when data missing; treat 0 with an
        # 'error' meta as missing (don't count as strength signal).
        if isinstance(erm_meta, dict) and erm_meta.get("error"):
            erm_score = None
    except Exception as exc:
        logger.debug("ERM strength check failed for %s: %s", ticker, exc)
        erm_score = None

    # Quality from the (already cross-sectionally normalized) signal vector
    if sv is not None:
        q_raw = getattr(sv, "quality_score", None)
        quality = _safe_float(q_raw)
        # quality_score=0.0 is ambiguous — could mean "not computed" or a
        # genuine zero z-score. Be conservative: treat exactly 0.0 as
        # "no strength signal" (matches the original cross_sectional logic
        # of skipping zero-only fields).
        if quality is not None and quality == 0.0:
            quality = None

    # SUE via earnings_signals
    try:
        from quant.earnings_signals import compute_sue_score
        sue_score, sue_meta = compute_sue_score(ticker, provider, as_of_date)
        if isinstance(sue_meta, dict) and sue_meta.get("error"):
            sue_score = None
    except Exception as exc:
        logger.debug("SUE strength check failed for %s: %s", ticker, exc)
        sue_score = None

    # Apply thresholds
    if erm_score is not None and erm_score > erm_threshold:
        flags.append(f"ERM={erm_score:+.3f}>{erm_threshold:+.3f}")
    if quality is not None and quality > quality_threshold:
        flags.append(f"quality={quality:+.3f}>{quality_threshold:+.3f}")
    if sue_score is not None and sue_score > sue_threshold:
        flags.append(f"SUE={sue_score:+.3f}>{sue_threshold:+.3f}")

    # Track which inputs we actually saw — useful for the "all-missing"
    # innocent-until-proven-guilty path.
    inputs_seen = sum(x is not None for x in (erm_score, quality, sue_score))

    return len(flags) >= 1, {
        "n_flags": len(flags),
        "flags": flags,
        "erm_score": erm_score,
        "quality_score": quality,
        "sue_score": sue_score,
        "inputs_seen": inputs_seen,
        "erm_threshold": erm_threshold,
        "quality_threshold": quality_threshold,
        "sue_threshold": sue_threshold,
    }


def apply_short_fundamental_veto(
    short_candidates: list[tuple],
    provider,
    as_of_date: Optional[date] = None,
    min_strong_signals: int = 1,
    erm_threshold: float = 0.20,
    quality_threshold: float = 0.30,
    sue_threshold: float = 0.50,
) -> tuple[list[tuple], list[dict]]:
    """
    Filter short candidates: skip any with `min_strong_signals` or more
    fundamental-strength flags. Returns (survivors, veto_log).

    "Innocent until proven guilty": if NO fundamental inputs are available
    (all None / error), the candidate is NOT vetoed.

    Args:
        short_candidates: list of (ticker, score, signal_vector) tuples
        provider: WRDSFundamentalProvider
        as_of_date: point-in-time date
        min_strong_signals: min strength flags to remove a candidate (default 1)
        erm_threshold / quality_threshold / sue_threshold: per-flag thresholds

    Returns:
        (surviving_short_candidates, veto_log)
    """
    survivors: list[tuple] = []
    veto_log: list[dict] = []

    for ticker, score, sv in short_candidates:
        is_strong, meta = compute_fundamental_strength_veto(
            ticker, provider, sv, as_of_date,
            erm_threshold=erm_threshold,
            quality_threshold=quality_threshold,
            sue_threshold=sue_threshold,
        )
        n_flags = meta.get("n_flags", 0)

        if is_strong and n_flags >= min_strong_signals:
            veto_log.append({
                "ticker": ticker,
                "score": round(float(score), 3),
                "n_flags": n_flags,
                "flags": meta.get("flags", []),
                "erm_score": meta.get("erm_score"),
                "quality_score": meta.get("quality_score"),
                "sue_score": meta.get("sue_score"),
                "inputs_seen": meta.get("inputs_seen", 0),
            })
            if sv is not None and hasattr(sv, "flags"):
                sv.flags.append(f"SHORT_VETOED(strength={n_flags})")
            logger.debug(
                "Short veto %s (score=%.3f): %d strength flags — %s",
                ticker, score, n_flags, ", ".join(meta.get("flags", [])),
            )
        else:
            survivors.append((ticker, score, sv))

    if veto_log:
        vetoed = [v["ticker"] for v in veto_log]
        logger.info(
            "Short fundamental-strength veto removed %d/%d candidates: %s",
            len(veto_log), len(short_candidates), ", ".join(vetoed),
        )

    return survivors, veto_log
