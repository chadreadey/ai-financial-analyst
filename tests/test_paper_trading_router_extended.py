"""Router-level tests for the extended `POST /api/paper-trading/rebalance`
body shape introduced by the two-stage pipeline change.

The new body accepts:
  - `tickers` (optional list[str]) — explicit override, bypasses screen
  - `use_quant_screen` (optional bool, default True)
  - `top_n_quant` (optional int, default 30)

Tests use FastAPI's `TestClient` and patch `run_rebalance` at its
import site inside the router module.
"""
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient


def _make_client():
    from backend.main import app
    return TestClient(app)


# ── T12 ──────────────────────────────────────────────────────────────────


@patch("backend.routers.paper_trading.run_rebalance")
def test_paper_trading_endpoint_accepts_new_body_shape(mock_run_rebalance):
    mock_run_rebalance.return_value = {
        "status": "ok", "closed": [], "opened": ["AAPL"], "errors": [],
    }
    client = _make_client()
    r = client.post(
        "/api/paper-trading/rebalance",
        json={"use_quant_screen": True, "top_n_quant": 20},
    )
    assert r.status_code == 200, r.text
    mock_run_rebalance.assert_called_once()
    kwargs = mock_run_rebalance.call_args.kwargs
    assert kwargs.get("use_quant_screen") is True
    assert kwargs.get("top_n_quant") == 20
    # `target_tickers` should be None when not provided (default path).
    assert kwargs.get("target_tickers") is None


# ── T13 ──────────────────────────────────────────────────────────────────


@patch("backend.routers.paper_trading.run_rebalance")
def test_paper_trading_endpoint_backward_compat(mock_run_rebalance):
    mock_run_rebalance.return_value = {
        "status": "ok", "closed": [], "opened": ["AAPL"], "errors": [],
    }
    client = _make_client()
    r = client.post(
        "/api/paper-trading/rebalance",
        json={"tickers": ["AAPL", "MSFT"]},
    )
    assert r.status_code == 200, r.text
    mock_run_rebalance.assert_called_once()
    kwargs = mock_run_rebalance.call_args.kwargs
    assert kwargs.get("target_tickers") == ["AAPL", "MSFT"]
