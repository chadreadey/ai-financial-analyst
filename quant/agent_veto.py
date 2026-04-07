"""
Quantified Agent Veto — deterministic proxy for LLM agent risk screening.

Approximates what the RiskAgent and EarningsAgent would flag as "avoid"
using structured WRDS data. Fully backtestable and CPCV-compatible.

Three veto signals:
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
"""

from __future__ import annotations

import logging
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
