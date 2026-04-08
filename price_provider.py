"""
Price data provider abstraction.

Defines a PriceProvider Protocol and implementations for Tiingo and Alpaca.
Both clients return data in a common schema so the backtest engine and
API routes can switch providers via PRICE_PROVIDER env var.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol

import requests

logger = logging.getLogger(__name__)


# ── Schema Validation ────────────────────────────────────────────────

_REQUIRED_ALPACA_BAR_FIELDS = ("t", "o", "h", "l", "c", "v")


def _validate_alpaca_bar(bar: dict, symbol: str) -> dict:
    """Log warning if required Alpaca bar fields are missing. Returns bar unchanged."""
    missing = [k for k in _REQUIRED_ALPACA_BAR_FIELDS if k not in bar]
    if missing:
        logger.warning("schema: alpaca_bar response for %s missing fields: %s", symbol, ", ".join(missing))
    return bar


# ── Provider Protocol ─────────────────────────────────────────────────

class PriceProvider(Protocol):
    """Common interface for price data providers."""

    def get_quote(self, symbol: str) -> dict:
        """Latest price data. Returns dict with 'close', 'adjClose', 'volume', 'date'."""
        ...

    def get_meta(self, symbol: str) -> dict:
        """Company metadata. Returns dict with 'ticker', 'name', etc."""
        ...

    def get_eod_history(self, symbol: str, start_date: str) -> list[dict]:
        """
        Historical daily OHLCV from start_date to present.
        Returns list of dicts with keys:
            date, open, high, low, close, adjOpen, adjHigh, adjLow, adjClose, volume, adjVolume
        """
        ...


# ── Alpaca Client ─────────────────────────────────────────────────────

class AlpacaClient:
    """
    Alpaca Markets REST client for historical price data.

    Uses the v2 market data API directly (no SDK dependency).
    Free tier: 200 req/min, IEX feed, data from 2016+.
    """

    BASE_URL = "https://data.alpaca.markets/v2"
    TRADING_URL = "https://api.alpaca.markets/v2"

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        feed: str = "iex",
    ) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        })
        self._feed = feed

    def get_quote(self, symbol: str) -> dict:
        """Get latest snapshot (daily bar) for a symbol."""
        try:
            resp = self._session.get(
                f"{self.BASE_URL}/stocks/{symbol}/snapshot",
                params={"feed": self._feed},
                timeout=(5, 15),
            )
            resp.raise_for_status()
            snap = resp.json()
            bar = snap.get("dailyBar", {})
            return {
                "close": bar.get("c", 0),
                "adjClose": bar.get("c", 0),
                "volume": bar.get("v", 0),
                "date": bar.get("t", ""),
            }
        except Exception as exc:
            logger.debug("alpaca snapshot %s failed: %s", symbol, exc, exc_info=True)
            return {}

    def get_meta(self, symbol: str) -> dict:
        """Get asset metadata. Note: Alpaca has no sector/description data."""
        try:
            resp = self._session.get(
                f"{self.TRADING_URL}/assets/{symbol}",
                timeout=(5, 15),
            )
            resp.raise_for_status()
            asset = resp.json()
            return {
                "ticker": asset.get("symbol", symbol),
                "name": asset.get("name", symbol),
                "exchange": asset.get("exchange", ""),
                "description": None,
                "sector": None,
            }
        except Exception as exc:
            logger.debug("alpaca asset %s failed: %s", symbol, exc, exc_info=True)
            return {"ticker": symbol, "name": symbol}

    def get_eod_history(self, symbol: str, start_date: str) -> list[dict]:
        """
        Fetch daily OHLCV bars with split+dividend adjustment.

        Alpaca returns adjusted prices when adjustment=all, so
        close == adjClose. We populate both fields for compatibility
        with the Tiingo schema.
        """
        all_bars: list[dict] = []
        page_token: Optional[str] = None

        while True:
            params: dict[str, Any] = {
                "timeframe": "1Day",
                "start": start_date,
                "adjustment": "all",
                "feed": self._feed,
                "limit": 10000,
                "sort": "asc",
            }
            if page_token:
                params["page_token"] = page_token

            try:
                resp = self._session.get(
                    f"{self.BASE_URL}/stocks/{symbol}/bars",
                    params=params,
                    timeout=(10, 30),
                )
                if resp.status_code == 429:
                    import time
                    time.sleep(1)
                    continue
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.debug("alpaca bars %s failed: %s", symbol, exc, exc_info=True)
                break

            bars = data.get("bars") or []
            for bar in (_validate_alpaca_bar(b, symbol) for b in bars):
                # Normalize timestamp: Alpaca returns "2024-01-18T05:00:00Z"
                ts = bar.get("t", "")
                all_bars.append({
                    "date": ts,
                    "open": bar.get("o", 0),
                    "high": bar.get("h", 0),
                    "low": bar.get("l", 0),
                    "close": bar.get("c", 0),
                    # With adjustment=all, these are already adjusted
                    "adjOpen": bar.get("o", 0),
                    "adjHigh": bar.get("h", 0),
                    "adjLow": bar.get("l", 0),
                    "adjClose": bar.get("c", 0),
                    "volume": bar.get("v", 0),
                    "adjVolume": bar.get("v", 0),
                })

            page_token = data.get("next_page_token")
            if not page_token:
                break

        return all_bars


# ── Alpaca Cache ──────────────────────────────────────────────────────

class AlpacaCache:
    """Per-run thread-safe cache wrapping AlpacaClient. Same pattern as TiingoCache."""

    def __init__(self, client: AlpacaClient) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._quote_cache: Dict[str, dict] = {}
        self._meta_cache: Dict[str, dict] = {}
        self._history_cache: Dict[str, list] = {}

    def get_quote(self, symbol: str) -> dict:
        sym = symbol.upper()
        with self._lock:
            cached = self._quote_cache.get(sym)
            if cached is not None:
                return dict(cached)

        result = self._client.get_quote(sym)

        with self._lock:
            self._quote_cache[sym] = result
            return dict(result)

    def get_meta(self, symbol: str) -> dict:
        sym = symbol.upper()
        with self._lock:
            cached = self._meta_cache.get(sym)
            if cached is not None:
                return dict(cached)

        result = self._client.get_meta(sym)

        with self._lock:
            self._meta_cache[sym] = result
            return dict(result)

    def get_eod_history(self, symbol: str, start_date: str) -> list[dict]:
        sym = symbol.upper()
        key = f"{sym}:{start_date}"
        with self._lock:
            cached = self._history_cache.get(key)
            if cached is not None:
                return list(cached)

        result = self._client.get_eod_history(sym, start_date)

        with self._lock:
            self._history_cache[key] = result
            return list(result)


# ── Provider Factory ──────────────────────────────────────────────────

def get_price_provider(provider: Optional[str] = None) -> PriceProvider:
    """
    Build a cached price provider from env vars.

    Args:
        provider: 'alpaca' or 'tiingo'. Reads PRICE_PROVIDER env var if None.

    Env vars:
        PRICE_PROVIDER:     'alpaca' or 'tiingo' (default: tiingo)
        ALPACA_API_KEY:     Alpaca key ID
        ALPACA_SECRET_KEY:  Alpaca secret key
        ALPACA_DATA_FEED:   'iex' (free) or 'sip' (paid). Default: iex
        TIINGO_API_KEY:     Tiingo API token
    """
    if provider is None:
        provider = os.getenv("PRICE_PROVIDER", "tiingo").lower().strip()

    if provider == "alpaca":
        api_key = os.getenv("ALPACA_API_KEY", "").strip()
        secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
        if not api_key or not secret_key:
            raise EnvironmentError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set when PRICE_PROVIDER=alpaca"
            )
        feed = os.getenv("ALPACA_DATA_FEED", "iex").lower().strip()
        client = AlpacaClient(api_key, secret_key, feed=feed)
        return AlpacaCache(client)

    else:  # tiingo (default)
        api_key = os.getenv("TIINGO_API_KEY", "").strip()
        if not api_key:
            raise EnvironmentError(
                "TIINGO_API_KEY must be set when PRICE_PROVIDER=tiingo"
            )
        from tiingo_client import TiingoClient, TiingoCache
        client = TiingoClient(api_key)
        return TiingoCache(client)
