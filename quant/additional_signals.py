"""
Additional cross-sectional signals: quality, price momentum, insider activity.

These three signals use data already cached in the system:
  1. Quality/Profitability — WRDS Compustat (ROIC, gross margin)
  2. Price Momentum (12-1M) — price cache (skip most recent month)
  3. Insider Activity — Finnhub MSPR (already computed in sentiment.py)

Each returns a score in [-1, +1] following the signal pipeline pattern.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Signal 1: Quality / Profitability ─────────────────────────────────


def compute_quality_scores(
    tickers: list[str],
    wrds_provider,
    as_of_date: date,
) -> dict[str, float]:
    """
    Compute quality/profitability score from WRDS Compustat.

    Uses two metrics:
    - ROIC = Net Income / (Total Assets - Current Liabilities)
    - Gross Margin = (Revenue - COGS) / Revenue

    Both are TTM (trailing twelve months) from the most recent 4 quarters.
    Score: z-scored cross-sectionally, so high-quality relative to peers = positive.
    """
    scores = {}

    for ticker in tickers:
        try:
            fundamentals = wrds_provider.get_balance_sheet_quarterly(
                ticker,
                limit=4,
                as_of_date=as_of_date,
            )
            if not fundamentals or len(fundamentals) < 1:
                continue

            latest = fundamentals[0]

            # ROIC = NI / (Total Assets - Current Liabilities)
            ni = latest.get("netIncome") or latest.get("niq")
            ta = latest.get("totalAssets") or latest.get("atq")
            cl = latest.get("totalCurrentLiabilities") or latest.get("lctq")

            roic = None
            if ni is not None and ta is not None and cl is not None:
                invested = float(ta) - float(cl)
                if invested > 0:
                    # Annualize from quarterly
                    roic = (float(ni) * 4) / invested

            # Gross Margin = (Revenue - COGS) / Revenue
            rev = latest.get("revenue") or latest.get("saleq") or latest.get("revtq")
            cogs = latest.get("costOfRevenue") or latest.get("cogsq")

            gross_margin = None
            if rev is not None and cogs is not None and float(rev) > 0:
                gross_margin = (float(rev) - float(cogs)) / float(rev)

            # Blend: 50% ROIC, 50% gross margin (both available)
            # or 100% of whichever is available
            components = []
            if roic is not None:
                # Map ROIC to [-1, +1]: 20%+ → +1, 0% → 0, -20% → -1
                roic_score = float(np.clip(roic / 0.20, -1.0, 1.0))
                components.append(roic_score)
            if gross_margin is not None:
                # Map margin to [-1, +1]: 60%+ → +1, 30% → 0, 0% → -1
                margin_score = float(np.clip((gross_margin - 0.30) / 0.30, -1.0, 1.0))
                components.append(margin_score)

            if components:
                scores[ticker] = round(float(np.mean(components)), 4)

        except Exception as exc:
            logger.debug("Quality computation failed for %s: %s", ticker, exc)

    return scores


# ── Signal 2: Price Momentum (12-1 Month) ────────────────────────────


def compute_price_momentum_scores(
    universe_data: dict[str, pd.DataFrame],
    as_of_date: pd.Timestamp,
    skip_recent_days: int = 21,
    lookback_days: int = 252,
) -> dict[str, float]:
    """
    Classic 12-1 month price momentum.

    Computes return from 12 months ago to 1 month ago (skipping the most
    recent month to avoid the short-term reversal effect). This is the
    Jegadeesh & Titman (1993) momentum signal — the basis of the Carhart
    momentum factor.

    Score: raw return mapped to [-1, +1] via winsorized z-score.
    """
    raw_returns = {}

    for ticker, df in universe_data.items():
        available = df[df.index <= as_of_date]
        if len(available) < lookback_days:
            continue

        # Price 1 month ago (skip recent)
        recent_idx = max(0, len(available) - skip_recent_days)
        if recent_idx < lookback_days - skip_recent_days:
            continue

        price_1m_ago = float(available.iloc[recent_idx - 1]["close"])

        # Price 12 months ago
        start_idx = max(0, len(available) - lookback_days)
        price_12m_ago = float(available.iloc[start_idx]["close"])

        if price_12m_ago > 0:
            ret = (price_1m_ago - price_12m_ago) / price_12m_ago
            raw_returns[ticker] = ret

    if len(raw_returns) < 5:
        return {}

    # Cross-sectional z-score
    returns_array = np.array(list(raw_returns.values()))

    # Winsorize at 2.5/97.5
    low = np.percentile(returns_array, 2.5)
    high = np.percentile(returns_array, 97.5)
    returns_array = np.clip(returns_array, low, high)

    mean_ret = np.mean(returns_array)
    std_ret = np.std(returns_array)

    if std_ret < 1e-8:
        return {t: 0.0 for t in raw_returns}

    scores = {}
    tickers_list = list(raw_returns.keys())
    for i, ticker in enumerate(tickers_list):
        raw = np.clip(raw_returns[ticker], low, high)
        z = (raw - mean_ret) / std_ret
        scores[ticker] = round(float(np.clip(z / 3.0, -1.0, 1.0)), 4)

    return scores


# ── Signal 3: Insider Activity (standalone) ───────────────────────────


def compute_insider_scores(
    tickers: list[str],
    as_of_date: pd.Timestamp,
    finnhub_client=None,
    sentiment_cache=None,
    lookback_months: int = 3,
) -> dict[str, float]:
    """
    Standalone insider trading signal from Finnhub MSPR.

    Currently insider MSPR is blended 70/30 into the news sentiment signal.
    This extracts it as an independent signal so cross-sectional normalization
    can evaluate it separately.

    MSPR (Monthly Share Purchase Ratio) is already in [-1, +1]:
      +1 = insiders only buying
      -1 = insiders only selling
    """
    from quant.sentiment import compute_insider_sentiment_score

    scores = {}
    for ticker in tickers:
        try:
            result = compute_insider_sentiment_score(
                ticker,
                as_of_date,
                lookback_months=lookback_months,
                client=finnhub_client,
                disk_cache=sentiment_cache,
            )
            if result.score != 0.0:
                scores[ticker] = round(float(result.score), 4)
        except Exception as exc:
            logger.debug("Insider score failed for %s: %s", ticker, exc)

    return scores
