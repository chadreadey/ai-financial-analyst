"""
Event timing signal from WRDS IBES actuals + consensus.

Computes post-earnings announcement drift (PEAD) using:
  - IBES actuals: announcement date (anndats) + actual EPS
  - IBES consensus: last estimate before announcement (meanest)
  - Surprise = (actual - estimate) / |estimate|

The PEAD effect: stocks drift in the direction of the earnings surprise
for 60+ trading days after the announcement. This is one of the most
robust anomalies in finance (Bernard & Thomas 1989).

Also flags earnings proximity for risk management:
  - earnings_blocked = True if next earnings is within 3 days
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Module-level caches
_actuals_cache: dict[str, list[dict]] = {}
_consensus_cache: dict[str, list[dict]] = {}


def _load_ibes_actuals(ticker: str, wrds_store) -> list[dict]:
    """Load IBES actuals for a ticker (cached)."""
    if ticker in _actuals_cache:
        return _actuals_cache[ticker]

    try:
        conn = wrds_store._conn()
        # Map our ticker to IBES ticker via the link table
        link = conn.execute(
            "SELECT ibes_ticker FROM ticker_link WHERE ticker = ? AND ibes_ticker IS NOT NULL LIMIT 1",
            (ticker.upper(),)
        ).fetchone()
        if link is None:
            _actuals_cache[ticker] = []
            conn.close()
            return []

        ibes_ticker = link["ibes_ticker"]
        rows = conn.execute("""
            SELECT ticker, pends, anndats, value as eps_actual
            FROM ibes_actuals
            WHERE ticker = ?
            ORDER BY pends DESC
        """, (ibes_ticker,)).fetchall()
        conn.close()

        result = [dict(r) for r in rows]
        _actuals_cache[ticker] = result
        return result
    except Exception as exc:
        logger.debug("Failed to load IBES actuals for %s: %s", ticker, exc)
        _actuals_cache[ticker] = []
        return []


def _load_ibes_consensus_at_date(ticker: str, as_of_date: str, wrds_store) -> float | None:
    """Load the most recent IBES consensus estimate before a given date."""
    cache_key = f"{ticker}_{as_of_date}"
    if cache_key in _consensus_cache:
        cached = _consensus_cache[cache_key]
        return cached[0] if cached else None

    try:
        conn = wrds_store._conn()
        link = conn.execute(
            "SELECT ibes_ticker FROM ticker_link WHERE ticker = ? AND ibes_ticker IS NOT NULL LIMIT 1",
            (ticker.upper(),)
        ).fetchone()
        if link is None:
            _consensus_cache[cache_key] = []
            conn.close()
            return None

        ibes_ticker = link["ibes_ticker"]
        row = conn.execute("""
            SELECT meanest FROM ibes_consensus
            WHERE ticker = ? AND statpers <= ? AND fpi = '1'
            ORDER BY statpers DESC LIMIT 1
        """, (ibes_ticker, as_of_date)).fetchone()
        conn.close()

        if row and row["meanest"] is not None:
            _consensus_cache[cache_key] = [float(row["meanest"])]
            return float(row["meanest"])

        _consensus_cache[cache_key] = []
        return None
    except Exception as exc:
        logger.debug("Failed to load IBES consensus for %s: %s", ticker, exc)
        _consensus_cache[cache_key] = []
        return None


def compute_event_timing_scores(
    tickers: list[str],
    as_of_date: pd.Timestamp,
    wrds_store=None,
    drift_window_days: int = 60,
    block_days: int = 3,
    **kwargs,
) -> dict[str, tuple[float, dict]]:
    """
    Compute PEAD-based event timing signal from WRDS IBES data.

    Returns {ticker: (score, metadata)}.
    """
    if wrds_store is None:
        return {}

    as_of = as_of_date.date() if hasattr(as_of_date, "date") else as_of_date
    as_of_str = str(as_of)

    results = {}
    for ticker in tickers:
        actuals = _load_ibes_actuals(ticker, wrds_store)
        if not actuals:
            continue

        # Find most recent past earnings and next future earnings
        past = []
        future = []
        for a in actuals:
            try:
                ann_date = date.fromisoformat(str(a["anndats"])[:10])
            except (ValueError, TypeError):
                continue
            if ann_date <= as_of:
                past.append((ann_date, a))
            else:
                future.append((ann_date, a))

        meta = {}
        score = 0.0

        # Earnings proximity (blocking)
        if future:
            future.sort(key=lambda x: x[0])
            days_to = (future[0][0] - as_of).days
            meta["days_to_earnings"] = days_to
            meta["earnings_blocked"] = days_to <= block_days
        else:
            meta["days_to_earnings"] = None
            meta["earnings_blocked"] = False

        # Post-earnings drift
        if past:
            past.sort(key=lambda x: x[0], reverse=True)
            last_date, last_actual = past[0]
            days_since = (as_of - last_date).days

            if days_since <= drift_window_days and last_actual.get("eps_actual") is not None:
                actual = float(last_actual["eps_actual"])

                # Get the consensus estimate that was active just before announcement
                estimate = _load_ibes_consensus_at_date(
                    ticker, str(last_date - timedelta(days=1)), wrds_store
                )

                if estimate is not None and abs(estimate) > 0.01:
                    surprise_pct = (actual - estimate) / abs(estimate)

                    # Decay linearly over drift_window_days
                    decay = max(0.0, 1.0 - days_since / drift_window_days)

                    # Map: >10% surprise = max score, clip at ±1
                    drift_score = float(np.clip(surprise_pct / 0.10, -1.0, 1.0))
                    score = drift_score * decay

                    meta["eps_actual"] = round(actual, 3)
                    meta["eps_estimate"] = round(estimate, 3)
                    meta["surprise_pct"] = round(surprise_pct * 100, 2)
                    meta["days_since_earnings"] = days_since
                    meta["decay"] = round(decay, 3)

        score = float(np.clip(score, -1.0, 1.0))
        if score != 0.0 or "surprise_pct" in meta:
            results[ticker] = (round(score, 4), meta)

    return results
