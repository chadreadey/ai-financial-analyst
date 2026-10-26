"""Admin-key gating of lab endpoints and the is_admin helper."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from config import settings

KEY = "test-key"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "internal_api_key", KEY, raising=False)
    from backend.main import app

    return TestClient(app)


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/paper-trading/rebalance"),
        ("POST", "/api/portfolio/holdings"),
        ("DELETE", "/api/watchlist/AAPL"),
        ("POST", "/api/backtest/run"),
        ("POST", "/api/industry/technology/analyze"),
        ("GET", "/api/analysis/history"),
        ("GET", "/api/diagnostics/assumptions"),
    ],
)
def test_lab_endpoints_forbidden_without_key(client, method, path):
    assert client.request(method, path).status_code == 403


def test_lab_endpoint_forbidden_with_wrong_key(client):
    r = client.get("/api/analysis/history", headers={"X-API-Key": "wrong"})
    assert r.status_code == 403
    assert r.json() == {"detail": "Forbidden."}


def test_public_endpoints_open(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/config/defaults").status_code == 200


def _request(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
    )


def test_is_admin(monkeypatch):
    from backend.auth import is_admin

    monkeypatch.setattr(settings, "internal_api_key", KEY, raising=False)
    assert is_admin(_request({"X-API-Key": KEY})) is True
    assert is_admin(_request({"X-API-Key": "wrong"})) is False
    assert is_admin(_request({})) is False
    monkeypatch.setattr(settings, "internal_api_key", "", raising=False)
    assert is_admin(_request({"X-API-Key": ""})) is False
