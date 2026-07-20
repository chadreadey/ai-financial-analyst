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
        return 0.0, {
            "error": "insufficient institutions",
            "n_institutions": len(current_snapshot) if current_snapshot else 0,
        }

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
    prior_total = (
        sum(h.get("sharesNumber", 0) for h in prior_snapshot) if prior_snapshot else current_total
    )

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


# ── Point-in-time guard ───────────────────────────────────────────────
# 13F filings have a statutory deadline of quarter-end + 45 calendar days
# (SEC Rule 13F-1). A backtest at as_of_date must therefore NOT consume
# any quarter-end whose filing window has not yet closed — otherwise it
# is using data that did not exist on the trade date (look-ahead bias).
# See `feedback_backtest_discipline` memory rule (no look-ahead).
FILING_LAG_DAYS = 45


def _pit_safe_date(report_date: date, filing_lag_days: int = FILING_LAG_DAYS) -> date:
    """Earliest date this data would be publicly available (point-in-time safe)."""
    return report_date + timedelta(days=filing_lag_days)


def _is_pit_safe_quarter(
    quarter_end_date: date,
    as_of_date: date,
    filing_lag_days: int = FILING_LAG_DAYS,
) -> bool:
    """
    Return True iff the 13F filing window for `quarter_end_date` has closed
    by `as_of_date` and the data may therefore be used at `as_of_date`
    without look-ahead bias.

    Example: quarter_end = 2025-03-31, filing deadline = 2025-05-15.
      - as_of_date = 2025-04-01 → False (filings not due yet)
      - as_of_date = 2025-05-15 → True (deadline reached)
      - as_of_date = 2025-06-01 → True (well past deadline)
    """
    deadline = quarter_end_date + timedelta(days=filing_lag_days)
    return deadline <= as_of_date


# ── Caches ────────────────────────────────────────────────────────────
# _raw_cache: ticker → full FMP/Finnhub data blob (fetched once per ticker)
# _wrds_cache: ticker → list of WRDS 13F quarterly rows (fetched once per ticker)
# _score_cache: (ticker, quarter_key) → (score, metadata) (computed once per quarter)
# All module-level so they persist across rebalance dates and CPCV combos.
_raw_cache: dict[str, list[dict] | None] = {}
_finnhub_raw_cache: dict[str, list[dict] | None] = {}
_wrds_cache: dict[str, list[dict] | None] = {}
_score_cache: dict[tuple[str, str], tuple[float, dict]] = {}


def _fetch_wrds_data(
    ticker: str,
    wrds_store=None,
) -> list[dict]:
    """
    Fetch pre-aggregated 13F holdings from WRDS store (tr_13f.s34).

    This is the PRIMARY data source — academic-grade, free via university,
    covers 2014-present with full position-level aggregation.

    Returns list of quarterly dicts with: ticker, rdate, n_holders,
    total_shares, n_buying, n_selling, n_unchanged.
    """
    if ticker in _wrds_cache:
        return _wrds_cache[ticker] or []

    if wrds_store is None:
        _wrds_cache[ticker] = None
        return []

    try:
        # Pull all available quarters (large as_of_date, many quarters)
        rows = wrds_store.get_inst_holdings_as_of(ticker, "2099-12-31", n_quarters=100)
        _wrds_cache[ticker] = rows
        return rows
    except Exception as exc:
        logger.debug("WRDS 13F fetch failed for %s: %s", ticker, exc)
        _wrds_cache[ticker] = None
        return []


def _fetch_fmp_data(
    ticker: str,
    fmp_client=None,
    fmp_cache=None,
) -> list[dict]:
    """
    Fetch FMP institutional data for a ticker. Fetched ONCE per ticker,
    then cached in-memory and in SQLite. Empty results are cached too
    (negative caching) to avoid repeated failed API calls.
    """
    # Check in-memory cache first (fastest)
    if ticker in _raw_cache:
        return _raw_cache[ticker] or []

    # Check SQLite cache
    if fmp_cache is not None:
        cached = fmp_cache.get_institutional_quarterly(ticker, max_age_seconds=0)
        if cached is not None:  # None = not in cache; [] = cached empty result
            _raw_cache[ticker] = cached
            return cached

    # Fetch from API
    fmp_data = []
    if fmp_client is not None:
        if hasattr(fmp_client, "get_institutional_ownership_history"):
            fmp_data = fmp_client.get_institutional_ownership_history(ticker)
        elif hasattr(fmp_client, "_client"):
            fmp_data = fmp_client._client.get_institutional_ownership_history(ticker)

    # Cache result (including empty — negative caching)
    if fmp_cache is not None:
        fmp_cache.set_institutional_quarterly(ticker, fmp_data)
    _raw_cache[ticker] = fmp_data

    return fmp_data


