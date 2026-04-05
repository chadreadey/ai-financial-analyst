"""
Stock universe definitions for backtesting.

Provides curated ticker lists by market-cap tier. The full S&P 500 is too
many API calls for Tiingo free tier, so we default to a liquid 50-stock
subset spanning all 11 GICS sectors.
"""

from __future__ import annotations

# ── Liquid 50: representative cross-sector subset ──────────────────────
# ~5 stocks per GICS sector, biased toward high liquidity / long history.

LIQUID_50 = [
    # Technology
    "AAPL", "MSFT", "NVDA", "GOOGL", "META",
    # Healthcare
    "JNJ", "UNH", "PFE", "ABBV", "MRK",
    # Financials
    "JPM", "BAC", "GS", "MS", "BRK-B",
    # Consumer Discretionary
    "AMZN", "TSLA", "HD", "NKE", "SBUX",
    # Consumer Staples
    "PG", "KO", "PEP", "WMT", "COST",
    # Industrials
    "CAT", "HON", "UPS", "BA", "GE",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG",
    # Materials
    "LIN", "APD", "SHW", "FCX", "NEM",
    # Utilities
    "NEE", "DUK", "SO", "D", "AEP",
    # Real Estate
    "AMT", "PLD", "CCI", "EQIX", "SPG",
]

# Smaller subsets for quick testing
LIQUID_20 = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "JPM", "JNJ", "UNH", "XOM", "PG",
    "HD", "CAT", "NEE", "AMT", "LIN",
    "BA", "KO", "GS", "PFE", "NVDA",
]

LIQUID_10 = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "JPM",
    "JNJ", "XOM", "PG", "HD", "CAT",
]

# SPY benchmark ticker
BENCHMARK = "SPY"


def get_universe(name: str = "liquid_50") -> list[str]:
    """Return a ticker list by universe name."""
    universes = {
        "liquid_50": LIQUID_50,
        "liquid_20": LIQUID_20,
        "liquid_10": LIQUID_10,
    }
    result = universes.get(name.lower())
    if result is None:
        raise ValueError(f"Unknown universe '{name}'. Options: {list(universes.keys())}")
    return list(result)
