"""In-memory spend limiter for anonymous live analysis runs.

Single-process only (the app runs as one Railway instance); state resets on
restart, which is acceptable for a showcase.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable

from fastapi import Request

HOUR = 3600
DAY = 86400
CONCURRENT_RETRY_AFTER = 30


class RunLimiter:
    def __init__(
        self,
        per_ip_per_hour: int,
        per_day: int,
        max_concurrent: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._per_ip = per_ip_per_hour
        self._per_day = per_day
        self._max_concurrent = max_concurrent
        self._clock = clock
        self._lock = threading.Lock()
        self._by_ip: dict[str, deque[float]] = defaultdict(deque)
        self._daily: deque[float] = deque()
        self._active = 0

    @staticmethod
    def _prune(dq: deque[float], now: float, window: int) -> None:
        while dq and now - dq[0] >= window:
            dq.popleft()

    def acquire(self, ip: str) -> tuple[bool, str | None, int | None]:
        with self._lock:
            now = self._clock()
            ip_q = self._by_ip[ip]
            self._prune(ip_q, now, HOUR)
            self._prune(self._daily, now, DAY)
            if not ip_q:
                self._by_ip.pop(ip, None)
                ip_q = self._by_ip[ip]

            if len(ip_q) >= self._per_ip:
                return False, "ip_hourly", max(1, int(ip_q[0] + HOUR - now))
            if len(self._daily) >= self._per_day:
                return False, "daily", max(1, int(self._daily[0] + DAY - now))
            if self._active >= self._max_concurrent:
                return False, "concurrent", CONCURRENT_RETRY_AFTER

            ip_q.append(now)
            self._daily.append(now)
            self._active += 1
            return True, None, None

    def release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        first = fwd.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
