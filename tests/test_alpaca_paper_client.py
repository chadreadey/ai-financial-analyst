"""Tests for Alpaca paper trading client."""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_settings(tmp_path):
    """Settings with a temp DB path and fake Alpaca keys."""
    from config import Settings
    return Settings(
        alpaca_api_key="test-key-id",
        alpaca_secret_key="test-secret-key",
        alpaca_paper_base_url="https://paper-api.alpaca.markets",
        warehouse_db_path=str(tmp_path / "test.db"),
        paper_default_qty=10,
    )


@patch("backend.alpaca_paper_client.TradingClient")
def test_get_account(mock_tc_class, mock_settings):
    mock_tc = MagicMock()
    account = MagicMock()
    account.cash = "100000.00"
    account.equity = "100000.00"
    account.buying_power = "200000.00"
    account.portfolio_value = "100000.00"
    account.currency = "USD"
    mock_tc.get_account.return_value = account
    mock_tc_class.return_value = mock_tc

    from backend.alpaca_paper_client import AlpacaPaperClient
    client = AlpacaPaperClient(mock_settings)
    result = client.get_account()

    assert result["cash"] == 100000.00
    assert result["buying_power"] == 200000.00
    assert result["equity"] == 100000.00


@patch("backend.alpaca_paper_client.TradingClient")
def test_submit_market_order(mock_tc_class, mock_settings):
    mock_tc = MagicMock()
    order = MagicMock()
    order.id = "order-123"
    order.status = "accepted"
    order.symbol = "AAPL"
    order.qty = "10"
    order.side = "buy"
    order.filled_avg_price = None
    order.filled_at = None
    order.submitted_at = "2026-04-15T14:30:00Z"
    mock_tc.submit_order.return_value = order
    mock_tc_class.return_value = mock_tc

    from backend.alpaca_paper_client import AlpacaPaperClient
    client = AlpacaPaperClient(mock_settings)
    result = client.submit_market_order("AAPL", qty=10, side="buy")

    assert result["order_id"] == "order-123"
    assert result["status"] == "accepted"
    assert result["symbol"] == "AAPL"
    mock_tc.submit_order.assert_called_once()


@patch("backend.alpaca_paper_client.TradingClient")
def test_get_positions(mock_tc_class, mock_settings):
    mock_tc = MagicMock()
    pos = MagicMock()
    pos.symbol = "AAPL"
    pos.qty = "10"
    pos.avg_entry_price = "150.00"
    pos.current_price = "155.00"
    pos.unrealized_pl = "50.00"
    pos.unrealized_plpc = "0.0333"
    pos.market_value = "1550.00"
    pos.side = "long"
    mock_tc.get_all_positions.return_value = [pos]
    mock_tc_class.return_value = mock_tc

    from backend.alpaca_paper_client import AlpacaPaperClient
    client = AlpacaPaperClient(mock_settings)
    positions = client.get_positions()

    assert len(positions) == 1
    assert positions[0]["symbol"] == "AAPL"
    assert positions[0]["qty"] == 10
    assert positions[0]["avg_entry_price"] == 150.00


@patch("backend.alpaca_paper_client.TradingClient")
def test_get_orders(mock_tc_class, mock_settings):
    mock_tc = MagicMock()
    order = MagicMock()
    order.id = "order-456"
    order.symbol = "MSFT"
    order.qty = "5"
    order.side = "buy"
    order.status = "filled"
    order.filled_avg_price = "400.00"
    order.filled_at = "2026-04-15T14:31:00Z"
    order.submitted_at = "2026-04-15T14:30:00Z"
    order.order_type = "market"
    mock_tc.get_orders.return_value = [order]
    mock_tc_class.return_value = mock_tc

    from backend.alpaca_paper_client import AlpacaPaperClient
    client = AlpacaPaperClient(mock_settings)
    orders = client.get_orders()

    assert len(orders) == 1
    assert orders[0]["order_id"] == "order-456"
    assert orders[0]["filled_avg_price"] == 400.00


@patch("backend.alpaca_paper_client.TradingClient")
def test_sync_positions_to_sqlite(mock_tc_class, mock_settings):
    mock_tc = MagicMock()
    pos = MagicMock()
    pos.symbol = "AAPL"
    pos.qty = "10"
    pos.avg_entry_price = "150.00"
    pos.current_price = "155.00"
    pos.unrealized_pl = "50.00"
    pos.unrealized_plpc = "0.0333"
    pos.market_value = "1550.00"
    pos.side = "long"
    mock_tc.get_all_positions.return_value = [pos]
    mock_tc_class.return_value = mock_tc

    from backend.alpaca_paper_client import AlpacaPaperClient
    client = AlpacaPaperClient(mock_settings)
    client.sync_positions_to_db()

    conn = sqlite3.connect(mock_settings.warehouse_db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM paper_positions").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["entry_price"] == 150.00


@patch("backend.alpaca_paper_client.TradingClient")
def test_close_position(mock_tc_class, mock_settings):
    mock_tc = MagicMock()
    order = MagicMock()
    order.id = "close-789"
    order.status = "accepted"
    order.symbol = "AAPL"
    order.qty = "10"
    order.side = "sell"
    order.filled_avg_price = None
    order.filled_at = None
    order.submitted_at = "2026-04-15T15:00:00Z"
    mock_tc.close_position.return_value = order
    mock_tc_class.return_value = mock_tc

    from backend.alpaca_paper_client import AlpacaPaperClient
    client = AlpacaPaperClient(mock_settings)
    result = client.close_position("AAPL")

    assert result["order_id"] == "close-789"
    mock_tc.close_position.assert_called_once_with("AAPL")
