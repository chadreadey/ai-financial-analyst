"""
News sentiment signal from Finnhub company news.

Uses VADER sentiment on headlines (no GPU, deterministic, pure Python).
Returns SignalResult in [-1, +1] — compatible with the quant signal framework.

Point-in-time safety: only articles with datetime < as_of_date are scored.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from quant.signals import SignalResult

logger = logging.getLogger(__name__)

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _vader = SentimentIntensityAnalyzer()
except ImportError:
    _vader = None
    logger.debug("vaderSentiment not installed — news sentiment will return 0.0")


def _score_headline(text: str) -> float:
    """VADER compound score for a single headline. Returns [-1, +1]."""
    if _vader is None:
        return 0.0
    return _vader.polarity_scores(text)["compound"]


def compute_news_sentiment_score(
    ticker: str,
    as_of_date: pd.Timestamp,
    news_window_days: int = 30,
    client=None,
    disk_cache=None,
    min_articles: int = 3,
) -> SignalResult:
    """
    Compute news sentiment signal for a ticker as of a date.

    Args:
        ticker: Stock symbol
        as_of_date: Rebalance date — only news before this date is used
        news_window_days: Days of news to consider
        client: FinnhubClient (or FinnhubCache)
        disk_cache: SentimentDiskCache for persistent storage
        min_articles: Return 0.0 if fewer articles found

    Returns:
        SignalResult with score in [-1, +1]
    """
    if _vader is None:
        return SignalResult(0.0, "vaderSentiment not installed", {"n_articles": 0})

    from_date = (as_of_date - timedelta(days=news_window_days)).strftime("%Y-%m-%d")
    to_date = as_of_date.strftime("%Y-%m-%d")
    sym = ticker.upper()

    # Try disk cache first — works even without a live client
    articles = None
    if disk_cache is not None:
        articles = disk_cache.load_news(sym, from_date, to_date)

    # Fall back to live API only if cache missed and client is available
    if articles is None:
        if client is None:
            return SignalResult(0.0, "no finnhub client and no cache hit", {"n_articles": 0})
        articles = client.get_company_news(sym, from_date, to_date)
        if disk_cache is not None:
            disk_cache.save_news(sym, from_date, to_date, articles)

    # Point-in-time filter: only articles published BEFORE as_of_date
    cutoff_ts = as_of_date.timestamp()
    filtered = [
        a for a in articles
        if a.get("datetime", 0) < cutoff_ts
    ]

    n = len(filtered)
    if n < min_articles:
        return SignalResult(
            0.0,
            f"{n} articles (below min {min_articles})",
            {"n_articles": n, "window_days": news_window_days},
        )

    # Score each headline + summary
    scores = []
    for article in filtered:
        text = article.get("headline", "")
        summary = article.get("summary", "")
        if summary:
            text = f"{text}. {summary}"
        if text.strip():
            scores.append(_score_headline(text))

    if not scores:
        return SignalResult(0.0, "no scorable text", {"n_articles": n})

    mean_score = sum(scores) / len(scores)
    # Clip to [-1, +1] (VADER compound is already in this range)
    score = max(-1.0, min(1.0, mean_score))

    detail = f"{len(scores)} articles, mean VADER={score:.3f}"
    return SignalResult(
        score=round(score, 4),
        detail=detail,
        metadata={
            "n_articles": len(scores),
            "window_days": news_window_days,
            "raw_mean": round(mean_score, 4),
        },
    )


def compute_insider_sentiment_score(
    ticker: str,
    as_of_date: pd.Timestamp,
    lookback_months: int = 3,
    client=None,
    disk_cache=None,
) -> SignalResult:
    """
    Compute insider sentiment signal from Finnhub MSPR data.

    MSPR (Monthly Share Purchase Ratio) is already in [-1, +1]:
      +1 = insiders only buying
      -1 = insiders only selling

    Uses the average MSPR over the last `lookback_months` months,
    lagged by 1 month to avoid lookahead (insider filings have ~2 day delay).
    """
    sym = ticker.upper()
    # Lag by 1 month for point-in-time safety
    end = as_of_date - timedelta(days=30)
    start = end - timedelta(days=lookback_months * 31)

    from_date = start.strftime("%Y-%m-%d")
    to_date = end.strftime("%Y-%m-%d")

    # Try disk cache first — works even without a live client
    records = None
    if disk_cache is not None:
        records = disk_cache.load_insider(sym, from_date, to_date)

    # Fall back to live API only if cache missed and client is available
    if records is None:
        if client is None:
            return SignalResult(0.0, "no finnhub client and no cache hit", {"n_months": 0})
        records = client.get_insider_sentiment(sym, from_date, to_date)
        if disk_cache is not None:
            disk_cache.save_insider(sym, from_date, to_date, records)

    if not records:
        return SignalResult(0.0, "no insider data", {"n_months": 0})

    mspr_values = [r.get("mspr", 0.0) for r in records if r.get("mspr") is not None]

    if not mspr_values:
        return SignalResult(0.0, "no MSPR values", {"n_months": 0})

    mean_mspr = sum(mspr_values) / len(mspr_values)
    score = max(-1.0, min(1.0, mean_mspr))

    return SignalResult(
        score=round(score, 4),
        detail=f"MSPR avg={score:.3f} over {len(mspr_values)} months",
        metadata={
            "n_months": len(mspr_values),
            "raw_mspr_values": [round(v, 3) for v in mspr_values],
        },
    )
