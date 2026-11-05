"""
Per-run thread-safe cache for yfinance ``.info`` lookups, plus the bounded
call helper every yfinance network call goes through.

Avoids duplicate HTTP calls when multiple enrichment sections request the same
symbol. Scoped to a single ``build_enrichment_context`` call.

Yahoo Finance aggressively rate-limits / invalidates crumbs when requests come
from datacenter IPs (e.g. Streamlit Cloud / GCP). Two mitigations are applied:

1. A module-level lock serializes all yfinance ``.info`` calls so concurrent
   ThreadPoolExecutor tasks don't trigger Yahoo's anti-abuse detection.
2. On a 401 Invalid Crumb response, a single retry is made with a fresh
   requests.Session() to force re-authentication.

yfinance calls carry no timeout of their own, and a dead connection (socket
stuck in CLOSE_WAIT) once stalled a run for 11 hours while holding the lock.
:func:`call_with_timeout` runs each call in a daemon worker thread and stops
waiting after ``YAHOO_TIMEOUT_SECONDS``. The caller, not the worker, holds the
lock, so a timeout always releases it; the stuck worker is abandoned.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Dict, Optional, TypeVar

from utils import env_flag

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Serializes all outbound yfinance ``.info`` calls across threads to avoid
# triggering Yahoo's anti-abuse detection from datacenter IPs.
_YF_GLOBAL_LOCK = threading.Lock()

DEFAULT_TIMEOUT_SECONDS = 20.0


class YahooTimeout(TimeoutError):
    """A yfinance call did not finish within the allowed time."""


def yahoo_timeout_seconds() -> float:
    """Per-call ceiling for yfinance network calls (env ``YAHOO_TIMEOUT_SECONDS``)."""
    raw = os.getenv("YAHOO_TIMEOUT_SECONDS", "")
    try:
        value = float(raw) if raw.strip() else DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        value = DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


def call_with_timeout(fn: Callable[[], T], timeout: Optional[float] = None, label: str = "") -> T:
    """Run *fn* in a daemon thread; return its result or raise :class:`YahooTimeout`.

    Exceptions raised by *fn* are re-raised in the caller. On timeout the worker
    is left running (it is a daemon, so it never blocks interpreter exit).
    """
    limit = yahoo_timeout_seconds() if timeout is None else timeout
    box: Dict[str, Any] = {}
    done = threading.Event()

    def _run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
            box["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=_run, name=f"yfinance-{label or 'call'}", daemon=True)
    worker.start()
    if not done.wait(limit):
        logger.warning("yfinance call %s timed out after %.1fs", label or "<call>", limit)
        raise YahooTimeout(f"yfinance call {label or '<call>'} timed out after {limit:.1f}s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def fetch_info(symbol: str) -> Dict[str, Any]:
    """Uncached, bounded Yahoo ``info`` lookup. Returns ``{}`` on any failure."""
    import requests
    import yfinance as yf

    sym = symbol.upper()
    limit = yahoo_timeout_seconds()
    # Bound the wait for the lock too, in case another caller is mid-timeout.
    if not _YF_GLOBAL_LOCK.acquire(timeout=limit):
        logger.warning("Yahoo lock busy for %.1fs; skipping info for %s", limit, sym)
        return {}
    try:
        for attempt in range(2):
            try:
                session = requests.Session() if attempt > 0 else None

                def _info(session=session) -> Dict[str, Any]:
                    ticker = yf.Ticker(sym, session=session) if session else yf.Ticker(sym)
                    return ticker.info or {}

                raw = call_with_timeout(_info, limit, label=f"{sym}.info")
                return dict(raw) if raw else {}
            except YahooTimeout:
                return {}
            except Exception as exc:
                if attempt == 0 and "401" in str(exc):
                    continue  # retry once with a fresh session
                return {}
        return {}
    finally:
        _YF_GLOBAL_LOCK.release()


class YahooLookupCache:
    """Thread-safe cache of symbol -> info dict (shallow copy on read)."""

    __slots__ = ("_lock", "_info")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._info: Dict[str, Dict[str, Any]] = {}

    def get_info(self, symbol: str) -> Dict[str, Any]:
        """Return a copy of Yahoo ``info`` for *symbol* (uppercased)."""
        if not env_flag("ENABLE_YAHOO_FALLBACK", default=True):
            return {}
        sym = symbol.upper()
        with self._lock:
            cached = self._info.get(sym)
            if cached is not None:
                return dict(cached)

        snapshot = fetch_info(sym)

        with self._lock:
            self._info[sym] = snapshot
            return dict(snapshot)
