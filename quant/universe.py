"""
Stock universe definitions for backtesting.

Provides curated ticker lists by market-cap tier spanning all 11 GICS sectors.
Static lists for offline/fast use, dynamic provider (FMP/Wikipedia) for live S&P 500.
"""

from __future__ import annotations

import logging

# ── Liquid 10: core blue chips for fast testing ──────────────────────
LIQUID_10 = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "JPM",
    "JNJ",
    "XOM",
    "PG",
    "HD",
    "CAT",
]

# ── Liquid 20 ────────────────────────────────────────────────────────
LIQUID_20 = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "JPM",
    "JNJ",
    "UNH",
    "XOM",
    "PG",
    "HD",
    "CAT",
    "NEE",
    "AMT",
    "LIN",
    "BA",
    "KO",
    "GS",
    "PFE",
    "NVDA",
]

# ── Liquid 50: ~5 stocks per GICS sector ─────────────────────────────
LIQUID_50 = [
    # Technology
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "META",
    # Healthcare
    "JNJ",
    "UNH",
    "PFE",
    "ABBV",
    "MRK",
    # Financials
    "JPM",
    "BAC",
    "GS",
    "MS",
    "BRK-B",
    # Consumer Discretionary
    "AMZN",
    "TSLA",
    "HD",
    "NKE",
    "SBUX",
    # Consumer Staples
    "PG",
    "KO",
    "PEP",
    "WMT",
    "COST",
    # Industrials
    "CAT",
    "HON",
    "UPS",
    "BA",
    "GE",
    # Energy
    "XOM",
    "CVX",
    "COP",
    "SLB",
    "EOG",
    # Materials
    "LIN",
    "APD",
    "SHW",
    "FCX",
    "NEM",
    # Utilities
    "NEE",
    "DUK",
    "SO",
    "D",
    "AEP",
    # Real Estate
    "AMT",
    "PLD",
    "CCI",
    "EQIX",
    "SPG",
]

# ── Liquid 100: ~9 stocks per sector, all high-liquidity ─────────────
LIQUID_100 = [
    # Technology (12)
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "META",
    "AVGO",
    "CRM",
    "ORCL",
    "ADBE",
    "CSCO",
    "AMD",
    "INTC",
    # Healthcare (10)
    "JNJ",
    "UNH",
    "PFE",
    "ABBV",
    "MRK",
    "LLY",
    "TMO",
    "ABT",
    "BMY",
    "AMGN",
    # Financials (10)
    "JPM",
    "BAC",
    "GS",
    "MS",
    "BRK-B",
    "WFC",
    "C",
    "BLK",
    "SCHW",
    "AXP",
    # Consumer Discretionary (10)
    "AMZN",
    "TSLA",
    "HD",
    "NKE",
    "SBUX",
    "MCD",
    "LOW",
    "TJX",
    "BKNG",
    "CMG",
    # Consumer Staples (8)
    "PG",
    "KO",
    "PEP",
    "WMT",
    "COST",
    "PM",
    "CL",
    "MDLZ",
    # Industrials (10)
    "CAT",
    "HON",
    "UPS",
    "BA",
    "GE",
    "RTX",
    "DE",
    "LMT",
    "UNP",
    "MMM",
    # Energy (8)
    "XOM",
    "CVX",
    "COP",
    "SLB",
    "EOG",
    "MPC",
    "PSX",
    "VLO",
    # Materials (6)
    "LIN",
    "APD",
    "SHW",
    "FCX",
    "NEM",
    "ECL",
    # Utilities (6)
    "NEE",
    "DUK",
    "SO",
    "D",
    "AEP",
    "SRE",
    # Real Estate (6)
    "AMT",
    "PLD",
    "CCI",
    "EQIX",
    "SPG",
    "PSA",
    # Communication Services (6)
    "GOOG",
    "DIS",
    "CMCSA",
    "NFLX",
    "T",
    "VZ",
]
# Deduplicate (GOOGL/GOOG overlap)
LIQUID_100 = list(dict.fromkeys(LIQUID_100))