def _fetch_finnhub_data(
    ticker: str,
    finnhub_client=None,
    finnhub_disk_cache=None,
) -> list[dict]:
    """
    Fetch Finnhub institutional data for a ticker. Fetched ONCE per ticker,
    cached in-memory and on disk. Empty results cached (negative caching).
    """
    if ticker in _finnhub_raw_cache:
        return _finnhub_raw_cache[ticker] or []

    # Check disk cache
    if finnhub_disk_cache is not None:
        cached = finnhub_disk_cache.get_institutional(ticker, "latest")
        if cached is not None:
            _finnhub_raw_cache[ticker] = cached
            return cached

    # Fetch from API
    fh_data = []
    if finnhub_client is not None:
        fh_data = finnhub_client.get_institutional_ownership(ticker)

    # Cache result (including empty)
    if finnhub_disk_cache is not None:
        finnhub_disk_cache.set_institutional(ticker, "latest", fh_data)
    _finnhub_raw_cache[ticker] = fh_data

    return fh_data


def _pit_quarter_key(as_of_date: date, filing_lag_days: int = 45) -> str:
    """
    Determine which quarter's data is available at as_of_date.

    Institutional data is quarterly and only changes when a new quarter's
    filings become public. The score for any as_of_date within the same
    PIT-safe quarter window is identical.
    """
    # Walk back to find the latest quarter-end whose filing is public
    # Q4 (Dec 31) → available ~Feb 14; Q1 (Mar 31) → available ~May 15, etc.
    for q_end_month in [12, 9, 6, 3]:
        q_end = date(as_of_date.year, q_end_month, {12: 31, 9: 30, 6: 30, 3: 31}[q_end_month])
        if q_end.year > as_of_date.year:
            continue
        if _pit_safe_date(q_end, filing_lag_days) <= as_of_date:
            return _quarter_key(q_end)
    # Try prior year Q4
    q_end = date(as_of_date.year - 1, 12, 31)
    if _pit_safe_date(q_end, filing_lag_days) <= as_of_date:
        return _quarter_key(q_end)
    return ""


def _score_from_wrds_rows(
    rows: list[dict],
    as_of_date: date,
    filing_lag_days: int = 45,
) -> tuple[float, dict] | None:
    """
    Compute institutional flow score from pre-aggregated WRDS 13F rows.

    Each row has: ticker, rdate, n_holders, total_shares, n_buying, n_selling, n_unchanged.
    Returns (score, metadata) or None if insufficient data.
    """
    # Filter by point-in-time: only use quarters whose filings are public
    pit_rows = []
    for r in rows:
        rdate = date.fromisoformat(str(r["rdate"])[:10])
        if _pit_safe_date(rdate, filing_lag_days) <= as_of_date:
            pit_rows.append(r)

    if not pit_rows:
        return None

    # Sort descending by rdate
    pit_rows.sort(key=lambda r: r["rdate"], reverse=True)
    current = pit_rows[0]
    prior = pit_rows[1] if len(pit_rows) >= 2 else None

    n_current = current.get("n_holders", 0) or 0
    if n_current < MIN_INSTITUTIONS:
        return None

    # Sub-signal 1: Holder count change
    n_prior = (prior.get("n_holders", 0) or 0) if prior else n_current
    holder_change_pct = (n_current - n_prior) / n_prior if n_prior > 0 else 0.0
    holder_score = float(np.clip(holder_change_pct / 0.50, -1.0, 1.0))

    # Sub-signal 2: Shares flow
    current_shares = current.get("total_shares", 0) or 0
    prior_shares = (prior.get("total_shares", 0) or 0) if prior else current_shares
    shares_flow_pct = (current_shares - prior_shares) / prior_shares if prior_shares > 0 else 0.0
    shares_score = float(np.clip(shares_flow_pct / 0.30, -1.0, 1.0))

    # Sub-signal 3: Buyer/seller ratio
    n_buying = current.get("n_buying", 0) or 0
    n_selling = current.get("n_selling", 0) or 0
    n_unchanged = current.get("n_unchanged", 0) or 0
    n_active = n_buying + n_selling
    buyer_seller_ratio = (n_buying - n_selling) / n_active if n_active > 0 else 0.0
    buyer_seller_score = float(np.clip(buyer_seller_ratio, -1.0, 1.0))

    # Composite
    score = (holder_score + shares_score + buyer_seller_score) / 3.0
    score = float(np.clip(score, -1.0, 1.0))

    metadata = {
        "n_institutions": n_current,
        "n_prior_institutions": n_prior,
        "n_buying": n_buying,
        "n_selling": n_selling,
        "n_unchanged": n_unchanged,
        "holder_count_change_pct": round(holder_change_pct * 100, 2),
        "shares_flow_pct": round(shares_flow_pct * 100, 2),
        "buyer_seller_ratio": round(buyer_seller_ratio, 3),
        "sub_scores": {
            "holder_count": round(holder_score, 4),
            "shares_flow": round(shares_score, 4),
            "buyer_seller": round(buyer_seller_score, 4),
        },
        "latest_rdate": current["rdate"],
    }

    return round(score, 4), metadata


