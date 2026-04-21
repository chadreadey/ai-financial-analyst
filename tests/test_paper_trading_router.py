"""Tests for paper trading router new endpoints."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.main import app
    return TestClient(app)


@patch("backend.routers.paper_trading.get_alpaca_client")
def test_get_account(mock_get_client, client):
    mock_alpaca = MagicMock()
    mock_alpaca.get_account.return_value = {
        "cash": 100000.0,
        "equity": 100000.0,
        "buying_power": 200000.0,
        "portfolio_value": 100000.0,
        "currency": "USD",
    }
    mock_get_client.return_value = mock_alpaca

    resp = client.get("/api/paper-trading/account")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cash"] == 100000.0
    assert data["buying_power"] == 200000.0


@patch("backend.routers.paper_trading.get_alpaca_client")
def test_get_orders(mock_get_client, client):
    mock_alpaca = MagicMock()
    mock_alpaca.get_orders.return_value = [
        {
            "order_id": "ord-1",
            "symbol": "AAPL",
            "qty": 10,
            "side": "buy",
            "status": "filled",
            "filled_avg_price": 150.0,
            "filled_at": "2026-04-15T14:31:00Z",
            "submitted_at": "2026-04-15T14:30:00Z",
            "order_type": "market",
        }
    ]
    mock_get_client.return_value = mock_alpaca

    resp = client.get("/api/paper-trading/orders")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["orders"]) == 1
    assert data["orders"][0]["symbol"] == "AAPL"


@patch("backend.routers.paper_trading.run_rebalance")
def test_trigger_rebalance(mock_rebalance, client):
    mock_rebalance.return_value = {
        "status": "ok",
        "closed": ["AAPL"],
        "opened": ["MSFT"],
        "errors": [],
    }

    resp = client.post("/api/paper-trading/rebalance", json={"tickers": ["MSFT"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "MSFT" in data["opened"]


@patch("backend.routers.paper_trading.get_alpaca_client")
def test_get_account_no_keys(mock_get_client, client):
    mock_get_client.side_effect = EnvironmentError("No keys")
    resp = client.get("/api/paper-trading/account")
    assert resp.status_code == 200
    data = resp.json()
    assert data["error"] == "Alpaca not configured"