# ── Liquid 200: broad S&P 500 coverage ───────────────────────────────
LIQUID_200 = LIQUID_100 + [
    # Technology
    "NOW",
    "INTU",
    "PANW",
    "SNPS",
    "CDNS",
    "KLAC",
    "AMAT",
    "LRCX",
    "MRVL",
    "ADI",
    "FTNT",
    "WDAY",
    # Healthcare
    "ISRG",
    "GILD",
    "VRTX",
    "REGN",
    "ZTS",
    "SYK",
    "BDX",
    "MDT",
    "EW",
    "DXCM",
    "IQV",
    "HCA",
    # Financials
    "ICE",
    "CME",
    "AON",
    "MCO",
    "SPGI",
    "TFC",
    "USB",
    "PNC",
    "MET",
    "AIG",
    "PRU",
    "TRV",
    # Consumer Discretionary
    "ROST",
    "ORLY",
    "AZO",
    "LULU",
    "DHI",
    "LEN",
    "GM",
    "F",
    "YUM",
    "DPZ",
    "MAR",
    "HLT",
    # Consumer Staples
    "EL",
    "KHC",
    "GIS",
    "SJM",
    "HSY",
    "MO",
    "STZ",
    "KMB",
    # Industrials
    "WM",
    "ETN",
    "ITW",
    "EMR",
    "FDX",
    "CSX",
    "NSC",
    "PCAR",
    "GD",
    "NOC",
    "TT",
    "CTAS",
    # Energy
    "OXY",
    "DVN",
    "HAL",
    "FANG",
    "BKR",
    "HES",
    "KMI",
    "WMB",
    # Materials
    "DD",
    "DOW",
    "NUE",
    "BALL",
    "VMC",
    "MLM",
    "PPG",
    "ALB",
    # Utilities
    "XEL",
    "WEC",
    "ES",
    "AEE",
    "CMS",
    "AWK",
    "ED",
    "EXC",
    # Real Estate
    "O",
    "DLR",
    "WELL",
    "AVB",
    "EQR",
    "VTR",
    "ARE",
    "MAA",
    # Communication Services
    "CHTR",
    "TMUS",
    "TTWO",
    "EA",
    "LYV",
    "MTCH",
    "WBD",
    "PARA",
]
LIQUID_200 = list(dict.fromkeys(LIQUID_200))

# ── GICS Sector Mapping ──────────────────────────────────────────────
# Used for sector-diversified portfolio construction (max N per sector).

