"""
Pinecone time-series vectors for quarterly macroeconomic snapshots.

Fetches FRED series via fred_client, resamples to quarterly (last observation
per quarter), builds a structured narrative snapshot for each quarter, and
upserts to the `macro_ts` namespace.

Vector ID format: macro_fts_{YYYYQQ}  e.g. macro_fts_2024Q1

FRED series used (via fred_client.QUARTERLY_SERIES):
  FEDFUNDS, DGS10, DGS2, T10Y2Y, CPIAUCSL, CPILFESL,
  A191RL1Q225SBEA, UNRATE, BAMLH0A0HYM2, BAMLC0A0CM, T5YIE, T10YIE
"""

import logging
import time
from typing import Dict, List, Optional

import pandas as pd

from fred_client import QUARTERLY_SERIES, get_fred_client

logger = logging.getLogger(__name__)

# Re-export for any code that referenced FRED_SERIES from this module
FRED_SERIES = QUARTERLY_SERIES


# ── regime labellers ─────────────────────────────────────────────────────────


def _rate_regime(fed_funds: Optional[float]) -> str:
    if fed_funds is None:
        return "unknown"
    if fed_funds >= 5.0:
        return "restrictive (≥5%)"
    if fed_funds >= 3.0:
        return "elevated (3–5%)"
    if fed_funds >= 1.0:
        return "moderate (1–3%)"
    return "accommodative (<1%)"


def _inflation_regime(cpi_yoy: Optional[float]) -> str:
    if cpi_yoy is None:
        return "unknown"
    if cpi_yoy >= 6.0:
        return "very high (≥6%)"
    if cpi_yoy >= 3.0:
        return "elevated (3–6%)"
    if cpi_yoy >= 2.0:
        return "moderate (2–3%)"
    return "low (<2%)"


def _growth_regime(real_gdp: Optional[float]) -> str:
    if real_gdp is None:
        return "unknown"
    if real_gdp >= 3.0:
        return "strong (≥3%)"
    if real_gdp >= 1.0:
        return "moderate (1–3%)"
    if real_gdp >= 0.0:
        return "weak (0–1%)"
    return "contraction (<0%)"


def _credit_regime(hy_spread: Optional[float]) -> str:
    if hy_spread is None:
        return "unknown"
    if hy_spread >= 800:
        return "crisis (≥800bps)"
    if hy_spread >= 500:
        return "stressed (500–800bps)"
    if hy_spread >= 350:
        return "elevated (350–500bps)"
    return "benign (<350bps)"


def _curve_regime(spread: Optional[float]) -> str:
    if spread is None:
        return "unknown"
    if spread >= 1.0:
        return "steeply positive (≥100bps)"
    if spread >= 0.0:
        return "flat/slightly positive"
    return f"inverted ({spread * 100:.0f}bps)"


def _fmt(v: Optional[float], decimals: int = 2, suffix: str = "") -> str:
    if v is None:
        return "n/a"
    return f"{v:.{decimals}f}{suffix}"


# ── build one snapshot ────────────────────────────────────────────────────────


def _build_macro_text(
    ql: str,
    period: str,
    row: Dict[str, Optional[float]],
    cpi_yoy: Optional[float],
    core_cpi_yoy: Optional[float],
) -> str:
    fed = row.get("fed_funds")
    dgs10 = row.get("dgs10")
    dgs2 = row.get("dgs2")
    spread = row.get("t10y2y")
    gdp = row.get("real_gdp_growth")
    unrate = row.get("unrate")
    hy = row.get("hy_spread")
    ig = row.get("ig_spread")
    be5 = row.get("breakeven_5y")
    be10 = row.get("breakeven_10y")

    lines = [
        f"Macroeconomic Snapshot — {ql} (quarter ending {period})",
        "",
        "=== Monetary Policy ===",
        f"Fed Funds Rate: {_fmt(fed)}%  Regime: {_rate_regime(fed)}",
        f"10-Year Treasury: {_fmt(dgs10)}%  2-Year Treasury: {_fmt(dgs2)}%",
        f"10-2 Year Spread: {_fmt(spread, 2, '%')}  Curve: {_curve_regime(spread)}",
        "",
        "=== Inflation ===",
        f"CPI YoY: {_fmt(cpi_yoy)}%  Regime: {_inflation_regime(cpi_yoy)}",
        f"Core CPI YoY: {_fmt(core_cpi_yoy)}%",
        f"5-Year Breakeven Inflation: {_fmt(be5)}%",
        f"10-Year Breakeven Inflation: {_fmt(be10)}%",
        "",
        "=== Economic Growth ===",
        f"Real GDP Growth (annualized): {_fmt(gdp)}%  Regime: {_growth_regime(gdp)}",
        f"Unemployment Rate: {_fmt(unrate)}%",
        "",
        "=== Credit / Risk ===",
        f"HY Credit Spread OAS: {_fmt(hy, 0, ' bps')}  Credit: {_credit_regime(hy)}",
        f"IG Credit Spread OAS: {_fmt(ig, 0, ' bps')}",
        "",
        "=== Macro Regime Summary ===",
        f"This quarter saw {_rate_regime(fed)} monetary policy, "
        f"{_inflation_regime(cpi_yoy)} inflation, "
        f"{_growth_regime(gdp)} economic growth, and "
        f"{_credit_regime(hy)} credit conditions.",
    ]
    return "\n".join(lines)


