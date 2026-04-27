"""
Factor baselines for the IC audit (Session 2 / IC-2, IC-3, IC-4).

Implements three academic / industry baselines so the in-house fundamental
signals can be honestly ranked against them:

1. Piotroski F-score (1-9 binary tests)        — IC-2 (P0)
2. QMJ proxy (Asness Quality-Minus-Junk)       — IC-3 (P1)
3. HML proxy (Fama-French value, B/M)          — IC-4 (P1)

All functions are PIT-safe: they query the WRDS Compustat / IBES PIT cache
with `WHERE rdq <= as_of_date` discipline and never use restated snapshots.

Returns:
- Piotroski returns int in [0, 9] (or None if data missing)
- QMJ / HML return float scores; cross-sectional z-scoring happens at the
  panel level inside the IC runner, NOT here. Each function returns the
  raw component (e.g. book-to-market ratio) so callers can z-score across
  the universe at a single date.

Design choice: we keep these as per-ticker scalar functions matching the
existing signal-function pattern. The caller batches across the universe.
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────────

def _f(row: dict, *keys: str) -> Optional[float]:
    """Fetch the first non-None numeric value for any of `keys`. None on miss.

    Critical: we deliberately do NOT default to 0 — see the
    `project_silent_zeros` memory rule. None propagates to NaN downstream.
    """
    for k in keys:
        v = row.get(k)
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isnan(f):
            continue
        return f
    return None


def _safe_div(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or den is None or den == 0:
        return None
    return num / den


# ── IC-2: Piotroski F-score ─────────────────────────────────────────────

def compute_piotroski_score(
    ticker: str,
    as_of_date: date,
    wrds_store,
) -> Optional[int]:
    """
    Piotroski (2000) F-score: 9 binary tests of fundamental health.

    Categories
        Profitability (4):
            1. ROA > 0      (NI / TotalAssets)
            2. CFO > 0      (Operating Cash Flow)
            3. ΔROA > 0     (current vs year-ago)
            4. Accruals     (CFO > Net Income — earnings-quality test)
        Leverage / liquidity / source (3):
            5. ΔLTDebt < 0  (debt declining)
            6. ΔCurrent ratio > 0   (liquidity improving)
            7. No new shares issued YoY (cshoq_t <= cshoq_t-4)
        Operating efficiency (2):
            8. ΔGross margin > 0
            9. ΔAsset turnover > 0  (Sales / TotalAssets)

    Returns int in [0, 9], or None if too much data is missing to score.

    PIT-safe: uses WRDS PIT store with `rdq <= as_of_date`. We need at
    minimum quarter t and quarter t-4 (year-ago) so the function returns
    None if either is unavailable. Compustat `oancfy` is YTD operating
    cash flow — for ROA / accruals we use trailing 4 quarters where possible.

    Args:
        ticker: equity ticker (e.g. "AAPL")
        as_of_date: PIT date — only filings with rdq <= as_of_date considered
        wrds_store: WRDSPointInTimeStore instance
    """
    date_str = str(as_of_date)
    rows = wrds_store.get_fundamentals_as_of(ticker, date_str, n_quarters=8)

    # We need q_t and q_t-4 at minimum
    if not rows or len(rows) < 5:
        return None

    q_now_fmp = rows[0]
    q_yago_fmp = rows[4]

    # Convert FMP-style names back to the Compustat fields we need. The
    # store's `_compustat_to_fmp_dict` already mapped them, so we read
    # the FMP keys here.
    def _fund(row, key_fmp):
        return _f(row, key_fmp)

    # Field mapping (FMP-key -> Compustat originals)
    # totalAssets <- atq, netIncome <- niq, operatingCashFlow <- oancfy (YTD!)
    # totalCurrentAssets <- actq, totalCurrentLiabilities <- lctq
    # longTermDebt <- dlttq, sharesOutstanding <- cshoq, revenue <- saleq/revtq
    # costOfRevenue <- cogsq

    # ── Profitability ──────────────────────────────────────────────────
    ta_now = _fund(q_now_fmp, "totalAssets")
    ta_yago = _fund(q_yago_fmp, "totalAssets")
    ni_now = _fund(q_now_fmp, "netIncome")
    ni_yago = _fund(q_yago_fmp, "netIncome")
    cfo_now_ytd = _fund(q_now_fmp, "operatingCashFlow")  # YTD per Compustat oancfy

    # oancfy is YTD — most informative comparison is sign (positive YTD CFO).
    # For the accruals test we want quarterly CFO; approximate by using YTD
    # vs the prior YTD (or sign of YTD) — we'll use the sign of YTD CFO
    # which is a reasonable proxy. Document this as a simplification.

    score = 0
    valid_tests = 0

    roa_now = _safe_div(ni_now, ta_now)
    roa_yago = _safe_div(ni_yago, ta_yago)

    # 1. ROA > 0
    if roa_now is not None:
        valid_tests += 1
        if roa_now > 0:
            score += 1

    # 2. CFO > 0  (using YTD as proxy)
    if cfo_now_ytd is not None:
        valid_tests += 1
        if cfo_now_ytd > 0:
            score += 1

    # 3. ΔROA > 0
    if roa_now is not None and roa_yago is not None:
        valid_tests += 1
        if roa_now > roa_yago:
            score += 1

    # 4. Accruals: CFO > Net Income
    # Note: cfo_now_ytd is YTD, ni_now is quarterly — not directly comparable.
    # Use sign-of-difference as a softer accruals quality test: positive
    # YTD CFO with positive NI is constructive. This is a documented simplification.
    if cfo_now_ytd is not None and ni_now is not None:
        valid_tests += 1
        # Approximate: scale ni quarterly to annual (×4) and compare to YTD CFO.
        # For an early-fiscal-year quarter this is generous; we accept the
        # bias because the goal is a baseline floor benchmark, not perfect.
        ni_annualized = ni_now * 4
        if cfo_now_ytd > ni_annualized:
            score += 1

    # ── Leverage / liquidity / source ───────────────────────────────
    ltd_now = _fund(q_now_fmp, "longTermDebt")
    ltd_yago = _fund(q_yago_fmp, "longTermDebt")
    ca_now = _fund(q_now_fmp, "totalCurrentAssets")
    cl_now = _fund(q_now_fmp, "totalCurrentLiabilities")
    ca_yago = _fund(q_yago_fmp, "totalCurrentAssets")
    cl_yago = _fund(q_yago_fmp, "totalCurrentLiabilities")
    cur_now = _safe_div(ca_now, cl_now)
    cur_yago = _safe_div(ca_yago, cl_yago)
    sho_now = _fund(q_now_fmp, "sharesOutstanding")
    sho_yago = _fund(q_yago_fmp, "sharesOutstanding")

    # 5. ΔLong-term debt < 0  (paying down debt)
    if ltd_now is not None and ltd_yago is not None:
        valid_tests += 1
        if ltd_now < ltd_yago:
            score += 1

    # 6. ΔCurrent ratio > 0
    if cur_now is not None and cur_yago is not None:
        valid_tests += 1
        if cur_now > cur_yago:
            score += 1

    # 7. No new shares issued YoY
    if sho_now is not None and sho_yago is not None:
        valid_tests += 1
        # Allow tiny float noise (up to 0.1%)
        if sho_now <= sho_yago * 1.001:
            score += 1

    # ── Operating efficiency ────────────────────────────────────────
    rev_now = _fund(q_now_fmp, "revenue")
    rev_yago = _fund(q_yago_fmp, "revenue")
    cogs_now = _fund(q_now_fmp, "costOfRevenue")
    cogs_yago = _fund(q_yago_fmp, "costOfRevenue")

    gm_now = None
    gm_yago = None
    if rev_now is not None and cogs_now is not None and rev_now != 0:
        gm_now = (rev_now - cogs_now) / rev_now
    if rev_yago is not None and cogs_yago is not None and rev_yago != 0:
        gm_yago = (rev_yago - cogs_yago) / rev_yago

    # 8. ΔGross margin > 0
    if gm_now is not None and gm_yago is not None:
        valid_tests += 1
        if gm_now > gm_yago:
            score += 1

    # 9. ΔAsset turnover > 0  (Sales / TotalAssets)
    at_now = _safe_div(rev_now, ta_now)
    at_yago = _safe_div(rev_yago, ta_yago)
    if at_now is not None and at_yago is not None:
        valid_tests += 1
        if at_now > at_yago:
            score += 1

    # If we couldn't run at least 5 of 9 tests the score is too noisy
    if valid_tests < 5:
        return None

    # If we ran fewer than 9, scale up so the score is on the [0,9] scale.
    # Document this as a simplification — purer would be returning a
    # float or marking partial-coverage. We round to the nearest int.
    if valid_tests < 9:
        score = int(round(score * 9.0 / valid_tests))

    return max(0, min(9, score))


# ── IC-3: QMJ proxy ─────────────────────────────────────────────────────

def compute_qmj_score(
    ticker: str,
    as_of_date: date,
    wrds_store,
) -> Optional[float]:
    """
    Quality-Minus-Junk proxy (Asness, Frazzini, Pedersen 2019).

    Composite of four pillars (each component z-scored at panel level by caller):
        - Profitability:  Gross profit / Total assets
                          = (revenue - cogs) / atq
        - Growth:         5y EPS growth proxy (we have ~13y; use trailing 5y)
                          Approximated as (epsfxq_t - epsfxq_t-20q) / |epsfxq_t-20q|
                          Falls back to (eps_t - eps_t-4) if 5y unavailable.
        - Safety:         Inverse leverage = -(longTermDebt / totalAssets)
                          Higher = safer (lower leverage)
        - Payout:         We do NOT have dividend data in the WRDS PIT store,
                          so we proxy with retained-earnings-style: NI/TA
                          (return on assets) which is the closest available.
                          DOCUMENTED SIMPLIFICATION.

    Returns a single composite raw score: equal-weighted sum of the four
    components. The IC runner z-scores cross-sectionally at the panel
    level. Returns None if data is too sparse.
    """
    date_str = str(as_of_date)
    rows = wrds_store.get_fundamentals_as_of(ticker, date_str, n_quarters=24)

    if not rows or len(rows) < 5:
        return None

    q = rows[0]
    q_4 = rows[4] if len(rows) > 4 else None
    q_20 = rows[20] if len(rows) > 20 else None

    # Profitability
    rev = _f(q, "revenue")
    cogs = _f(q, "costOfRevenue")
    ta = _f(q, "totalAssets")
    profitability = None
    if rev is not None and cogs is not None and ta and ta > 0:
        profitability = (rev - cogs) / ta

    # Growth (5y EPS or 1y fallback)
    eps_now = _f(q, "eps")
    eps_5y = _f(q_20, "eps") if q_20 else None
    eps_1y = _f(q_4, "eps") if q_4 else None

    growth = None
    if eps_now is not None and eps_5y is not None and abs(eps_5y) > 1e-6:
        growth = (eps_now - eps_5y) / abs(eps_5y)
    elif eps_now is not None and eps_1y is not None and abs(eps_1y) > 1e-6:
        # Fallback: 1y growth scaled to 5y equivalent (×5 is overkill; we
        # use 1y growth raw — cross-sectional z-score will normalize anyway)
        growth = (eps_now - eps_1y) / abs(eps_1y)

    # Safety: inverse leverage
    ltd = _f(q, "longTermDebt")
    safety = None
    if ltd is not None and ta and ta > 0:
        safety = -(ltd / ta)

    # Payout proxy: ROA
    ni = _f(q, "netIncome")
    payout = None
    if ni is not None and ta and ta > 0:
        payout = ni / ta

    # Need at least 2 of 4 to proceed
    components = [c for c in (profitability, growth, safety, payout) if c is not None]
    if len(components) < 2:
        return None

    # Equal-weighted average over available components.
    # The caller will cross-sectionally z-score this at the panel level.
    return float(sum(components) / len(components))


# ── IC-4: HML proxy ─────────────────────────────────────────────────────

def compute_hml_score(
    ticker: str,
    as_of_date: date,
    wrds_store,
    price: Optional[float] = None,
) -> Optional[float]:
    """
    HML (Fama-French value) proxy: book-to-market ratio.

    book_to_market = totalStockholdersEquity / market_cap
                   = ceqq / (price × cshoq)

    Higher = "value" (cheap relative to book).

    The caller passes the latest price (e.g. from the price cache, dividend-
    adjusted close as of `as_of_date`). If price is None we fall back to
    a synthetic market cap estimate using ceqq alone, which is incorrect
    but lets the function return *something* deterministic. Recommended:
    always pass a price.

    PIT-safe: book equity from WRDS PIT (rdq filtered); price is point-in-time
    from the price cache.

    Returns a raw B/M ratio (cross-sectional z-scoring done by caller).
    Returns None if equity or shares missing.
    """
    date_str = str(as_of_date)
    rows = wrds_store.get_fundamentals_as_of(ticker, date_str, n_quarters=2)
    if not rows:
        return None

    q = rows[0]
    book_equity = _f(q, "totalStockholdersEquity")
    shares = _f(q, "sharesOutstanding")

    if book_equity is None or book_equity <= 0:
        # Negative book value is rare but real (post-buyback). HML is
        # undefined in that case — flag NaN rather than fake a score.
        return None

    if price is None or shares is None or shares <= 0:
        # Without market cap we cannot compute B/M. Return None so the
        # caller propagates NaN rather than fabricating a value.
        return None

    market_cap = price * shares
    if market_cap <= 0:
        return None

    return float(book_equity / market_cap)