def fetch_and_score_institutional_flow(
    ticker: str,
    as_of_date: date,
    wrds_store=None,
    fmp_client=None,
    fmp_cache=None,
    finnhub_client=None,
    finnhub_disk_cache=None,
    lookback_quarters: int = 4,
    filing_lag_days: int = 45,
) -> tuple[float, dict]:
    """
    Fetch institutional ownership data and compute flow score.

    Data source priority:
    1. WRDS tr_13f.s34 (academic, pre-aggregated in SQLite — best quality)
    2. FMP institutional ownership API (paid tier)
    3. Finnhub institutional ownership (paid tier)

    Score memoization: (ticker, quarter) computed once, reused across
    all CPCV combos and rebalance dates within the same quarter.
    """
    # --- Score memoization: same ticker + same quarter = same score ---
    pit_qkey = _pit_quarter_key(as_of_date, filing_lag_days)
    cache_key = (ticker, pit_qkey)
    if cache_key in _score_cache:
        return _score_cache[cache_key]

    # --- Try WRDS first (primary, best quality) ---
    wrds_rows = _fetch_wrds_data(ticker, wrds_store)
    if wrds_rows:
        result = _score_from_wrds_rows(wrds_rows, as_of_date, filing_lag_days)
        if result is not None:
            score, meta = result
            meta["data_source"] = "wrds_13f"
            meta["as_of_date"] = str(as_of_date)
            if pit_qkey:
                _score_cache[cache_key] = (score, meta)
            return score, meta

    # --- Fallback: FMP data ---
    current_snapshot = []
    prior_snapshot = []
    data_source = "none"

    fmp_data = _fetch_fmp_data(ticker, fmp_client, fmp_cache)

    if fmp_data:
        # Bucket FMP records by quarter-end date so we can pick the latest
        # PIT-safe quarter for `current_snapshot` and the next-latest for
        # `prior_snapshot`.
        quarters: dict[str, list[dict]] = defaultdict(list)
        quarter_end_dates: dict[str, date] = {}
        for record in fmp_data:
            rec_date_str = record.get("date", "")
            if not rec_date_str:
                continue
            try:
                rec_date = date.fromisoformat(str(rec_date_str)[:10])
            except (ValueError, TypeError):
                continue
            qkey = _quarter_key(rec_date)
            quarters[qkey].append(record)
            # Track the latest report date seen per bucket (handles records
            # that may carry slightly different dates within the same quarter)
            existing = quarter_end_dates.get(qkey)
            if existing is None or rec_date > existing:
                quarter_end_dates[qkey] = rec_date

        # PIT GUARD: walk quarters newest → oldest and take only those whose
        # 13F filing deadline (quarter_end + 45d) has elapsed by as_of_date.
        # Without this guard, a backtest at as_of_date = 2025-04-01 could
        # consume Q1 2025 data (quarter ends 2025-03-31, due ~2025-05-15)
        # that did not exist on the trade date. Both `current_snapshot` and
        # `prior_snapshot` (used for QoQ comparison) must be PIT-safe.
        pit_safe_quarters: list[str] = [
            qkey
            for qkey in sorted(quarters.keys(), reverse=True)
            if _is_pit_safe_quarter(quarter_end_dates[qkey], as_of_date, filing_lag_days)
        ]

        if len(pit_safe_quarters) >= 1:
            current_snapshot = quarters[pit_safe_quarters[0]]
            data_source = "fmp"
        if len(pit_safe_quarters) >= 2:
            prior_snapshot = quarters[pit_safe_quarters[1]]

    # --- Fallback: Finnhub enrichment ---
    finnhub_meta = {}
    fh_data = _fetch_finnhub_data(ticker, finnhub_client, finnhub_disk_cache)

    # PIT GUARD for Finnhub: each row carries a `filingDate` — a row only
    # becomes public on its filingDate, so any row with filingDate > as_of_date
    # would not have existed at the trade date. Filter those out before use.
    # If a row has no filingDate, conservatively keep it only when its enclosing
    # quarter (inferred via the 45-day rule from `today`'s prior quarter-end)
    # is past — i.e. drop rows that lack a verifiable filing date but whose
    # implicit quarter cannot be confirmed PIT-safe.
    pit_safe_fh_data: list[dict] = []
    for h in fh_data or []:
        filing_str = h.get("filingDate") or h.get("filing_date") or ""
        if filing_str:
            try:
                filing_d = date.fromisoformat(str(filing_str)[:10])
            except (ValueError, TypeError):
                # Unparseable filing date → drop (cannot verify PIT-safety)
                continue
            if filing_d <= as_of_date:
                pit_safe_fh_data.append(h)
        # Rows with no filingDate are dropped — we cannot confirm PIT safety.

    if pit_safe_fh_data:
        finnhub_meta = {
            "finnhub_n_holders": len(pit_safe_fh_data),
            "finnhub_total_shares": sum(h.get("share", 0) for h in pit_safe_fh_data),
        }
        if data_source == "fmp":
            data_source = "both"
        elif not current_snapshot and len(pit_safe_fh_data) >= MIN_INSTITUTIONS:
            current_snapshot = [
                {
                    "investorName": h.get("name", ""),
                    "sharesNumber": h.get("share", 0),
                    "sharesNumberChange": h.get("change", 0),
                }
                for h in pit_safe_fh_data
            ]
            data_source = "finnhub"

    score, meta = compute_institutional_flow_score(current_snapshot, prior_snapshot)
    meta["data_source"] = data_source
    meta["as_of_date"] = str(as_of_date)
    meta["finnhub_enrichment"] = finnhub_meta

    # Cache the computed score
    if pit_qkey:
        _score_cache[cache_key] = (score, meta)

    return score, meta


