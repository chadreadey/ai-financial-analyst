"""
Event timing signal.

Computes a per-stock signal based on proximity to catalysts:
  1. Earnings proximity — days until next earnings report
  2. Post-earnings drift — direction and magnitude of most recent surprise
  3. Macro event proximity — FOMC, CPI, NFP within N days

The signal captures two effects:
  - Pre-earnings: avoid new entries within 3 days (binary event risk)
  - Post-earnings: drift in direction of surprise for 60 days (PEAD)
  - Macro proximity: reduce conviction when high-impact macro events are imminent

Returns a score in [-1, +1] plus a risk flag for earnings proximity.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Module-level caches ──
_earnings_cache: dict[str, list[dict]] = {}
_economic_cache: dict[str, list[dict]] = {}


def _fetch_earnings_calendar(
    from_date: str,
    to_date: str,
    finnhub_client=None,
    disk_cache=None,
) -> list[dict]:
    """Fetch earnings calendar with caching."""
    cache_key = f"{from_date}_{to_date}"
    if cache_key in _earnings_cache:
        return _earnings_cache[cache_key]

    if disk_cache is not None:
        cached = disk_cache.get_institutional(f"earnings_cal", cache_key)
        if cached is not None:
            _earnings_cache[cache_key] = cached
            return cached

    data = []
    if finnhub_client is not None:
        data = finnhub_client.get_earnings_calendar(from_date, to_date)

    # Cache (including empty)
    _earnings_cache[cache_key] = data
    if disk_cache is not None and data:
        disk_cache.set_institutional(f"earnings_cal", cache_key, data)

    return data


def _fetch_economic_calendar(
    from_date: str,
    to_date: str,
    finnhub_client=None,
) -> list[dict]:
    """Fetch economic calendar with caching."""
    cache_key = f"{from_date}_{to_date}"
    if cache_key in _economic_cache:
        return _economic_cache[cache_key]

    data = []
    if finnhub_client is not None:
        data = finnhub_client.get_economic_calendar(from_date, to_date)

    _economic_cache[cache_key] = data
    return data


def compute_event_timing_scores(
    tickers: list[str],
    as_of_date: pd.Timestamp,
    finnhub_client=None,
    disk_cache=None,
    earnings_window_days: int = 60,
    macro_window_days: int = 5,
    earnings_block_days: int = 3,
) -> dict[str, tuple[float, dict]]:
    """
    Compute event timing signal for each ticker.

    Returns {ticker: (score, metadata)} where:
      score: [-1, +1] based on post-earnings drift + event proximity
      metadata: includes earnings_blocked flag, days_to_earnings, surprise info

    Score components:
    1. Post-earnings drift (+/- 0.7 weight): if last earnings surprise was positive,
       signal is bullish for up to 60 days. Decays linearly.
    2. Macro proximity penalty (-0.3 weight): if high-impact macro event within
       macro_window_days, reduce conviction (uncertainty spike).
    """
    as_of = as_of_date.date() if hasattr(as_of_date, "date") else as_of_date

    # Fetch earnings calendar: look back 90 days and forward 30 days
    lookback_start = (as_of - timedelta(days=90)).strftime("%Y-%m-%d")
    forward_end = (as_of + timedelta(days=30)).strftime("%Y-%m-%d")
    as_of_str = as_of.strftime("%Y-%m-%d") if hasattr(as_of, "strftime") else str(as_of)

    earnings_events = _fetch_earnings_calendar(
        lookback_start, forward_end, finnhub_client, disk_cache,
    )

    # Build per-ticker earnings info
    ticker_earnings = {}
    for event in earnings_events:
        sym = event.get("symbol", "")
        if sym not in tickers:
            continue
        event_date_str = event.get("date", "")
        if not event_date_str:
            continue
        try:
            event_date = date.fromisoformat(str(event_date_str)[:10])
        except (ValueError, TypeError):
            continue

        if sym not in ticker_earnings:
            ticker_earnings[sym] = []
        ticker_earnings[sym].append({
            "date": event_date,
            "eps_actual": event.get("epsActual"),
            "eps_estimate": event.get("epsEstimate"),
            "revenue_actual": event.get("revenueActual"),
            "revenue_estimate": event.get("revenueEstimate"),
        })

    # Fetch macro calendar: look forward from as_of
    macro_events = _fetch_economic_calendar(
        as_of_str,
        (as_of + timedelta(days=macro_window_days + 1)).strftime("%Y-%m-%d"),
        finnhub_client,
    )

    # Count high-impact macro events in window
    high_impact_count = sum(
        1 for e in macro_events
        if e.get("impact") == "high" and e.get("country", "") == "US"
    )
    macro_penalty = min(high_impact_count * 0.15, 0.5)  # cap at 0.5

    # Score each ticker
    results = {}
    for ticker in tickers:
        events = ticker_earnings.get(ticker, [])
        if not events:
            continue

        # Sort by date
        events.sort(key=lambda e: e["date"])

        # Find most recent past earnings
        past_earnings = [e for e in events if e["date"] <= as_of]
        future_earnings = [e for e in events if e["date"] > as_of]

        score = 0.0
        meta = {
            "n_earnings_events": len(events),
            "macro_high_impact": high_impact_count,
        }

        # ── Earnings proximity check ──
        if future_earnings:
            next_earnings = future_earnings[0]
            days_to_earnings = (next_earnings["date"] - as_of).days
            meta["days_to_earnings"] = days_to_earnings
            meta["earnings_blocked"] = days_to_earnings <= earnings_block_days
        else:
            meta["days_to_earnings"] = None
            meta["earnings_blocked"] = False

        # ── Post-earnings drift ──
        if past_earnings:
            last = past_earnings[-1]
            days_since = (as_of - last["date"]).days

            if days_since <= earnings_window_days and last["eps_actual"] is not None and last["eps_estimate"] is not None:
                try:
                    actual = float(last["eps_actual"])
                    estimate = float(last["eps_estimate"])

                    if abs(estimate) > 0.01:
                        surprise_pct = (actual - estimate) / abs(estimate)
                    elif actual > 0:
                        surprise_pct = 1.0
                    elif actual < 0:
                        surprise_pct = -1.0
                    else:
                        surprise_pct = 0.0

                    # Decay: full signal at day 0, zero at earnings_window_days
                    decay = max(0.0, 1.0 - days_since / earnings_window_days)

                    # Map surprise to [-1, +1]: >10% surprise = max, clip at ±1
                    drift_score = float(np.clip(surprise_pct / 0.10, -1.0, 1.0))
                    drift_score *= decay

                    score = drift_score * 0.7  # 70% weight on PEAD

                    meta["surprise_pct"] = round(surprise_pct * 100, 2)
                    meta["days_since_earnings"] = days_since
                    meta["decay"] = round(decay, 3)
                    meta["drift_score"] = round(drift_score, 4)
                except (TypeError, ValueError):
                    pass

        # ── Macro proximity penalty ──
        if macro_penalty > 0:
            score -= macro_penalty * 0.3  # 30% weight on macro uncertainty

        score = float(np.clip(score, -1.0, 1.0))
        results[ticker] = (round(score, 4), meta)

    return results
