"""Tests for paper trading scheduler.

Bundle 0 regression tests cover the audit findings the rewrite closes:
  F-002  fail-closed universe (watchlist error / empty never flattens book)
  F-001  single order submitter (orchestrator auto-trade disabled)
  F-006  verdict-flip exits for held names
  F-007  verdict substring-trap classification
  F-005  non-reentrant rebalance
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_job(verdict="BUY", conviction=0.75, entry=180.0):
    job = MagicMock()
    job.status = "complete"
    job.result = MagicMock()
    job.result.structured_verdict = {
        "verdict": verdict,
        "conviction_score": conviction,
        "entry_price": entry,
    }
    return job


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

    mock_create_job.return_value = _make_job()

    result = run_rebalance(target_tickers=["MSFT"])

    assert result["status"] == "ok"
    assert result["closed"] == ["AAPL"]
    assert result["opened"] == ["MSFT"]


def test_scheduler_starts_without_error():
    from backend.paper_scheduler import create_scheduler

    scheduler = create_scheduler(start=False)
    assert scheduler is not None


def test_verdict_side_classification():
    """F-007: never mis-read negated/ambiguous text as a buy."""
    from backend.paper_scheduler import _verdict_side

    assert _verdict_side("BUY") == "buy"
    assert _verdict_side("STRONG BUY") == "buy"
    assert _verdict_side("SELL") == "sell"
    assert _verdict_side("STRONG SELL") == "sell"
    assert _verdict_side("HOLD") is None
    assert _verdict_side("") is None
    # The substring trap: "DO NOT BUY" must NOT be treated as a buy.
    assert _verdict_side("DO NOT BUY") is None


@patch("backend.paper_scheduler.get_alpaca_client")
@patch("backend.paper_scheduler.sqlite3.connect")
def test_rebalance_fails_closed_on_watchlist_error(mock_connect, mock_get_client):
    """F-002: a watchlist read error must abort WITHOUT closing positions."""
    from backend.paper_scheduler import run_rebalance

    mock_client = MagicMock()
    mock_client.get_positions.return_value = [
        {"symbol": "AAPL", "qty": 10, "side": "long"},
        {"symbol": "MSFT", "qty": 5, "side": "long"},
    ]
    mock_get_client.return_value = mock_client
    mock_connect.side_effect = Exception("db unavailable")

    result = run_rebalance()  # scheduled path → sources from watchlist

    assert result["status"] == "aborted-watchlist-error"
    assert result["closed"] == []
    mock_client.close_position.assert_not_called()


@patch("backend.paper_scheduler.get_alpaca_client")
@patch("backend.paper_scheduler._get_watchlist_tickers")
def test_rebalance_fails_closed_on_empty_universe(mock_watchlist, mock_get_client):
    """F-002: an empty watchlist must NOT be read as 'sell everything'."""
    from backend.paper_scheduler import run_rebalance

    mock_client = MagicMock()
    mock_client.get_positions.return_value = [
        {"symbol": "AAPL", "qty": 10, "side": "long"},
    ]
    mock_get_client.return_value = mock_client
    mock_watchlist.return_value = []

    result = run_rebalance()

    assert result["status"] == "aborted-empty-universe"
    assert result["closed"] == []
    mock_client.close_position.assert_not_called()


@patch("backend.paper_scheduler.get_alpaca_client")
@patch("backend.paper_scheduler.run_analysis_job")
@patch("backend.paper_scheduler.create_job")
def test_rebalance_is_single_submitter(mock_create_job, mock_run_analysis, mock_get_client):
    """F-001: analysis must run with auto_paper_trade disabled, and the
    scheduler must submit exactly one order per opened name."""
    from backend.paper_scheduler import run_rebalance

    mock_client = MagicMock()
    mock_client.get_positions.return_value = []
    mock_client.submit_market_order.return_value = {"order_id": "buy-1"}
    mock_get_client.return_value = mock_client
    mock_create_job.return_value = _make_job(verdict="BUY", conviction=0.9)

    result = run_rebalance(target_tickers=["MSFT"])

    assert result["opened"] == ["MSFT"]
    mock_client.submit_market_order.assert_called_once()
    # Orchestrator auto-trade explicitly disabled so it is not a 2nd submitter.
    assert mock_run_analysis.call_args.kwargs.get("auto_paper_trade") is False


@patch("backend.paper_scheduler.get_alpaca_client")
@patch("backend.paper_scheduler.run_analysis_job")
@patch("backend.paper_scheduler.create_job")
def test_rebalance_closes_held_name_on_verdict_flip(
    mock_create_job, mock_run_analysis, mock_get_client
):
    """F-006: a held name whose fresh verdict turns bearish must be closed."""
    from backend.paper_scheduler import run_rebalance

    mock_client = MagicMock()
    mock_client.get_positions.return_value = [
        {"symbol": "AAPL", "qty": 10, "side": "long"},
    ]
    mock_get_client.return_value = mock_client
    mock_create_job.return_value = _make_job(verdict="STRONG SELL", conviction=0.85)

    result = run_rebalance(target_tickers=["AAPL"])

    assert "AAPL" in result["closed"]
    mock_client.close_position.assert_called_once_with("AAPL")
    mock_client.submit_market_order.assert_not_called()


@patch("backend.paper_scheduler.get_alpaca_client")
def test_rebalance_is_non_reentrant(mock_get_client):
    """F-005: a rebalance already in progress must be skipped, not interleaved."""
    from backend import paper_scheduler

    acquired = paper_scheduler._rebalance_lock.acquire(blocking=False)
    assert acquired
    try:
        result = paper_scheduler.run_rebalance(target_tickers=["MSFT"])
    finally:
        paper_scheduler._rebalance_lock.release()

    assert result["status"] == "skipped-already-running"
    mock_get_client.assert_not_called()