# ── fetch & resample ─────────────────────────────────────────────────────────


def fetch_fred_quarterly(
    fred_api_key: str,
    start_year: int = 2000,
) -> pd.DataFrame:
    """
    Fetch all FRED series and resample to quarterly (last obs per quarter).
    Returns a DataFrame indexed by quarter-end date with one column per series key.
    Uses the centralized CachedFREDClient for caching and rate limiting.
    """
    client = get_fred_client(fred_api_key)
    if client is None:
        logger.warning("No FRED client available — skipping quarterly fetch")
        return pd.DataFrame()
    return client.get_quarterly_dataframe(start_year=start_year)


# ── public API ────────────────────────────────────────────────────────────────


def build_macro_records(df: pd.DataFrame) -> List[Dict]:
    """
    Convert a quarterly-resampled FRED DataFrame into Pinecone-ready records.
    Computes CPI YoY from raw CPI levels.
    """
    records = []

    # Compute CPI YoY (12-month % change before resampling happens to monthly anyway)
    # After quarterly resampling CPI is the last monthly reading in that quarter.
    # YoY = 4 quarters back
    cpi_yoy_series = (
        df["cpi"].pct_change(4, fill_method=None) * 100
        if "cpi" in df.columns
        else pd.Series(dtype=float)
    )
    core_cpi_yoy_series = (
        df["core_cpi"].pct_change(4, fill_method=None) * 100
        if "core_cpi" in df.columns
        else pd.Series(dtype=float)
    )

    for date, row in df.iterrows():
        period = date.strftime("%Y-%m-%d")
        year = date.year
        q = (date.month - 1) // 3 + 1
        ql = f"{year}Q{q}"

        data: Dict[str, Optional[float]] = {}
        for key in QUARTERLY_SERIES:
            val = row.get(key)
            data[key] = float(val) if pd.notna(val) else None

        cpi_yoy_raw = cpi_yoy_series.get(date)
        core_cpi_yoy_raw = core_cpi_yoy_series.get(date)
        cpi_yoy = float(cpi_yoy_raw) if pd.notna(cpi_yoy_raw) else None
        core_cpi_yoy = float(core_cpi_yoy_raw) if pd.notna(core_cpi_yoy_raw) else None

        text = _build_macro_text(ql, period, data, cpi_yoy, core_cpi_yoy)

        record: Dict = {
            "_id": f"macro_fts_{ql}",
            "text": text[:4000],
            "period": period,
            "quarter_label": ql,
        }
        # Store key metrics as metadata for potential filtering
        for key, val in data.items():
            if val is not None:
                record[key] = round(val, 4)
        if cpi_yoy is not None:
            record["cpi_yoy"] = round(cpi_yoy, 4)
        if core_cpi_yoy is not None:
            record["core_cpi_yoy"] = round(core_cpi_yoy, 4)

        records.append(record)

    return records


def upsert_macro_vectors(
    fred_api_key: str,
    index,
    namespace: str = "macro_ts",
    start_year: int = 2000,
    batch_size: int = 50,
    dry_run: bool = False,
) -> int:
    """
    Fetch FRED data, build quarterly macro snapshots, and upsert to Pinecone.
    Returns number of records upserted (or previewed in dry-run).
    """
    logger.info("Fetching FRED data (start_year=%d)...", start_year)
    df = fetch_fred_quarterly(fred_api_key, start_year=start_year)

    if df.empty:
        logger.warning("No FRED data returned — skipping macro upsert")
        return 0

    records = build_macro_records(df)
    if not records:
        logger.warning("No macro records built — skipping")
        return 0

    logger.info("Built %d quarterly macro records", len(records))
    ns = namespace or "macro_ts"
    total = 0

    for i in range(0, len(records), batch_size):
        chunk = records[i : i + batch_size]
        if dry_run:
            logger.info("DRY RUN — would upsert macro records %d–%d", i, i + len(chunk) - 1)
        else:
            try:
                index.upsert_records(ns, chunk)
                logger.info("Upserted macro records %d–%d", i, i + len(chunk) - 1)
            except Exception as exc:
                logger.error("Macro upsert failed at offset %d: %s", i, exc)
                continue
        total += len(chunk)
        time.sleep(0.05)

    logger.info("Macro vectors done. %s %d records.", "Previewed" if dry_run else "Upserted", total)
    return total
