"""
Kalshi-based signals for the quant model.

Two signals:

1. compute_macro_modifier(client) -> float in [-1, +1]
   Reads Fed/CPI/JOBS Kalshi markets and returns a uniform
   macro-regime modifier applied cross-sectionally. Dovish
   (high cut probability) -> positive; hawkish -> negative.

2. compute_event_divergence(client, ticker, our_prob_beat, threshold) -> float in [-1, +1]
   Computes divergence between our model's earnings-beat probability
   and Kalshi's market-implied probability. Returns 0.0 if divergence
   is below threshold (no-bet zone).
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np

from quant.kalshi_client import KalshiClient

logger = logging.getLogger(__name__)

_MACRO_SERIES_CONFIG = {
    "FED": {"weight": 0.50, "bullish_if_yes": True},
    "CPI": {"weight": 0.25, "bullish_if_yes": False},
    "JOBS": {"weight": 0.25, "bullish_if_yes": False},
}

_EARN_SERIES = "EARN"


def compute_macro_modifier(
    client: KalshiClient,
    _date_override: Optional[str] = None,
) -> float:
    weighted_sum = 0.0
    total_weight = 0.0

    for series, cfg in _MACRO_SERIES_CONFIG.items():
        try:
            markets = client.get_markets(series_ticker=series, _date_override=_date_override)
        except Exception as exc:
            logger.warning("Kalshi macro fetch failed for %s: %s", series, exc)
            continue

        if not markets:
            continue

        market = max(markets, key=lambda m: m.get("volume", 0))
        yes_prob = market.get("yes_prob")
        if yes_prob is None:
            yes_prob = 0.5

        bullish_prob = yes_prob if cfg["bullish_if_yes"] else (1.0 - yes_prob)
        centred = bullish_prob - 0.5

        weighted_sum += centred * cfg["weight"]
        total_weight += cfg["weight"]

    if total_weight == 0:
        return 0.0

    raw = weighted_sum / total_weight
    return float(np.clip(raw * 2.0, -1.0, 1.0))


def compute_macro_momentum(
    client: KalshiClient,
    lookback_periods: int = 4,
    _date_override: Optional[str] = None,
) -> float:
    """Rate-of-change (velocity) of the macro modifier.

    Returns current_modifier - prior_modifier, clipped to [-1, +1].
    The prior date is lookback_periods * 30 days before today (or _date_override).
    Returns 0.0 gracefully on any error.
    """
    try:
        from datetime import datetime, timedelta

        if _date_override:
            base_date = datetime.strptime(_date_override, "%Y-%m-%d")
        else:
            base_date = datetime.utcnow()

        prior_date = base_date - timedelta(days=lookback_periods * 30)
        prior_date_str = prior_date.strftime("%Y-%m-%d")

        current_modifier = compute_macro_modifier(client, _date_override=_date_override)
        prior_modifier = compute_macro_modifier(client, _date_override=prior_date_str)

        delta = current_modifier - prior_modifier
        return float(np.clip(delta, -1.0, 1.0))
    except Exception as exc:
        logger.warning("compute_macro_momentum failed: %s", exc)
        return 0.0


def compute_event_divergence(
    client: KalshiClient,
    ticker: str,
    our_prob_beat: float,
    threshold: float = 0.20,
    _date_override: Optional[str] = None,
) -> float:
    try:
        markets = _find_earn_market(client, ticker, _date_override)
        if not markets:
            return 0.0

        kalshi_prob = markets[0].get("yes_prob")
        if kalshi_prob is None:
            return 0.0

        divergence = our_prob_beat - kalshi_prob

        if abs(divergence) < threshold:
            return 0.0

        raw = math.tanh(divergence * 3.0)
        return float(np.clip(raw, -1.0, 1.0))
    except Exception as exc:
        logger.warning("Event divergence computation failed for %s: %s", ticker, exc)
        return 0.0


def _find_earn_market(
    client: KalshiClient,
    ticker: str,
    _date_override: Optional[str] = None,
) -> list[dict]:
    try:
        all_earn = client.get_markets(series_ticker=_EARN_SERIES, _date_override=_date_override)
    except Exception as exc:
        logger.warning("Kalshi EARN fetch failed: %s", exc)
        return []

    ticker_upper = ticker.upper()
    matching = [
        m
        for m in all_earn
        if ticker_upper in m.get("ticker", "").upper()
        or ticker_upper in m.get("event_ticker", "").upper()
    ]
    matching.sort(key=lambda m: m.get("volume", 0), reverse=True)
    return matching
