"""
Institutional flow signal from FMP + Finnhub 13F ownership data.

Computes QoQ changes in institutional ownership as a cross-sectional
signal for the backtest pipeline. Three sub-signals:
  1. Holder count change (% change in number of institutional holders)
  2. Shares flow (% change in total institutional shares held)
  3. Buyer/seller ratio (net buyers - sellers / total)

Point-in-time safety: only uses snapshots with report_date + 45 days <= as_of_date.

Returns (score, metadata) tuples following the earnings_signals.py pattern.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import numpy as np

from quant.scoring import reclassify

logger = logging.getLogger(__name__)

# Minimum institutions to produce a signal (suppress noise from thinly held stocks)
MIN_INSTITUTIONS = 3


def compute_institutional_flow_score(
    current_snapshot: list[dict],
    prior_snapshot: list[dict],
) -> tuple[float, dict]:
    """
    Compute institutional flow score from two quarterly ownership snapshots.

    Args:
        current_snapshot: Latest quarter's institutional holders.
            Each dict has: investorName, sharesNumber, sharesNumberChange
        prior_snapshot: Prior quarter's institutional holders (same format).

    Returns:
        (score in [-1, +1], metadata dict)
    """
    if not current_snapshot or len(current_snapshot) < MIN_INSTITUTIONS:
        return 0.0, {"error": "insufficient institutions", "n_institutions": len(current_snapshot) if current_snapshot else 0}

    # --- Sub-signal 1: Holder count change ---
    n_current = len(current_snapshot)
    n_prior = len(prior_snapshot) if prior_snapshot else n_current

    if n_prior > 0:
        holder_count_change_pct = (n_current - n_prior) / n_prior
    else:
        holder_count_change_pct = 0.0

    # Winsorize at +/- 50% change and map to [-1, +1]
    holder_score = float(np.clip(holder_count_change_pct / 0.50, -1.0, 1.0))

    # --- Sub-signal 2: Shares flow ---
    current_total = sum(h.get("sharesNumber", 0) for h in current_snapshot)
    prior_total = sum(h.get("sharesNumber", 0) for h in prior_snapshot) if prior_snapshot else current_total

    if prior_total > 0:
        shares_flow_pct = (current_total - prior_total) / prior_total
    else:
        shares_flow_pct = 0.0

    # Winsorize at +/- 30% change and map to [-1, +1]
    shares_score = float(np.clip(shares_flow_pct / 0.30, -1.0, 1.0))

    # --- Sub-signal 3: Buyer/seller ratio ---
    n_buying = 0
    n_selling = 0
    n_unchanged = 0

    for h in current_snapshot:
        change = h.get("sharesNumberChange", 0) or 0
        if change > 0:
            n_buying += 1
        elif change < 0:
            n_selling += 1
        else:
            n_unchanged += 1

    n_active = n_buying + n_selling
    if n_active > 0:
        buyer_seller_ratio = (n_buying - n_selling) / n_active
    else:
        buyer_seller_ratio = 0.0

    buyer_seller_score = float(np.clip(buyer_seller_ratio, -1.0, 1.0))

    # --- Composite: equal weight of three sub-signals ---
    score = (holder_score + shares_score + buyer_seller_score) / 3.0
    score = float(np.clip(score, -1.0, 1.0))

    metadata = {
        "n_institutions": n_current,
        "n_prior_institutions": n_prior,
        "n_buying": n_buying,
        "n_selling": n_selling,
        "n_unchanged": n_unchanged,
        "holder_count_change_pct": round(holder_count_change_pct * 100, 2),
        "shares_flow_pct": round(shares_flow_pct * 100, 2),
        "buyer_seller_ratio": round(buyer_seller_ratio, 3),
        "sub_scores": {
            "holder_count": round(holder_score, 4),
            "shares_flow": round(shares_score, 4),
            "buyer_seller": round(buyer_seller_score, 4),
        },
    }

    return round(score, 4), metadata


def _quarter_key(d: date) -> str:
    """Convert date to quarter string, e.g. '2025Q4'."""
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def _pit_safe_date(report_date: date, filing_lag_days: int = 45) -> date:
    """Earliest date this data would be publicly available (point-in-time safe)."""
    return report_date + timedelta(days=filing_lag_days)


def fetch_and_score_institutional_flow(
    ticker: str,
    as_of_date: date,
    fmp_client=None,
    fmp_cache=None,
    finnhub_client=None,
    finnhub_disk_cache=None,
    lookback_quarters: int = 4,
    filing_lag_days: int = 45,
) -> tuple[float, dict]:
    """
    Fetch institutional ownership data and compute flow score.

    Tries FMP first (richer data), uses Finnhub as enrichment.
    Caches results to avoid repeat API calls during backtesting.

    Point-in-time safety: only uses snapshots where
    report_date + filing_lag_days <= as_of_date.
    """
    current_snapshot = []
    prior_snapshot = []
    data_source = "none"

    # --- Try FMP data ---
    fmp_data = None
    if fmp_cache is not None:
        fmp_data = fmp_cache.get_institutional_quarterly(ticker, max_age_seconds=0)

    if fmp_data is None and fmp_client is not None:
        if hasattr(fmp_client, "get_institutional_ownership_history"):
            fmp_data = fmp_client.get_institutional_ownership_history(ticker)
        elif hasattr(fmp_client, "_client"):
            # FMPCache wrapper
            fmp_data = fmp_client._client.get_institutional_ownership_history(ticker)

        if fmp_data and fmp_cache is not None:
            fmp_cache.set_institutional_quarterly(ticker, fmp_data)

    if fmp_data:
        # Group by quarter, filter by point-in-time safety
        quarters = defaultdict(list)
        for record in fmp_data:
            rec_date_str = record.get("date", "")
            if not rec_date_str:
                continue
            try:
                rec_date = date.fromisoformat(str(rec_date_str)[:10])
            except (ValueError, TypeError):
                continue

            # Point-in-time: only use if filing would be public by as_of_date
            if _pit_safe_date(rec_date, filing_lag_days) > as_of_date:
                continue

            qkey = _quarter_key(rec_date)
            quarters[qkey].append(record)

        # Sort quarters descending
        sorted_quarters = sorted(quarters.keys(), reverse=True)

        if len(sorted_quarters) >= 1:
            current_snapshot = quarters[sorted_quarters[0]]
            data_source = "fmp"

        if len(sorted_quarters) >= 2:
            prior_snapshot = quarters[sorted_quarters[1]]

    # --- Finnhub enrichment ---
    finnhub_meta = {}
    if finnhub_client is not None:
        fh_data = None
        quarter_str = _quarter_key(as_of_date)

        if finnhub_disk_cache is not None:
            fh_data = finnhub_disk_cache.get_institutional(ticker, quarter_str)

        if fh_data is None:
            fh_data = finnhub_client.get_institutional_ownership(ticker)
            if fh_data and finnhub_disk_cache is not None:
                finnhub_disk_cache.set_institutional(ticker, quarter_str, fh_data)

        if fh_data:
            finnhub_meta = {
                "finnhub_n_holders": len(fh_data),
                "finnhub_total_shares": sum(h.get("share", 0) for h in fh_data),
            }
            if data_source == "fmp":
                data_source = "both"
            else:
                # Use Finnhub as primary if FMP failed
                if not current_snapshot and len(fh_data) >= MIN_INSTITUTIONS:
                    current_snapshot = [
                        {
                            "investorName": h.get("name", ""),
                            "sharesNumber": h.get("share", 0),
                            "sharesNumberChange": h.get("change", 0),
                        }
                        for h in fh_data
                    ]
                    data_source = "finnhub"

    score, meta = compute_institutional_flow_score(current_snapshot, prior_snapshot)
    meta["data_source"] = data_source
    meta["as_of_date"] = str(as_of_date)
    meta["finnhub_enrichment"] = finnhub_meta

    return score, meta


def compute_institutional_flow_scores(
    tickers: list[str],
    as_of_date: date,
    fmp_client=None,
    fmp_cache=None,
    finnhub_client=None,
    finnhub_disk_cache=None,
    lookback_quarters: int = 4,
) -> dict[str, tuple[float, dict]]:
    """
    Compute institutional flow scores for all tickers in the universe.

    Returns {ticker: (score, metadata)}.
    """
    results = {}
    for ticker in tickers:
        try:
            score, meta = fetch_and_score_institutional_flow(
                ticker=ticker,
                as_of_date=as_of_date,
                fmp_client=fmp_client,
                fmp_cache=fmp_cache,
                finnhub_client=finnhub_client,
                finnhub_disk_cache=finnhub_disk_cache,
                lookback_quarters=lookback_quarters,
            )
            if score != 0.0 or "error" not in meta:
                results[ticker] = (score, meta)
        except Exception as exc:
            logger.debug("Institutional flow failed for %s: %s", ticker, exc)

    return results


def blend_institutional_flow(
    signals: dict,
    flow_scores: dict[str, tuple[float, dict]],
    weight: float = 0.15,
) -> dict:
    """
    Blend institutional flow scores into SignalVector composite scores.

    Same pattern as blend_earnings_signals in earnings_signals.py.
    """
    if not flow_scores:
        return signals

    for ticker, sv in signals.items():
        entry = flow_scores.get(ticker)
        if entry is None:
            continue

        score, meta = entry
        quant_scale = 1.0 - weight
        blended = sv.composite_score * quant_scale + score * weight
        sv.composite_score = float(np.clip(blended, -1.0, 1.0))

        reclassify(sv)

        n_inst = meta.get("n_institutions", 0)
        src = meta.get("data_source", "unknown")
        sv.flags.append(f"inst_flow_w={weight:.3f}(n={n_inst},src={src})")

    return signals
