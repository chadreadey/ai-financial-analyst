"""
Fundamental signals from FMP financial data.

Two signals with documented IC 0.04-0.10:
  1. ROA (Return on Assets) — quality/profitability proxy
  2. Earnings Revision Momentum — analyst consensus trend

These are blended into the composite as an overlay (like sentiment),
not as core SignalVector members, because they require FMP API data
rather than pure price/volume.

Usage in backtest:
    scores = compute_fundamental_scores(tickers, as_of_date, fmp_client)
    signals = blend_fundamentals_into_signals(signals, scores, weight=0.10)
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def compute_quality_score(
    ticker: str,
    fmp_client,
    as_of_date=None,
) -> tuple[float, dict]:
    """
    Compute financial quality signal from balance sheet data.

    Uses two balance-sheet ratios (no income statement needed):
      1. Equity Ratio = Stockholders' Equity / Total Assets (financial strength)
      2. Current Ratio = Current Assets / Current Liabilities (liquidity)

    Combined score mapping:
      equity_ratio > 0.50  → +1.0   (fortress balance sheet)
      equity_ratio > 0.35  → +0.5
      equity_ratio > 0.20  → +0.0
      equity_ratio > 0.10  → -0.5
      equity_ratio <= 0.10 → -1.0   (highly leveraged)

      current_ratio > 2.0  → +0.5 bonus
      current_ratio > 1.5  → +0.25 bonus
      current_ratio < 1.0  → -0.5 penalty

    Returns (score, metadata_dict).
    """
    try:
        kwargs = {"limit": 1}
        if as_of_date is not None:
            kwargs["as_of_date"] = as_of_date
        balance = fmp_client.get_balance_sheet_quarterly(ticker, **kwargs)

        if not balance:
            return 0.0, {"error": "no data"}

        total_assets = balance[0].get("totalAssets", 0) or 0
        equity = balance[0].get("totalStockholdersEquity", 0) or 0
        current_assets = balance[0].get("totalCurrentAssets", 0) or 0
        current_liabilities = balance[0].get("totalCurrentLiabilities", 0) or 0

        if total_assets <= 0:
            return 0.0, {"error": "invalid assets"}

        equity_ratio = equity / total_assets

        if equity_ratio > 0.50:
            eq_score = 1.0
        elif equity_ratio > 0.35:
            eq_score = 0.5 + (equity_ratio - 0.35) / 0.15 * 0.5
        elif equity_ratio > 0.20:
            eq_score = (equity_ratio - 0.20) / 0.15 * 0.5
        elif equity_ratio > 0.10:
            eq_score = -0.5 + (equity_ratio - 0.10) / 0.10 * 0.5
        else:
            eq_score = -1.0

        # Current ratio bonus/penalty
        cr_adj = 0.0
        current_ratio = current_assets / current_liabilities if current_liabilities > 0 else 2.0
        if current_ratio > 2.0:
            cr_adj = 0.5
        elif current_ratio > 1.5:
            cr_adj = 0.25
        elif current_ratio < 1.0:
            cr_adj = -0.5

        score = eq_score * 0.7 + cr_adj * 0.3

        return round(float(np.clip(score, -1.0, 1.0)), 4), {
            "equity_ratio": round(equity_ratio * 100, 2),
            "current_ratio": round(current_ratio, 2),
            "equity": equity,
            "total_assets": total_assets,
        }

    except Exception as exc:
        logger.debug("Quality score computation failed for %s: %s", ticker, exc)
        return 0.0, {"error": str(exc)}


def compute_earnings_revision_score(
    ticker: str,
    fmp_client,
    as_of_date=None,
) -> tuple[float, dict]:
    """
    Compute earnings revision momentum from FMP analyst estimates.

    Compares the most recent EPS estimate to the prior estimate.
    Positive revisions (analysts raising estimates) are bullish.
    Documented IC: 0.04-0.10 (Jegadeesh & Titman, Bernard & Thomas).

    Score mapping:
      revision > +10% → +1.0
      revision > +5%  → +0.5
      revision > 0%   → +0.2
      revision = 0    →  0.0
      revision < -5%  → -0.5
      revision < -10% → -1.0

    Returns (score, metadata_dict).
    """
    try:
        est_kwargs = {"limit": 4}
        if as_of_date is not None:
            est_kwargs["as_of_date"] = as_of_date
        estimates = fmp_client.get_analyst_estimates(ticker, **est_kwargs)

        if not estimates or len(estimates) < 2:
            return 0.0, {"error": "insufficient estimates"}

        # Compare latest estimate to prior
        current = estimates[0].get("epsAvg", None)
        prior = estimates[1].get("epsAvg", None)

        if current is None or prior is None or prior == 0:
            return 0.0, {"error": "missing EPS estimates"}

        revision_pct = (current - prior) / abs(prior)

        if revision_pct > 0.10:
            score = 1.0
        elif revision_pct > 0.05:
            score = 0.5 + (revision_pct - 0.05) / 0.05 * 0.5
        elif revision_pct > 0:
            score = revision_pct / 0.05 * 0.5
        elif revision_pct > -0.05:
            score = revision_pct / 0.05 * 0.5
        elif revision_pct > -0.10:
            score = -0.5 + (revision_pct + 0.10) / 0.05 * 0.5
        else:
            score = -1.0

        return round(float(np.clip(score, -1.0, 1.0)), 4), {
            "revision_pct": round(revision_pct * 100, 2),
            "current_eps_est": current,
            "prior_eps_est": prior,
        }

    except Exception as exc:
        logger.debug("Earnings revision failed for %s: %s", ticker, exc)
        return 0.0, {"error": str(exc)}


def compute_fundamental_scores(
    tickers: list[str],
    fmp_client=None,
    fmp_cache=None,
    wrds_provider=None,
    as_of_date=None,
) -> dict[str, tuple[float, int]]:
    """
    Compute fundamental signal for each ticker.

    Provider priority: wrds_provider (if as_of_date provided) > fmp_cache > fmp_client.
    Returns {ticker: (combined_score, n_signals)} where combined_score
    is the average of quality and earnings revision signals.
    n_signals indicates how many of the two signals had valid data.
    """
    if wrds_provider is not None and as_of_date is not None:
        data_source = wrds_provider
    elif fmp_cache is not None:
        data_source = _CacheBackedFMP(fmp_client, fmp_cache)
    elif fmp_client is not None:
        data_source = fmp_client
    else:
        return {}

    results = {}
    for ticker in tickers:
        qual_score, qual_meta = compute_quality_score(ticker, data_source, as_of_date=as_of_date)
        rev_score, rev_meta = compute_earnings_revision_score(ticker, data_source, as_of_date=as_of_date)

        valid_scores = []
        if "error" not in qual_meta:
            valid_scores.append(qual_score)
        if "error" not in rev_meta:
            valid_scores.append(rev_score)

        if not valid_scores:
            continue

        combined = sum(valid_scores) / len(valid_scores)
        results[ticker] = (round(float(np.clip(combined, -1.0, 1.0)), 4), len(valid_scores))

    return results


class _CacheBackedFMP:
    """Wrapper that reads from cache first, falls back to live FMP client."""

    def __init__(self, client=None, cache=None):
        self._client = client
        self._cache = cache

    def get_income_statement_quarterly(self, ticker: str, limit: int = 8, as_of_date=None) -> list[dict]:
        # as_of_date ignored — FMP cache is a static snapshot (no point-in-time)
        if self._cache:
            data = self._cache.get_income_quarterly(ticker)
            if data is not None:
                return data[:limit]
        if self._client:
            return self._client.get_income_statement_quarterly(ticker, limit=limit)
        return []

    def get_balance_sheet_quarterly(self, ticker: str, limit: int = 4, as_of_date=None) -> list[dict]:
        # as_of_date ignored — FMP cache is a static snapshot (no point-in-time)
        if self._cache:
            data = self._cache.get_balance_quarterly(ticker)
            if data is not None:
                return data[:limit]
        if self._client:
            return self._client.get_balance_sheet_quarterly(ticker, limit=limit)
        return []

    def get_analyst_estimates(self, ticker: str, limit: int = 4, as_of_date=None) -> list[dict]:
        if self._cache:
            data = self._cache.get_analyst_estimates(ticker)
            if data is not None:
                return data[:limit]
        if self._client:
            return self._client.get_analyst_estimates(ticker, limit=limit)
        return []


def blend_fundamentals_into_signals(
    signals: dict,
    fundamental_scores: dict[str, tuple[float, int]],
    weight: float = 0.10,
) -> dict:
    """
    Blend fundamental scores into SignalVector composite scores.

    Follows the same pattern as blend_sentiment_into_signals:
    - Weight scales with number of valid fundamental signals (1 or 2)
    - Blended: composite = (1 - effective_weight) * quant + effective_weight * fundamental

    Args:
        signals: {ticker: SignalVector}
        fundamental_scores: {ticker: (score, n_signals)}
        weight: Base weight for fundamental overlay (default 10%)
    """
    if not fundamental_scores:
        return signals

    for ticker, sv in signals.items():
        entry = fundamental_scores.get(ticker)
        if entry is None:
            continue

        score, n_signals = entry
        # Scale weight by signal completeness (1 signal = 50% weight, 2 = full)
        effective_weight = weight * (n_signals / 2.0)

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

        sv.flags.append(f"fundamental_w={effective_weight:.3f}(n={n_signals})")

    return signals


def load_cached_fundamentals(ticker: str, fmp_cache=None) -> dict:
    """
    Load cached fundamental data for a single ticker and return a dict
    suitable for AnalysisData.cached_fundamentals.

    Returns structured data that agents can consume directly:
    - balance_sheet: latest quarterly balance sheet metrics
    - earnings_revision: EPS revision direction and magnitude
    - balance_sheet_qoq: quarter-over-quarter changes
    - latest_income: revenue, net income, EPS from latest quarter
    """
    if fmp_cache is None:
        return {}

    result = {}

    # --- Balance sheet (latest quarter) ---
    balance = fmp_cache.get_balance_quarterly(ticker)
    if balance and len(balance) > 0:
        latest = balance[0]
        total_assets = latest.get("totalAssets", 0) or 0
        equity = latest.get("totalStockholdersEquity", 0) or 0
        current_assets = latest.get("totalCurrentAssets", 0) or 0
        current_liab = latest.get("totalCurrentLiabilities", 0) or 0
        total_debt = latest.get("totalDebt", 0) or 0
        cash = latest.get("cashAndCashEquivalents", 0) or 0

        bs = {
            "as_of_date": latest.get("date", "unknown"),
            "total_assets": total_assets,
            "stockholders_equity": equity,
            "total_debt": total_debt,
            "cash": cash,
            "net_debt": total_debt - cash,
            "current_assets": current_assets,
            "current_liabilities": current_liab,
        }
        if total_assets > 0:
            bs["equity_ratio_pct"] = round(equity / total_assets * 100, 1)
            bs["debt_to_assets_pct"] = round(total_debt / total_assets * 100, 1)
        if current_liab > 0:
            bs["current_ratio"] = round(current_assets / current_liab, 2)
        if equity > 0:
            bs["debt_to_equity"] = round(total_debt / equity, 2)

        result["balance_sheet"] = bs

        # Quarter-over-quarter trend if we have 2+ quarters
        if len(balance) >= 2:
            prior = balance[1]
            prior_equity = prior.get("totalStockholdersEquity", 0) or 0
            prior_debt = prior.get("totalDebt", 0) or 0
            prior_cash = prior.get("cashAndCashEquivalents", 0) or 0
            changes = {}
            if prior_equity > 0:
                changes["equity_change_pct"] = round((equity - prior_equity) / abs(prior_equity) * 100, 1)
            if prior_debt > 0:
                changes["debt_change_pct"] = round((total_debt - prior_debt) / abs(prior_debt) * 100, 1)
            if prior_cash > 0:
                changes["cash_change_pct"] = round((cash - prior_cash) / abs(prior_cash) * 100, 1)
            if changes:
                result["balance_sheet_qoq"] = changes

    # --- Income (if available — Tiingo provides this) ---
    income = fmp_cache.get_income_quarterly(ticker)
    if income and len(income) > 0:
        latest_inc = income[0]
        result["latest_income"] = {
            "as_of_date": latest_inc.get("date", "unknown"),
            "revenue": latest_inc.get("revenue", 0),
            "net_income": latest_inc.get("netIncome", 0),
            "ebitda": latest_inc.get("ebitda", 0),
            "eps_diluted": latest_inc.get("epsDil") or latest_inc.get("eps", 0),
        }
        if len(income) >= 2:
            prior_inc = income[1]
            prior_rev = prior_inc.get("revenue", 0) or 0
            prior_ni = prior_inc.get("netIncome", 0) or 0
            curr_rev = latest_inc.get("revenue", 0) or 0
            curr_ni = latest_inc.get("netIncome", 0) or 0
            if prior_rev > 0:
                result["latest_income"]["revenue_qoq_pct"] = round(
                    (curr_rev - prior_rev) / abs(prior_rev) * 100, 1
                )
            if prior_ni != 0:
                result["latest_income"]["net_income_qoq_pct"] = round(
                    (curr_ni - prior_ni) / abs(prior_ni) * 100, 1
                )

    # --- Earnings revision / EPS trajectory ---
    estimates = fmp_cache.get_analyst_estimates(ticker)
    if estimates and len(estimates) >= 2:
        current_est = estimates[0]
        prior_est = estimates[1]
        current_eps = current_est.get("epsAvg")
        prior_eps = prior_est.get("epsAvg")
        current_date = current_est.get("date", "unknown")
        prior_date = prior_est.get("date", "unknown")

        # Distinguish real analyst estimates (FMP) from historical EPS (Tiingo).
        # FMP estimates have numAnalystsEps; Tiingo-sourced ones don't.
        is_analyst_estimate = current_est.get("numAnalystsEps") is not None

        if current_eps is not None and prior_eps is not None and prior_eps != 0:
            revision_pct = (current_eps - prior_eps) / abs(prior_eps) * 100

            if current_date != prior_date and abs(revision_pct) <= 50:
                direction = "UP" if revision_pct > 2 else "DOWN" if revision_pct < -2 else "FLAT"
                result["earnings_revision"] = {
                    "current_eps": round(current_eps, 3),
                    "prior_eps": round(prior_eps, 3),
                    "revision_pct": round(revision_pct, 1),
                    "direction": direction,
                    "current_date": current_date,
                    "prior_date": prior_date,
                    "is_analyst_consensus": is_analyst_estimate,
                }
                if is_analyst_estimate:
                    result["earnings_revision"]["num_analysts"] = current_est.get("numAnalystsEps")

    return result