def prefetch_institutional_data(
    tickers: list[str],
    wrds_store=None,
    fmp_client=None,
    fmp_cache=None,
    finnhub_client=None,
    finnhub_disk_cache=None,
) -> dict[str, int]:
    """
    Pre-fetch and cache institutional data for all tickers.

    Call this ONCE before backtesting to warm the cache. All subsequent
    calls to fetch_and_score_institutional_flow will hit cache only.

    Returns {ticker: n_records} for tickers with data.
    """
    stats = {}
    for ticker in tickers:
        wrds_data = _fetch_wrds_data(ticker, wrds_store)
        fmp_data = _fetch_fmp_data(ticker, fmp_client, fmp_cache)
        fh_data = _fetch_finnhub_data(ticker, finnhub_client, finnhub_disk_cache)
        n = len(wrds_data) + len(fmp_data) + len(fh_data)
        if n > 0:
            stats[ticker] = n
        logger.debug(
            "Prefetched %s: %d WRDS + %d FMP + %d Finnhub records",
            ticker,
            len(wrds_data),
            len(fmp_data),
            len(fh_data),
        )
    return stats


def compute_institutional_flow_scores(
    tickers: list[str],
    as_of_date: date,
    wrds_store=None,
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
                wrds_store=wrds_store,
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
    Set institutional flow scores on SignalVectors for cross-sectional normalization.

    No longer modifies composite_score directly — just stores the flow
    score on sv.institutional_flow_score. Composite is built later
    by compute_normalized_composite after cross-sectional normalization.
    """
    if not flow_scores:
        return signals

    for ticker, sv in signals.items():
        entry = flow_scores.get(ticker)
        if entry is None:
            continue

        score, meta = entry
        sv.institutional_flow_score = score

        n_inst = meta.get("n_institutions", 0)
        src = meta.get("data_source", "unknown")
        sv.flags.append(f"inst_flow(n={n_inst},src={src})")

    return signals
