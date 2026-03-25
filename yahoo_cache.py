"""
Per-run thread-safe cache for yfinance ``.info`` lookups.

Avoids duplicate HTTP calls when multiple enrichment sections request the same
symbol. Scoped to a single ``build_enrichment_context`` call.

Yahoo Finance aggressively rate-limits / invalidates crumbs when requests come
from datacenter IPs (e.g. Streamlit Cloud / GCP). Two mitigations are applied:

1. A module-level lock serializes all yfinance HTTP calls so concurrent
   ThreadPoolExecutor tasks don't trigger Yahoo's anti-abuse detection.
2. On a 401 Invalid Crumb response, a single retry is made with a fresh
   requests.Session() to force re-authentication.
"""

from __future__ import annotations

import threading
from typing import Any, Dict

# Serializes all outbound yfinance HTTP calls across threads to avoid
# triggering Yahoo's anti-abuse detection from datacenter IPs.
_YF_GLOBAL_LOCK = threading.Lock()


class YahooLookupCache:
    """Thread-safe cache of symbol -> info dict (shallow copy on read)."""

    __slots__ = ("_lock", "_info")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._info: Dict[str, Dict[str, Any]] = {}

    def get_info(self, symbol: str) -> Dict[str, Any]:
        """Return a copy of Yahoo ``info`` for *symbol* (uppercased)."""
        sym = symbol.upper()
        with self._lock:
            cached = self._info.get(sym)
            if cached is not None:
                return dict(cached)

        import requests
        import yfinance as yf

        snapshot: Dict[str, Any] = {}
        with _YF_GLOBAL_LOCK:
            for attempt in range(2):
                try:
                    session = requests.Session() if attempt > 0 else None
                    ticker = yf.Ticker(sym, session=session) if session else yf.Ticker(sym)
                    raw = ticker.info or {}
                    snapshot = dict(raw) if raw else {}
                    break
                except Exception as exc:
                    if attempt == 0 and "401" in str(exc):
                        continue  # retry once with a fresh session
                    break

        with self._lock:
            self._info[sym] = snapshot
            return dict(snapshot)
