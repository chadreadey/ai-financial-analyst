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
