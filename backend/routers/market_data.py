from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()

PERIOD_DAYS = {
    "1mo": 30,
    "3mo": 90,
    "1yr": 365,
    "3yr": 1095,
    "5yr": 1825,
}


def _get_tiingo_history(ticker: str, days: int) -> list[dict]:
    tiingo_key = os.getenv("TIINGO_API_KEY", "").strip()
    if not tiingo_key:
        return []
    try:
        from tiingo_client import TiingoClient
        client = TiingoClient(tiingo_key)
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return client.get_eod_history(ticker, start) or []
    except Exception as exc:
        logger.warning("Tiingo history failed for %s: %s", ticker, exc)
        return []


@router.get("/sparkline/{ticker}")
async def get_sparkline(ticker: str):
    data = _get_tiingo_history(ticker.upper(), 90)
    if not data:
        return {"ticker": ticker.upper(), "closes": [], "dates": []}

    data = sorted(data, key=lambda d: d.get("date", ""))
    closes = [float(d.get("adjClose") or d.get("close", 0)) for d in data[-60:]]
    dates = [str(d.get("date", ""))[:10] for d in data[-60:]]
    return {"ticker": ticker.upper(), "closes": closes, "dates": dates}


@router.get("/price-history/{ticker}")
async def get_price_history(ticker: str, period: str = "1yr"):
    days = PERIOD_DAYS.get(period, 365)
    data = _get_tiingo_history(ticker.upper(), days)
    if not data:
        return {"ticker": ticker.upper(), "bars": []}

    data = sorted(data, key=lambda d: d.get("date", ""))
    bars = []
    for d in data:
        date_str = str(d.get("date", ""))[:10]
        bars.append({
            "time": date_str,
            "open": float(d.get("open", 0)),
            "high": float(d.get("high", 0)),
            "low": float(d.get("low", 0)),
            "close": float(d.get("adjClose") or d.get("close", 0)),
            "volume": int(d.get("volume", 0)),
        })
    return {"ticker": ticker.upper(), "bars": bars}
