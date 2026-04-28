"""Tests for portfolio router (candidates endpoint)."""
from __future__ import annotations

import sqlite3
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.main import app
    return TestClient(app)


@pytest.fixture
def temp_warehouse(tmp_path, monkeypatch):
    db_path = tmp_path / "warehouse.db"
    from config import settings as config_settings
    monkeypatch.setattr(config_settings, "warehouse_db_path", str(db_path))
    return db_path


def _seed_paper_position(db_path, ticker: str):
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
        "INSERT OR REPLACE INTO paper_positions (ticker, entry_price, entry_date, verdict) "
        "VALUES (?, ?, ?, ?)",
        (ticker, 100.0, "2026-04-01", "BUY"),
    )
    conn.commit()
    conn.close()


def _seed_cached_ranking(db_path, ticker: str, score: float, direction: str = "BUY",
                         actionable: bool = True, age_seconds: float = 60):
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quant_rankings (
            ticker TEXT PRIMARY KEY,
            ranked_at REAL NOT NULL,
            composite_score REAL NOT NULL,
            composite_direction TEXT NOT NULL,
            actionable INTEGER NOT NULL,
            top_signals_json TEXT NOT NULL,
            universe TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO quant_rankings "
        "(ticker, ranked_at, composite_score, composite_direction, "
        "actionable, top_signals_json, universe) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            ticker,
            time.time() - age_seconds,
            score,
            direction,
            1 if actionable else 0,
            '[{"name": "obv_trend", "score": 0.4}]',
            "liquid_20",
        ),
    )
    conn.commit()
    conn.close()


@patch("backend.routers.portfolio._compute_rankings")
def test_candidates_uses_fresh_cache(mock_compute, client, temp_warehouse):
    """Cached rows <1h old should be served without recomputing."""
    _seed_cached_ranking(temp_warehouse, "AAPL", 0.7, "BUY", age_seconds=600)
    _seed_cached_ranking(temp_warehouse, "MSFT", 0.5, "BUY", age_seconds=600)

    resp = client.get("/api/portfolio/candidates?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert mock_compute.call_count == 0  # Did not recompute
    tickers = [c["ticker"] for c in data["candidates"]]
    assert tickers == ["AAPL", "MSFT"]  # Sorted by composite_score DESC
    assert data["candidates"][0]["composite_score"] == 0.7
    assert data["candidates"][0]["actionable"] is True
    assert data["candidates"][0]["top_signals"][0]["name"] == "obv_trend"


@patch("backend.routers.portfolio._compute_rankings")
def test_candidates_excludes_held_tickers(mock_compute, client, temp_warehouse):
    _seed_paper_position(temp_warehouse, "AAPL")
    _seed_cached_ranking(temp_warehouse, "AAPL", 0.7, age_seconds=600)
    _seed_cached_ranking(temp_warehouse, "MSFT", 0.5, age_seconds=600)

    resp = client.get("/api/portfolio/candidates?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    tickers = [c["ticker"] for c in data["candidates"]]
    assert "AAPL" not in tickers
    assert "MSFT" in tickers


@patch("backend.routers.portfolio._compute_rankings")
def test_candidates_recomputes_when_stale(mock_compute, client, temp_warehouse):
    """Cache older than TTL triggers recompute."""
    _seed_cached_ranking(temp_warehouse, "AAPL", 0.7, age_seconds=86400)  # >1h old
    mock_compute.return_value = (
        [
            {
                "ticker": "GOOGL",
                "composite_score": 0.9,
                "composite_direction": "BUY",
                "actionable": True,
                "top_signals_json": '[{"name": "rsi", "score": 0.6}]',
            },
            {
                "ticker": "AMZN",
                "composite_score": 0.4,
                "composite_direction": "BUY",
                "actionable": False,
                "top_signals_json": "[]",
            },
        ],
        [],  # no errors
    )

    resp = client.get("/api/portfolio/candidates?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert mock_compute.call_count == 1
    tickers = [c["ticker"] for c in data["candidates"]]
    # Stale AAPL row should have been replaced; new ranking is GOOGL > AMZN
    assert tickers == ["GOOGL", "AMZN"]


@patch("backend.routers.portfolio._compute_rankings")
def test_candidates_force_refresh(mock_compute, client, temp_warehouse):
    _seed_cached_ranking(temp_warehouse, "AAPL", 0.7, age_seconds=60)  # very fresh
    mock_compute.return_value = (
        [
            {
                "ticker": "TSLA",
                "composite_score": 0.95,
                "composite_direction": "BUY",
                "actionable": True,
                "top_signals_json": "[]",
            },
        ],
        [],
    )

    resp = client.get("/api/portfolio/candidates?refresh=true")
    assert resp.status_code == 200
    data = resp.json()
    assert mock_compute.call_count == 1
    assert data["candidates"][0]["ticker"] == "TSLA"


@patch("backend.routers.portfolio._compute_rankings")
def test_candidates_handles_ranker_error(mock_compute, client, temp_warehouse):
    """If ranker blows up and we have no cache, return empty + error."""
    mock_compute.side_effect = RuntimeError("provider down")

    resp = client.get("/api/portfolio/candidates?refresh=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidates"] == []
    assert any("provider down" in e for e in data["errors"])
