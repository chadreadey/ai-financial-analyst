"""Tests for paper trading scheduler."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@patch("backend.paper_scheduler.get_alpaca_client")
@patch("backend.paper_scheduler.run_analysis_job")
@patch("backend.paper_scheduler.create_job")
def test_rebalance_job_runs_analysis_and_submits_orders(
    mock_create_job, mock_run_analysis, mock_get_client
):
    from backend.paper_scheduler import run_rebalance

    mock_client = MagicMock()
    mock_client.get_positions.return_value = [
        {"symbol": "AAPL", "qty": 10, "side": "long"},
    ]
    mock_client.close_position.return_value = {"order_id": "close-1", "status": "accepted"}
    mock_client.submit_market_order.return_value = {"order_id": "buy-1", "status": "accepted"}
    mock_client.sync_positions_to_db.return_value = 2
    mock_get_client.return_value = mock_client

    mock_job = MagicMock()
    mock_job.status = "complete"
    mock_job.result = MagicMock()
    mock_job.result.structured_verdict = {
        "verdict": "BUY",
        "conviction_score": 0.75,
        "entry_price": 180.0,
    }
    mock_create_job.return_value = mock_job

    result = run_rebalance(target_tickers=["MSFT"])

    assert result["status"] == "ok"
    assert result["closed"] == ["AAPL"]
    assert result["opened"] == ["MSFT"]


def test_scheduler_starts_without_error():
    from backend.paper_scheduler import create_scheduler
    scheduler = create_scheduler(start=False)
    assert scheduler is not None


# ── Two-stage pipeline (T7-T11) ──────────────────────────────────────────


def _client_with_no_positions():
    """Build a MagicMock Alpaca client with empty positions + canned responses."""
    client = MagicMock()
    client.get_positions.return_value = []
    client.close_position.return_value = {"order_id": "x", "status": "accepted"}
    client.submit_market_order.return_value = {"order_id": "buy-1", "status": "accepted"}
    client.sync_positions_to_db.return_value = 0
    return client


def _job_with_buy(conviction: float = 0.75):
    job = MagicMock()
    job.status = "complete"
    job.result = MagicMock()
    job.result.structured_verdict = {
        "verdict": "BUY",
        "conviction_score": conviction,
        "entry_price": 100.0,
    }
    return job


# ── T7 ───────────────────────────────────────────────────────────────────


@patch("backend.paper_scheduler.get_alpaca_client")
@patch("backend.paper_scheduler.run_analysis_job")
@patch("backend.paper_scheduler.create_job")
@patch("backend.paper_scheduler._quant_screen")
def test_run_rebalance_uses_quant_screen_by_default(
    mock_screen, mock_create_job, mock_run_analysis, mock_get_client
):
    from backend.paper_scheduler import run_rebalance

    mock_get_client.return_value = _client_with_no_positions()
    mock_create_job.return_value = _job_with_buy()
    mock_screen.return_value = ["MSFT", "GOOGL"]

    result = run_rebalance()

    mock_screen.assert_called_once()
    assert sorted(result["opened"]) == ["GOOGL", "MSFT"]


# ── T8 ───────────────────────────────────────────────────────────────────


@patch("backend.paper_scheduler.get_alpaca_client")
@patch("backend.paper_scheduler.run_analysis_job")
@patch("backend.paper_scheduler.create_job")
@patch("backend.paper_scheduler._quant_screen")
def test_run_rebalance_explicit_tickers_bypass_screen(
    mock_screen, mock_create_job, mock_run_analysis, mock_get_client
):
    from backend.paper_scheduler import run_rebalance

    mock_get_client.return_value = _client_with_no_positions()
    mock_create_job.return_value = _job_with_buy()

    result = run_rebalance(target_tickers=["AAPL"])

    mock_screen.assert_not_called()
    assert result["opened"] == ["AAPL"]


# ── T9 ───────────────────────────────────────────────────────────────────


@patch("backend.paper_scheduler.get_alpaca_client")
@patch("backend.paper_scheduler.run_analysis_job")
@patch("backend.paper_scheduler.create_job")
@patch("backend.paper_scheduler._get_watchlist_tickers")
@patch("backend.paper_scheduler._quant_screen")
def test_run_rebalance_falls_back_to_watchlist_on_screen_error(
    mock_screen, mock_watchlist, mock_create_job, mock_run_analysis, mock_get_client
):
    from backend.paper_scheduler import run_rebalance

    mock_get_client.return_value = _client_with_no_positions()
    mock_create_job.return_value = _job_with_buy()
    mock_screen.side_effect = RuntimeError("DB missing")
    mock_watchlist.return_value = ["JPM"]

    result = run_rebalance()

    mock_screen.assert_called_once()
    mock_watchlist.assert_called_once()
    assert result["opened"] == ["JPM"]
    # Errors list reflects only per-ticker order errors, not the screen
    # fallback (which is transparent by design — R8 / loud-failure spec).
    assert not any("screen" in e.lower() for e in result["errors"])


# ── T10 ──────────────────────────────────────────────────────────────────


@patch("backend.paper_scheduler.get_alpaca_client")
@patch("backend.paper_scheduler.run_analysis_job")
@patch("backend.paper_scheduler.create_job")
@patch("backend.paper_scheduler._get_watchlist_tickers")
@patch("backend.paper_scheduler._quant_screen")
def test_run_rebalance_use_quant_screen_false_uses_watchlist(
    mock_screen, mock_watchlist, mock_create_job, mock_run_analysis, mock_get_client
):
    from backend.paper_scheduler import run_rebalance

    mock_get_client.return_value = _client_with_no_positions()
    mock_create_job.return_value = _job_with_buy()
    mock_watchlist.return_value = ["XOM"]

    result = run_rebalance(use_quant_screen=False)

    mock_screen.assert_not_called()
    mock_watchlist.assert_called_once()
    assert result["opened"] == ["XOM"]


# ── T11 ──────────────────────────────────────────────────────────────────


@patch("backend.paper_scheduler.get_alpaca_client")
@patch("backend.paper_scheduler.run_analysis_job")
@patch("backend.paper_scheduler.create_job")
@patch("backend.paper_scheduler._get_watchlist_tickers")
@patch("backend.paper_scheduler._quant_screen")
def test_run_rebalance_no_targets_returns_no_targets_status(
    mock_screen, mock_watchlist, mock_create_job, mock_run_analysis, mock_get_client
):
    from backend.paper_scheduler import run_rebalance

    mock_get_client.return_value = _client_with_no_positions()
    mock_screen.return_value = []

    result = run_rebalance()

    mock_screen.assert_called_once()
    # Watchlist must NOT be hit — screen succeeded (returned []) so no
    # fallback fires; we go straight to the no-op path.
    mock_watchlist.assert_not_called()
    mock_create_job.assert_not_called()
    assert result == {"status": "no_targets", "closed": [], "opened": [], "errors": []}
