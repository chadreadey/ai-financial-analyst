"""
Sector momentum signal.

Computes trailing N-month return for each GICS sector ETF, then maps
the sector return to each stock in that sector. Stocks in hot sectors
get a positive signal; stocks in lagging sectors get a negative signal.

This is a time-series momentum signal applied at the sector level —
it captures the "rising tide lifts all boats" effect and the tendency
for sector trends to persist over 3-12 month horizons.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Sector ETF → GICS sector name mapping
ETF_TO_SECTOR = {
    "XLK": "Technology",
    "XLV": "Healthcare",
    "XLF": "Financials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLE": "Energy",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}


def compute_sector_momentum_scores(
    sector_etf_data: dict[str, pd.DataFrame],
    signals: dict,
    as_of_date: pd.Timestamp,
    sector_fn,
    lookback_days: int = 63,
) -> dict[str, float]:
    """
    Compute sector momentum score for each ticker based on its sector ETF return.

    Args:
        sector_etf_data: {etf_ticker: DataFrame with 'close' column}
        signals: {ticker: SignalVector} — used to get the ticker list
        as_of_date: Date to compute momentum as of
        sector_fn: Callable(ticker) -> sector_name
        lookback_days: Trading days for momentum computation (63 ≈ 3 months)

    Returns:
        {ticker: momentum_score in [-1, +1]}
    """
    # Compute trailing return for each sector ETF
    sector_returns = {}
    for etf, df in sector_etf_data.items():
        available = df[df.index <= as_of_date]
        if len(available) < lookback_days:
            continue

        current_price = float(available.iloc[-1]["close"])
        past_price = float(available.iloc[-lookback_days]["close"])

        if past_price > 0:
            ret = (current_price - past_price) / past_price
            sector_name = ETF_TO_SECTOR.get(etf)
            if sector_name:
                sector_returns[sector_name] = ret

    if not sector_returns:
        return {}

    # Cross-sectional z-score of sector returns
    returns_array = np.array(list(sector_returns.values()))
    mean_ret = np.mean(returns_array)
    std_ret = np.std(returns_array)

    if std_ret < 1e-8:
        # All sectors have same return — no momentum signal
        return {t: 0.0 for t in signals}

    sector_z = {
        sector: float(np.clip((ret - mean_ret) / std_ret / 3.0, -1.0, 1.0))
        for sector, ret in sector_returns.items()
    }

    # Map sector momentum to each stock
    scores = {}
    for ticker in signals:
        sector = sector_fn(ticker)
        scores[ticker] = sector_z.get(sector, 0.0)

    return scores
