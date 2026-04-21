"""TestClient coverage for backend/routers/backtest_modal.py.

Offline-only. All external dependencies (backtest_reader, Modal dispatcher,
Supabase, stale sweepers) are monkeypatched. Auth is exercised by setting
settings.internal_api_key to a test value and asserting missing/wrong keys
return 403.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


GOOD_KEY = "test-key"
AUTH_HEADERS = {"X-API-Key": GOOD_KEY}

FAKE_RUN = {
    "run_id": "abc123",
    "config_hash": "hash1",
    "git_sha": "deadbeef",
    "status": "complete",
    "n_combinations": 10,
    "n_completed": 10,
    "n_failed": 0,
    "n_skipped": 0,
}
FAKE_COMBO = {
    "run_id": "abc123",
    "combo_idx": 0,
    "oos_sharpe": 1.2,
    "status": "complete",
}
FAKE_TRADE = {
    "run_id": "abc123",
    "combo_idx": 0,
    "ticker": "AAPL",
    "pnl_pct": 0.05,
}
FAKE_EVENT = {"id": 1, "run_id": "abc123", "event_type": "run_started"}


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    """Force the router auth dependency to a known test key.

    We patch the `settings` attribute on the module where the dependency
    function actually reads it (backtest_modal imports settings at module
    load time).
    """
    from backend.routers import backtest_modal as router_mod
    # Make both the local reference and the global settings object carry
    # the key — the dependency reads settings.internal_api_key.
    monkeypatch.setattr(router_mod.settings, "internal_api_key", GOOD_KEY, raising=False)


@pytest.fixture(autouse=True)
def _stub_sweepers(monkeypatch):
    """list_runs route opportunistically calls stale sweepers — no-op them."""
    from backend import cpcv_sqlite, supabase_backtest
    monkeypatch.setattr(cpcv_sqlite, "sweep_stale_runs", lambda *a, **k: 0, raising=False)
    monkeypatch.setattr(supabase_backtest, "sweep_stale_runs", lambda *a, **k: 0, raising=False)


@pytest.fixture(autouse=True)
def _mock_reader(monkeypatch):
    """Patch the reader module that the router imports."""
    from backend import backtest_reader as reader
    monkeypatch.setattr(reader, "source", lambda: "sqlite")
    monkeypatch.setattr(reader, "list_runs", lambda **kw: [FAKE_RUN])
    monkeypatch.setattr(
        reader,
        "get_run",
        lambda run_id: FAKE_RUN if run_id == "abc123" else None,
    )
    monkeypatch.setattr(
        reader, "find_runs_by_config_hash", lambda h, **kw: [FAKE_RUN]
    )
    monkeypatch.setattr(reader, "get_combinations", lambda run_id, **kw: [FAKE_COMBO])
    monkeypatch.setattr(reader, "get_trades", lambda run_id, **kw: [FAKE_TRADE])
    monkeypatch.setattr(
        reader,
        "get_events",
        lambda run_id, **kw: {"source": "sqlite", "events": [FAKE_EVENT]},
    )


@pytest.fixture()
def client():
    from backend.main import app
    return TestClient(app)


# ── Auth gating ───────────────────────────────────────────────────────────

def test_missing_api_key_returns_403(client):
    r = client.get("/api/backtest/modal/runs")
    # FastAPI treats a missing required Header as 422 unless the dependency
    # raises earlier. The plan's intent is "no header = reject"; 403 or 422
    # both satisfy that (we assert not 200).
    assert r.status_code in (403, 422)


def test_wrong_api_key_returns_403(client):
    r = client.get("/api/backtest/modal/runs", headers={"X-API-Key": "wrong"})
    assert r.status_code == 403


def test_correct_api_key_succeeds(client):
    r = client.get("/api/backtest/modal/runs", headers=AUTH_HEADERS)
    assert r.status_code == 200


# ── GET endpoints (happy path) ────────────────────────────────────────────

def test_source(client):
    r = client.get("/api/backtest/modal/source", headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json()["source"] == "sqlite"


def test_list_runs_default(client):
    r = client.get("/api/backtest/modal/runs", headers=AUTH_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["runs"][0]["run_id"] == "abc123"


def test_list_runs_status_filter(client):
    r = client.get(
        "/api/backtest/modal/runs?status=complete", headers=AUTH_HEADERS
    )
    assert r.status_code == 200


def test_list_runs_invalid_status(client):
    r = client.get("/api/backtest/modal/runs?status=bogus", headers=AUTH_HEADERS)
    assert r.status_code == 422


def test_get_run_found(client):
    r = client.get("/api/backtest/modal/runs/abc123", headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json()["run_id"] == "abc123"


def test_get_run_not_found(client):
    r = client.get(
        "/api/backtest/modal/runs/doesnotexist", headers=AUTH_HEADERS
    )
    assert r.status_code == 404


def test_runs_by_config_hash(client):
    r = client.get(
        "/api/backtest/modal/runs/by-config-hash/hash1", headers=AUTH_HEADERS
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["config_hash"] == "hash1"


def test_get_combinations(client):
    r = client.get(
        "/api/backtest/modal/runs/abc123/combinations", headers=AUTH_HEADERS
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_get_combinations_invalid_order_by(client):
    r = client.get(
        "/api/backtest/modal/runs/abc123/combinations?order_by=evil",
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 422


def test_get_combo_trades(client):
    r = client.get(
        "/api/backtest/modal/runs/abc123/combinations/0/trades",
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["combo_idx"] == 0
    assert body["count"] == 1


def test_get_run_trades(client):
    r = client.get(
        "/api/backtest/modal/runs/abc123/trades", headers=AUTH_HEADERS
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_get_events(client):
    """The reader now returns {"source": ..., "events": [...]} — the router
    must flatten source into the response envelope and still produce a
    count field."""
    r = client.get(
        "/api/backtest/modal/runs/abc123/events", headers=AUTH_HEADERS
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["source"] == "sqlite"
    assert body["events"][0]["id"] == 1


# ── POST /modal dispatch ──────────────────────────────────────────────────

def test_dispatch_modal_missing_tickers_and_universe(client):
    r = client.post("/api/backtest/modal", json={}, headers=AUTH_HEADERS)
    assert r.status_code == 400


def test_dispatch_modal_rejects_oversize_ticker_list(client):
    """Pydantic validator must reject > 50 tickers with 422."""
    payload = {"tickers": ["AAPL"] * 51}
    r = client.post("/api/backtest/modal", json=payload, headers=AUTH_HEADERS)
    assert r.status_code == 422


def test_dispatch_modal_rejects_path_traversal_ticker(client):
    """Ticker regex [A-Z]{1,5} must reject strings like '../etc/passwd'."""
    r = client.post(
        "/api/backtest/modal",
        json={"tickers": ["../etc/passwd"]},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 422


def test_dispatch_modal_rejects_numeric_ticker(client):
    r = client.post(
        "/api/backtest/modal",
        json={"tickers": ["123"]},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 422


def test_dispatch_modal_rejects_too_long_ticker(client):
    r = client.post(
        "/api/backtest/modal",
        json={"tickers": ["TOOLONG"]},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 422


def test_dispatch_modal_success(client, monkeypatch):
    """POST /modal with a known universe name returns the kickoff metadata."""
    import modal_app.dispatcher as disp

    def fake_kickoff(config, **kw):
        return {
            "run_id": "newrun1",
            "config_hash": "h2",
            "git_sha": "sha1",
            "status": "queued",
        }

    monkeypatch.setattr(disp, "kickoff_cpcv_background", fake_kickoff)

    # Patch get_universe on the real module (don't wholesale-replace it,
    # which would break `from quant.universe import BENCHMARK` in quant.backtest).
    from quant import universe as universe_mod
    monkeypatch.setattr(
        universe_mod, "get_universe", lambda name: ["AAPL", "MSFT"], raising=False
    )

    r = client.post(
        "/api/backtest/modal",
        json={"universe": "liquid_10"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["run_id"] == "newrun1"


# ── CORS regex pin ────────────────────────────────────────────────────────

def test_cors_evil_vercel_tenant_rejected(client):
    r = client.options(
        "/api/backtest/modal/runs",
        headers={
            "Origin": "https://evil-attacker.vercel.app",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-API-Key,Content-Type",
        },
    )
    assert "evil-attacker.vercel.app" not in r.headers.get(
        "access-control-allow-origin", ""
    )


def test_cors_own_vercel_project_allowed(client):
    r = client.options(
        "/api/backtest/modal/runs",
        headers={
            "Origin": "https://ai-financial-analyst.vercel.app",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-API-Key,Content-Type",
        },
    )
    # Starlette may echo or omit the header; the critical bit is that the
    # project's own origin must be allowed (not stripped).
    allowed = r.headers.get("access-control-allow-origin", "")
    assert allowed == "https://ai-financial-analyst.vercel.app"


def test_cors_vercel_preview_slug_allowed(client):
    """The pinned regex `ai-financial-analyst(-[a-z0-9]+)?\\.vercel\\.app`
    allows a single `-<alphanumeric>` suffix (Vercel hash-style previews).
    Multi-hyphen preview URLs like
    `ai-financial-analyst-git-modal-chadreadey.vercel.app` will NOT match;
    those must be added via CORS_ORIGINS. Verify the single-segment preview
    form works.
    """
    r = client.options(
        "/api/backtest/modal/runs",
        headers={
            "Origin": "https://ai-financial-analyst-abc123.vercel.app",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-API-Key,Content-Type",
        },
    )
    allowed = r.headers.get("access-control-allow-origin", "")
    assert allowed == "https://ai-financial-analyst-abc123.vercel.app"
