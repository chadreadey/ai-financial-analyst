"""Public (non-admin) behaviour of POST /api/analysis/run."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.rate_limit import RunLimiter
from backend.schemas import RunAnalysisRequest
from config import settings

BODY = {"ticker": "NVDA"}


class InlineThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


@pytest.fixture
def env(monkeypatch):
    from backend.routers import analysis

    monkeypatch.setattr(settings, "internal_api_key", "test-key", raising=False)
    calls = []

    def fake_job(job, request, auto_paper_trade=None):
        calls.append((request, auto_paper_trade))

    monkeypatch.setattr(analysis, "run_analysis_job", fake_job)
    monkeypatch.setattr(analysis.threading, "Thread", InlineThread)
    monkeypatch.setattr(analysis, "limiter", RunLimiter(3, 30, 2))
    from backend.main import app

    return TestClient(app), calls, analysis


def test_public_run_clamps_params(env):
    client, calls, _ = env
    r = client.post(
        "/api/analysis/run",
        json={
            "ticker": " nvda ",
            "provider": "openai",
            "model": "gpt-x",
            "api_key": "sk-x",  # pragma: allowlist secret
            "max_agent_output_tokens": 99999,
        },
    )
    assert r.status_code == 200
    req, apt = calls[0]
    assert req.ticker == "NVDA"
    assert req.provider == settings.llm_provider
    assert req.model is None
    assert req.api_key is None
    assert (
        req.max_agent_output_tokens
        == RunAnalysisRequest.model_fields["max_agent_output_tokens"].default
    )
    assert apt is False


@pytest.mark.parametrize("ticker", ["DROP TABLE", "TOOLONG", ""])
def test_public_run_rejects_bad_ticker(env, ticker):
    client, calls, _ = env
    r = client.post("/api/analysis/run", json={"ticker": ticker})
    assert r.status_code == 422
    assert calls == []


def test_public_run_accepts_class_share_ticker(env):
    client, calls, _ = env
    assert client.post("/api/analysis/run", json={"ticker": "brk.b"}).status_code == 200
    assert calls[0][0].ticker == "BRK.B"


def test_public_run_429_after_limit(env):
    client, calls, _ = env
    h = {"X-Forwarded-For": "7.7.7.7"}
    for _ in range(3):
        assert client.post("/api/analysis/run", json=BODY, headers=h).status_code == 200
    r = client.post("/api/analysis/run", json=BODY, headers=h)
    assert r.status_code == 429
    assert "limit" in r.json()["detail"]
    assert "Retry-After" in r.headers
    assert len(calls) == 3


def test_slot_released_when_job_raises(env, monkeypatch):
    client, _, analysis = env
    monkeypatch.setattr(analysis, "limiter", RunLimiter(10, 30, 1))

    def boom(job, request, auto_paper_trade=None):
        raise RuntimeError("x")

    monkeypatch.setattr(analysis, "run_analysis_job", boom)
    tc = TestClient(client.app, raise_server_exceptions=False)
    for i in range(3):
        # inline thread re-raises inside the request; slot must still free
        tc.post("/api/analysis/run", json=BODY, headers={"X-Forwarded-For": f"1.1.1.{i}"})
    assert analysis.limiter.acquire("9.9.9.9")[0] is True


def test_admin_run_bypasses_limits_and_keeps_params(env):
    client, calls, _ = env
    h = {"X-API-Key": "test-key"}
    for _ in range(5):
        r = client.post(
            "/api/analysis/run",
            json={"ticker": "nvda", "provider": "openai", "max_agent_output_tokens": 99999},
            headers=h,
        )
        assert r.status_code == 200
    req, apt = calls[-1]
    assert req.provider == "openai"
    assert req.max_agent_output_tokens == 99999
    assert apt is None
