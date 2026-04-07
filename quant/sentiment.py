"""
News sentiment signal from Finnhub company news.

Uses FinBERT (ProsusAI/finbert) for financial sentiment scoring.
Falls back to VADER if transformers is not installed.
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

# ── Sentiment scorer: FinBERT (preferred) → VADER (fallback) ─────────

_scorer_name = "none"
_finbert_pipeline = None
_vader = None

try:
    from transformers import pipeline as hf_pipeline
    _finbert_pipeline = hf_pipeline(
        "sentiment-analysis",
        model="ProsusAI/finbert",
        device=-1,  # CPU only — deterministic, no GPU required
        top_k=None,  # return all class probabilities
    )
    _scorer_name = "finbert"
    logger.info("FinBERT sentiment model loaded (ProsusAI/finbert)")
except Exception as exc:
    logger.debug("FinBERT not available (%s) — trying VADER fallback", exc)
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _vader = SentimentIntensityAnalyzer()
        _scorer_name = "vader"
        logger.info("Using VADER sentiment (FinBERT not available)")
    except ImportError:
        logger.debug("Neither FinBERT nor VADER available — sentiment will return 0.0")


def _score_headline(text: str) -> float:
    """
    Score a single headline/text. Returns [-1, +1].

    FinBERT returns {positive, negative, neutral} probabilities.
    Score = P(positive) - P(negative), yielding [-1, +1].
    """
    if _finbert_pipeline is not None:
        try:
            results = _finbert_pipeline(text[:512], truncation=True)
            # results is a list of lists: [[{label, score}, ...]]
            probs = {r["label"]: r["score"] for r in results[0]}
            return probs.get("positive", 0.0) - probs.get("negative", 0.0)
        except Exception:
            return 0.0
    if _vader is not None:
        return _vader.polarity_scores(text)["compound"]
    return 0.0


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
    if _scorer_name == "none":
        return SignalResult(0.0, "no sentiment scorer available", {"n_articles": 0})

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

    detail = f"{len(scores)} articles, mean {_scorer_name}={score:.3f}"
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
