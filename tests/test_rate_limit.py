"""RunLimiter and client_ip."""

from __future__ import annotations

from starlette.requests import Request

from backend.rate_limit import RunLimiter, client_ip


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _req(headers=None, client=("5.5.5.5", 1)):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "headers": raw, "client": client})


def test_ip_hourly_limit():
    clock = Clock()
    lim = RunLimiter(3, 30, 10, clock=clock)
    for _ in range(3):
        assert lim.acquire("1.1.1.1")[0] is True
        lim.release()
    ok, reason, retry = lim.acquire("1.1.1.1")
    assert (ok, reason) == (False, "ip_hourly")
    assert 0 < retry <= 3600
    clock.t += 3601
    assert lim.acquire("1.1.1.1")[0] is True


def test_other_ip_unaffected():
    lim = RunLimiter(1, 30, 10, clock=Clock())
    assert lim.acquire("1.1.1.1")[0]
    lim.release()
    assert lim.acquire("1.1.1.1")[0] is False
    assert lim.acquire("2.2.2.2")[0] is True


def test_daily_limit():
    lim = RunLimiter(100, 2, 10, clock=Clock())
    assert lim.acquire("1.1.1.1")[0]
    assert lim.acquire("2.2.2.2")[0]
    ok, reason, retry = lim.acquire("3.3.3.3")
    assert (ok, reason) == (False, "daily")
    assert 0 < retry <= 86400


def test_concurrent_limit():
    lim = RunLimiter(10, 30, 2, clock=Clock())
    assert lim.acquire("1.1.1.1")[0]
    assert lim.acquire("2.2.2.2")[0]
    ok, reason, retry = lim.acquire("3.3.3.3")
    assert (ok, reason) == (False, "concurrent")
    assert retry
    lim.release()
    assert lim.acquire("3.3.3.3")[0] is True


def test_refused_acquire_consumes_nothing():
    lim = RunLimiter(10, 30, 1, clock=Clock())
    assert lim.acquire("1.1.1.1")[0]
    assert lim.acquire("1.1.1.1")[0] is False
    lim.release()
    lim.release()  # floor at 0
    assert lim.acquire("1.1.1.1")[0]
    assert lim.acquire("1.1.1.1")[0] is False


def test_limiter_uses_first_forwarded_for_entry():
    assert client_ip(_req({"X-Forwarded-For": "9.9.9.9, 10.0.0.1"})) == "9.9.9.9"
    assert client_ip(_req()) == "5.5.5.5"
    assert client_ip(_req(client=None)) == "unknown"
