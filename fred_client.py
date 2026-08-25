"""
FRED REST client with thread-safe cache and disk persistence.

Provides macro indicators: Treasury yields, credit spreads, inflation
breakevens, employment, GDP, and Fed policy rates.

Free tier: 120 req/min, full history back to series inception.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


# ── Series Catalog ─────────────────────────────────────────────────────

# Core macro series used across the platform
MACRO_SERIES: Dict[str, Tuple[str, str]] = {
    # (series_id, unit)
    "DGS10": ("10-Year Treasury Yield", "%"),
    "DGS2": ("2-Year Treasury Yield", "%"),
    "DGS5": ("5-Year Treasury Yield", "%"),
    "DGS30": ("30-Year Treasury Yield", "%"),
    "DGS3MO": ("3-Month Treasury Yield", "%"),
    "DGS6MO": ("6-Month Treasury Yield", "%"),
    "DGS1": ("1-Year Treasury Yield", "%"),
    "DGS7": ("7-Year Treasury Yield", "%"),
    "DGS20": ("20-Year Treasury Yield", "%"),
    "FEDFUNDS": ("Fed Funds Rate", "%"),
    "CPIAUCSL": ("CPI All Items", "index"),
    "CPILFESL": ("Core CPI", "index"),
    "UNRATE": ("Unemployment Rate", "%"),
    "BAMLH0A0HYM2": ("HY Credit Spread OAS", "bps"),
    "BAMLC0A0CM": ("IG Credit Spread OAS", "bps"),
    "T10Y2Y": ("10-2 Year Spread", "%"),
    "A191RL1Q225SBEA": ("Real GDP Growth", "%"),
    "UMCSENT": ("Consumer Sentiment (UMich)", "index"),
    "VIXCLS": ("CBOE VIX", "index"),
    "T5YIE": ("5-Year Breakeven Inflation", "%"),
    "T10YIE": ("10-Year Breakeven Inflation", "%"),
    "PCOPPUSDM": ("Copper Price USD/lb", "USD/lb"),
}

# Treasury maturities for yield curve interpolation (discount_rate.py)
TREASURY_SERIES: Dict[float, str] = {
    0.25: "DGS3MO",
    0.5: "DGS6MO",
    1.0: "DGS1",
    2.0: "DGS2",
    5.0: "DGS5",
    7.0: "DGS7",
    10.0: "DGS10",
    20.0: "DGS20",
    30.0: "DGS30",
}

# Quarterly macro series for warehouse/macro_vectors.py
QUARTERLY_SERIES: Dict[str, str] = {
    "fed_funds": "FEDFUNDS",
    "dgs10": "DGS10",
    "dgs2": "DGS2",
    "t10y2y": "T10Y2Y",
    "cpi": "CPIAUCSL",
    "core_cpi": "CPILFESL",
    "real_gdp_growth": "A191RL1Q225SBEA",
    "unrate": "UNRATE",
    "hy_spread": "BAMLH0A0HYM2",
    "ig_spread": "BAMLC0A0CM",
    "breakeven_5y": "T5YIE",
    "breakeven_10y": "T10YIE",
}


# ── REST Client ────────────────────────────────────────────────────────


class FREDClient:
    """FRED API client via fredapi. Handles rate-limit backoff."""

    def __init__(self, api_key: str) -> None:
        from fredapi import Fred

        self._fred = Fred(api_key=api_key)
        self._call_count = 0

    def get_series(
        self,
        series_id: str,
        observation_start: Optional[str] = None,
        observation_end: Optional[str] = None,
    ) -> pd.Series:
        """Fetch a single FRED series. Returns empty Series on failure."""
        self._call_count += 1
        if self._call_count % 100 == 0:
            logger.info("FRED call count: %d", self._call_count)
        if self._call_count > 100:
            time.sleep(0.5)  # stay under 120 req/min

        kwargs: Dict[str, Any] = {}
        if observation_start:
            kwargs["observation_start"] = observation_start
        if observation_end:
            kwargs["observation_end"] = observation_end

        try:
            data = self._fred.get_series(series_id, **kwargs)
            data = data.dropna()
            return data
        except Exception as exc:
            logger.debug("FRED %s failed: %s", series_id, exc, exc_info=True)
            return pd.Series(dtype=float)

    def get_series_batch(
        self,
        series_ids: List[str],
        observation_start: Optional[str] = None,
        observation_end: Optional[str] = None,
    ) -> Dict[str, pd.Series]:
        """Fetch multiple series sequentially. Returns dict of series_id -> data."""
        results: Dict[str, pd.Series] = {}
        for sid in series_ids:
            results[sid] = self.get_series(sid, observation_start, observation_end)
        return results


# ── In-Memory Cache ────────────────────────────────────────────────────


class FREDCache:
    """Per-run thread-safe cache. Same two-lock pattern as FinnhubCache."""

    def __init__(self, client: FREDClient) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._series_cache: Dict[str, pd.Series] = {}

    @property
    def client(self) -> FREDClient:
        return self._client

    def get_series(
        self,
        series_id: str,
        observation_start: Optional[str] = None,
        observation_end: Optional[str] = None,
    ) -> pd.Series:
        key = f"{series_id}:{observation_start or ''}:{observation_end or ''}"
        with self._lock:
            cached = self._series_cache.get(key)
            if cached is not None:
                return cached.copy()

        result = self._client.get_series(series_id, observation_start, observation_end)

        with self._lock:
            self._series_cache[key] = result
            return result.copy()

    def get_series_batch(
        self,
        series_ids: List[str],
        observation_start: Optional[str] = None,
        observation_end: Optional[str] = None,
    ) -> Dict[str, pd.Series]:
        results: Dict[str, pd.Series] = {}
        for sid in series_ids:
            results[sid] = self.get_series(sid, observation_start, observation_end)
        return results

    def get_latest(self, series_id: str) -> Optional[float]:
        """Get the most recent observation for a series."""
        data = self.get_series(series_id)
        if data.empty:
            return None
        return float(data.iloc[-1])


# ── Disk Cache ─────────────────────────────────────────────────────────


class FREDDiskCache:
    """
    Persistent JSON cache for FRED series, keyed by (series_id, start, end).

    Historical FRED data is immutable — old observations never change.
    Only series ending within 3 days of today are considered potentially
    stale and re-fetched.
    """

    def __init__(self, cache_dir: str = "") -> None:
        if not cache_dir:
            cache_dir = os.getenv(
                "FRED_CACHE_DIR",
                os.path.join(os.path.dirname(__file__), ".fred_cache"),
            )
        self._dir = cache_dir
        os.makedirs(self._dir, exist_ok=True)

    def _path(self, series_id: str, start: str, end: str) -> str:
        safe = f"fred_{series_id}_{start}_{end}.json"
        return os.path.join(self._dir, safe)

    def _is_stale(self, end_date: str) -> bool:
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d")
            return (datetime.now() - end).days <= 3
        except ValueError:
            return True

    def load(self, series_id: str, start: str, end: str) -> Optional[pd.Series]:
        path = self._path(series_id, start, end)
        if not os.path.exists(path):
            return None
        if self._is_stale(end):
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            s = pd.Series(data["values"], index=pd.to_datetime(data["dates"]))
            return s
        except Exception:
            return None

    def save(self, series_id: str, start: str, end: str, data: pd.Series) -> None:
        if data.empty:
            return
        path = self._path(series_id, start, end)
        payload = {
            "series_id": series_id,
            "dates": [d.isoformat() for d in data.index],
            "values": [float(v) for v in data.values],
            "saved_at": datetime.now().isoformat(),
        }
        with open(path, "w") as f:
            json.dump(payload, f)


# ── Cached Client (Disk + Memory) ─────────────────────────────────────


class CachedFREDClient:
    """
    Full-featured FRED client with disk + in-memory caching.
    Use this as the primary entry point for all FRED data access.
    """

    def __init__(self, api_key: str, cache_dir: str = "") -> None:
        self._client = FREDClient(api_key)
        self._mem = FREDCache(self._client)
        self._disk = FREDDiskCache(cache_dir)

    @property
    def client(self) -> FREDClient:
        return self._client

    def get_series(
        self,
        series_id: str,
        observation_start: Optional[str] = None,
        observation_end: Optional[str] = None,
    ) -> pd.Series:
        start = observation_start or ""
        end = observation_end or ""

        # Check disk cache first (for historical ranges)
        if start and end:
            disk_hit = self._disk.load(series_id, start, end)
            if disk_hit is not None:
                logger.debug("FRED disk cache hit: %s [%s, %s]", series_id, start, end)
                return disk_hit

        # Then in-memory, then API
        result = self._mem.get_series(series_id, observation_start, observation_end)

        # Persist to disk if we have a bounded range
        if start and end and not result.empty:
            self._disk.save(series_id, start, end, result)

        return result

    def get_latest(self, series_id: str) -> Optional[float]:
        """Get the most recent observation. Not disk-cached (always fresh)."""
        return self._mem.get_latest(series_id)

    def get_yield_curve(self) -> Optional[Dict[float, float]]:
        """Return {maturity_years: yield_pct} for Treasury curve."""
        curve: Dict[float, float] = {}
        for mat, sid in TREASURY_SERIES.items():
            val = self.get_latest(sid)
            if val is not None:
                curve[mat] = val
        return curve if len(curve) >= 3 else None

    def get_macro_snapshot(
        self, lookback_days: int = 365
    ) -> Dict[str, Tuple[Optional[float], Optional[float]]]:
        """
        Return {series_id: (current_value, 1Y_change)} for all macro series.
        Used by market_enrichment.py for the macro section.
        """
        start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        snapshot: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
        for sid in MACRO_SERIES:
            data = self.get_series(sid, observation_start=start)
            if data.empty:
                snapshot[sid] = (None, None)
                continue
            current = float(data.iloc[-1])
            prior = float(data.iloc[0])
            snapshot[sid] = (current, current - prior)
        return snapshot

    def get_quarterly_dataframe(self, start_year: int = 2000) -> pd.DataFrame:
        """
        Fetch all quarterly series and resample to quarter-end.
        Used by warehouse/macro_vectors.py.
        """
        start = f"{start_year}-01-01"
        frames: Dict[str, pd.Series] = {}
        for key, series_id in QUARTERLY_SERIES.items():
            data = self.get_series(series_id, observation_start=start)
            frames[key] = data
            if not data.empty:
                logger.info("FRED %s: %d observations", series_id, len(data))
        df = pd.DataFrame(frames)
        if df.empty:
            return df
        df.index = pd.to_datetime(df.index)
        df = df.resample("QE").last()
        return df


# ── Module-level singleton ─────────────────────────────────────────────

_instance: Optional[CachedFREDClient] = None
_instance_lock = threading.Lock()


def get_fred_client(api_key: Optional[str] = None) -> Optional[CachedFREDClient]:
    """
    Get or create the module-level FRED client singleton.
    Returns None if no API key is available.
    """
    global _instance
    if _instance is not None:
        return _instance

    if api_key is None:
        # Try env var directly first (avoids pydantic_settings import issues in backtest)
        api_key = os.getenv("FRED_API_KEY", "").strip()
        if not api_key:
            try:
                from config import settings

                api_key = settings.fred_api_key.strip()
            except ImportError:
                pass

    if not api_key:
        return None

    with _instance_lock:
        if _instance is None:
            _instance = CachedFREDClient(api_key)
    return _instance
