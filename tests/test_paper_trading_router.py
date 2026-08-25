"""Tests for paper trading router new endpoints."""

from __future__ import annotations

import sqlite3
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.main import app

    return TestClient(app)


@pytest.fixture
def temp_warehouse(tmp_path, monkeypatch):
    """Point the paper-trading router at an isolated warehouse DB and seed it."""
    db_path = tmp_path / "warehouse.db"
    from config import settings as config_settings

    monkeypatch.setattr(config_settings, "warehouse_db_path", str(db_path))
    return db_path


def _seed_position(db_path, ticker: str, entry_price: float, entry_date: str = "2026-04-20"):
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_positions (
            ticker TEXT PRIMARY KEY,
            entry_price REAL,
            entry_date TEXT,
            current_price REAL,
            verdict TEXT DEFAULT '',
            exit_conditions TEXT DEFAULT '',
            direction TEXT DEFAULT 'LONG',
            conviction_score REAL
        )
    """)
    conn.execute(
        "INSERT OR REPLACE INTO paper_positions (ticker, entry_price, entry_date, verdict, direction) "
        "VALUES (?, ?, ?, ?, ?)",
        (ticker, entry_price, entry_date, "BUY", "LONG"),
    )
    conn.commit()
    conn.close()


def _seed_analysis_history(
    db_path,
    ticker: str,
    verdict: str,
    conviction: str = "HIGH",
    composite_score: float = 0.5,
    price_target: float | None = None,
    days_ago: int = 1,
):
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analysis_history (
            analysis_id TEXT PRIMARY KEY,
            ticker TEXT,
            run_at REAL,
            company_name TEXT,
            verdict TEXT,
            conviction TEXT,
            time_horizon TEXT,
            composite_score REAL,
            health_scores TEXT,
            price_target REAL,
            stop_loss_value REAL,
            stop_loss_unit TEXT,
            entry_price_at_run REAL
        )
    """)
    run_at = time.time() - (days_ago * 86400)
    conn.execute(
        "INSERT OR REPLACE INTO analysis_history "
        "(analysis_id, ticker, run_at, verdict, conviction, composite_score, price_target) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            f"hist-{ticker}-{days_ago}",
            ticker,
            run_at,
            verdict,
            conviction,
            composite_score,
            price_target,
        ),
    )
    conn.commit()
    conn.close()


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


@patch("backend.routers.paper_trading._fetch_current_price")
def test_positions_with_verdicts_joins_latest_history(mock_price, client, temp_warehouse):
    _seed_position(temp_warehouse, "NVDA", entry_price=400.0)
    _seed_analysis_history(
        temp_warehouse,
        "NVDA",
        verdict="STRONG BUY",
        conviction="HIGH",
        composite_score=0.72,
        price_target=580.0,
        days_ago=2,
    )
    # Older record should be ignored
    _seed_analysis_history(
        temp_warehouse,
        "NVDA",
        verdict="HOLD",
        conviction="LOW",
        composite_score=0.05,
        price_target=420.0,
        days_ago=30,
    )
    mock_price.return_value = 512.30

    resp = client.get("/api/paper-trading/positions-with-verdicts")
    assert resp.status_code == 200
    data = resp.json()

    assert data["totals"]["total_positions"] == 1
    assert data["totals"]["stale_count"] == 0  # 2 days old, threshold is 7

    pos = data["positions"][0]
    assert pos["ticker"] == "NVDA"
    assert pos["entry_price"] == 400.0
    assert pos["current_price"] == 512.30
    assert pos["unrealized_pnl_pct"] == pytest.approx(
        28.075, abs=0.05
    )  # (512.30 - 400) / 400 * 100
    assert pos["entry_verdict"] == "BUY"
    assert pos["latest_verdict"] is not None
    assert pos["latest_verdict"]["verdict"] == "STRONG BUY"
    assert pos["latest_verdict"]["conviction"] == "HIGH"
    assert pos["latest_verdict"]["composite_score"] == 0.72
    assert pos["latest_verdict"]["price_target"] == 580.0
    assert pos["latest_verdict"]["days_stale"] in (1, 2, 3)  # tolerate clock jitter
    assert pos["latest_verdict"]["implied_upside_pct"] is not None
    # 580 vs 512.30 → ~13.2% upside
    assert 13.0 <= pos["latest_verdict"]["implied_upside_pct"] <= 13.5


@patch("backend.routers.paper_trading._fetch_current_price")
def test_positions_with_verdicts_marks_stale_and_missing(mock_price, client, temp_warehouse):
    _seed_position(temp_warehouse, "AAPL", entry_price=150.0)
    _seed_position(temp_warehouse, "MSFT", entry_price=300.0)
    # AAPL has a stale verdict (>7 days)
    _seed_analysis_history(
        temp_warehouse,
        "AAPL",
        verdict="BUY",
        conviction="MED",
        composite_score=0.3,
        price_target=165.0,
        days_ago=14,
    )
    # MSFT has no analysis history at all
    mock_price.return_value = 200.0

    resp = client.get("/api/paper-trading/positions-with-verdicts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["totals"]["total_positions"] == 2
    assert data["totals"]["stale_count"] == 2  # AAPL stale, MSFT no analysis

    by_ticker = {p["ticker"]: p for p in data["positions"]}
    assert by_ticker["AAPL"]["latest_verdict"]["days_stale"] >= 14
    assert by_ticker["MSFT"]["latest_verdict"] is None


@patch("backend.routers.paper_trading._fetch_current_price")
def test_positions_with_verdicts_empty(mock_price, client, temp_warehouse):
    mock_price.return_value = None
    resp = client.get("/api/paper-trading/positions-with-verdicts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["positions"] == []
    assert data["totals"]["total_positions"] == 0
    assert data["totals"]["stale_count"] == 0
