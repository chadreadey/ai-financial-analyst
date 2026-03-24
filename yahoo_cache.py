"""
Per-run thread-safe cache for yfinance ``.info`` lookups.

Avoids duplicate HTTP calls when multiple enrichment sections request the same
symbol. Scoped to a single ``build_enrichment_context`` call.
"""

from __future__ import annotations

import threading
from typing import Any, Dict


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

        import yfinance as yf

        raw = yf.Ticker(sym).info or {}
        snapshot = dict(raw) if raw else {}

        with self._lock:
            self._info[sym] = snapshot
            return dict(snapshot)