TICKER_SECTOR = {
    # Technology
    "AAPL": "Technology",
    "MSFT": "Technology",
    "NVDA": "Technology",
    "GOOGL": "Technology",
    "GOOG": "Technology",
    "META": "Technology",
    "AVGO": "Technology",
    "CRM": "Technology",
    "ORCL": "Technology",
    "ADBE": "Technology",
    "CSCO": "Technology",
    "AMD": "Technology",
    "INTC": "Technology",
    "NOW": "Technology",
    "INTU": "Technology",
    "PANW": "Technology",
    "SNPS": "Technology",
    "CDNS": "Technology",
    "KLAC": "Technology",
    "AMAT": "Technology",
    "LRCX": "Technology",
    "MRVL": "Technology",
    "ADI": "Technology",
    "FTNT": "Technology",
    "WDAY": "Technology",
    # Healthcare
    "JNJ": "Healthcare",
    "UNH": "Healthcare",
    "PFE": "Healthcare",
    "ABBV": "Healthcare",
    "MRK": "Healthcare",
    "LLY": "Healthcare",
    "TMO": "Healthcare",
    "ABT": "Healthcare",
    "BMY": "Healthcare",
    "AMGN": "Healthcare",
    "ISRG": "Healthcare",
    "GILD": "Healthcare",
    "VRTX": "Healthcare",
    "REGN": "Healthcare",
    "ZTS": "Healthcare",
    "SYK": "Healthcare",
    "BDX": "Healthcare",
    "MDT": "Healthcare",
    "EW": "Healthcare",
    "DXCM": "Healthcare",
    "IQV": "Healthcare",
    "HCA": "Healthcare",
    # Financials
    "JPM": "Financials",
    "BAC": "Financials",
    "GS": "Financials",
    "MS": "Financials",
    "BRK-B": "Financials",
    "WFC": "Financials",
    "C": "Financials",
    "BLK": "Financials",
    "SCHW": "Financials",
    "AXP": "Financials",
    "ICE": "Financials",
    "CME": "Financials",
    "AON": "Financials",
    "MCO": "Financials",
    "SPGI": "Financials",
    "TFC": "Financials",
    "USB": "Financials",
    "PNC": "Financials",
    "MET": "Financials",
    "AIG": "Financials",
    "PRU": "Financials",
    "TRV": "Financials",
    # Consumer Discretionary
    "AMZN": "Consumer Discretionary",
    "TSLA": "Consumer Discretionary",
    "HD": "Consumer Discretionary",
    "NKE": "Consumer Discretionary",
    "SBUX": "Consumer Discretionary",
    "MCD": "Consumer Discretionary",
    "LOW": "Consumer Discretionary",
    "TJX": "Consumer Discretionary",
    "BKNG": "Consumer Discretionary",
    "CMG": "Consumer Discretionary",
    "ROST": "Consumer Discretionary",
    "ORLY": "Consumer Discretionary",
    "AZO": "Consumer Discretionary",
    "LULU": "Consumer Discretionary",
    "DHI": "Consumer Discretionary",
    "LEN": "Consumer Discretionary",
    "GM": "Consumer Discretionary",
    "F": "Consumer Discretionary",
    "YUM": "Consumer Discretionary",
    "DPZ": "Consumer Discretionary",
    "MAR": "Consumer Discretionary",
    "HLT": "Consumer Discretionary",
    # Consumer Staples
    "PG": "Consumer Staples",
    "KO": "Consumer Staples",
    "PEP": "Consumer Staples",
    "WMT": "Consumer Staples",
    "COST": "Consumer Staples",
    "PM": "Consumer Staples",
    "CL": "Consumer Staples",
    "MDLZ": "Consumer Staples",
    "EL": "Consumer Staples",
    "KHC": "Consumer Staples",
    "GIS": "Consumer Staples",
    "SJM": "Consumer Staples",
    "HSY": "Consumer Staples",
    "MO": "Consumer Staples",
    "STZ": "Consumer Staples",
    "KMB": "Consumer Staples",
    # Industrials
    "CAT": "Industrials",
    "HON": "Industrials",
    "UPS": "Industrials",
    "BA": "Industrials",
    "GE": "Industrials",
    "RTX": "Industrials",
    "DE": "Industrials",
    "LMT": "Industrials",
    "UNP": "Industrials",
    "MMM": "Industrials",
    "WM": "Industrials",
    "ETN": "Industrials",
    "ITW": "Industrials",
    "EMR": "Industrials",
    "FDX": "Industrials",
    "CSX": "Industrials",
    "NSC": "Industrials",
    "PCAR": "Industrials",
    "GD": "Industrials",
    "NOC": "Industrials",
    "TT": "Industrials",
    "CTAS": "Industrials",
    # Energy
    "XOM": "Energy",
    "CVX": "Energy",
    "COP": "Energy",
    "SLB": "Energy",
    "EOG": "Energy",
    "MPC": "Energy",
    "PSX": "Energy",
    "VLO": "Energy",
    "OXY": "Energy",
    "DVN": "Energy",
    "HAL": "Energy",
    "FANG": "Energy",
    "BKR": "Energy",
    "HES": "Energy",
    "KMI": "Energy",
    "WMB": "Energy",
    # Materials
    "LIN": "Materials",
    "APD": "Materials",
    "SHW": "Materials",
    "FCX": "Materials",
    "NEM": "Materials",
    "ECL": "Materials",
    "DD": "Materials",
    "DOW": "Materials",
    "NUE": "Materials",
    "BALL": "Materials",
    "VMC": "Materials",
    "MLM": "Materials",
    "PPG": "Materials",
    "ALB": "Materials",
    # Utilities
    "NEE": "Utilities",
    "DUK": "Utilities",
    "SO": "Utilities",
    "D": "Utilities",
    "AEP": "Utilities",
    "SRE": "Utilities",
    "XEL": "Utilities",
    "WEC": "Utilities",
    "ES": "Utilities",
    "AEE": "Utilities",
    "CMS": "Utilities",
    "AWK": "Utilities",
    "ED": "Utilities",
    "EXC": "Utilities",
    # Real Estate
    "AMT": "Real Estate",
    "PLD": "Real Estate",
    "CCI": "Real Estate",
    "EQIX": "Real Estate",
    "SPG": "Real Estate",
    "PSA": "Real Estate",
    "O": "Real Estate",
    "DLR": "Real Estate",
    "WELL": "Real Estate",
    "AVB": "Real Estate",
    "EQR": "Real Estate",
    "VTR": "Real Estate",
    "ARE": "Real Estate",
    "MAA": "Real Estate",
    # Communication Services
    "DIS": "Communication Services",
    "CMCSA": "Communication Services",
    "NFLX": "Communication Services",
    "T": "Communication Services",
    "VZ": "Communication Services",
    "CHTR": "Communication Services",
    "TMUS": "Communication Services",
    "TTWO": "Communication Services",
    "EA": "Communication Services",
    "LYV": "Communication Services",
    "MTCH": "Communication Services",
    "WBD": "Communication Services",
    "PARA": "Communication Services",
}


def get_sector(ticker: str) -> str:
    """
    Return GICS sector for a ticker.

    Tries dynamic provider (FMP/Wikipedia-backed SQLite cache) first,
    falls back to hardcoded TICKER_SECTOR dict.
    """
    # Try dynamic provider first
    try:
        from quant.universe_provider import get_universe_provider

        sector = get_universe_provider().get_sector(ticker)
        if sector != "Unknown":
            return sector
    except Exception:
        pass
    return TICKER_SECTOR.get(ticker.upper(), "Unknown")


# SPY benchmark ticker
BENCHMARK = "SPY"


def get_universe(name: str = "liquid_50") -> list[str]:
    """
    Return a ticker list by universe name.

    Static universes: liquid_10, liquid_20, liquid_50, liquid_100, liquid_200
    Dynamic universes: sp500_top50, sp500_top100, sp500 (requires FMP_API_KEY or internet)
    """
    # Static universes (fast, no API needed)
    static = {
        "liquid_10": LIQUID_10,
        "liquid_20": LIQUID_20,
        "liquid_50": LIQUID_50,
        "liquid_100": LIQUID_100,
        "liquid_200": LIQUID_200,
    }
    result = static.get(name.lower())
    if result is not None:
        return list(result)

    # Dynamic universes (FMP/Wikipedia backed)
    dynamic_sizes = {
        "sp500_top50": 50,
        "sp500_top100": 100,
        "sp500_top200": 200,
        "sp500": 500,
    }
    n = dynamic_sizes.get(name.lower())
    if n is not None:
        try:
            from quant.universe_provider import get_universe_provider

            provider = get_universe_provider()
            tickers = provider.get_top_n_tickers(n)
            if tickers:
                return tickers
        except Exception as exc:
            logger.warning("Dynamic universe '%s' failed: %s — falling back to static", name, exc)
            # Fallback to largest static universe
            if n <= 50:
                return list(LIQUID_50)
            elif n <= 100:
                return list(LIQUID_100)
            else:
                return list(LIQUID_200)

    options = list(static.keys()) + list(dynamic_sizes.keys())
    raise ValueError(f"Unknown universe '{name}'. Options: {options}")


logger = logging.getLogger(__name__)
