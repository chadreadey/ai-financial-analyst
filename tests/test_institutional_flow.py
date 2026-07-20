# tests/test_institutional_flow.py
"""Tests for institutional flow signal."""

import pytest
from unittest.mock import MagicMock, patch


class TestFMPInstitutionalOwnership:
    """Test FMP institutional ownership endpoint."""

    def test_get_institutional_ownership_history_returns_list(self):
        """FMP client should return list of quarterly snapshots."""
        from fmp_client import FMPClient

        mock_response = [
            {
                "date": "2025-12-31",
                "investorName": "Vanguard Group",
                "sharesNumber": 1_200_000_000,
                "sharesNumberChange": 50_000_000,
                "ownershipPercent": 8.5,
                "typeOfOwner": "Investment Advisor",
            },
            {
                "date": "2025-12-31",
                "investorName": "BlackRock",
                "sharesNumber": 1_000_000_000,
                "sharesNumberChange": -20_000_000,
                "ownershipPercent": 7.1,
                "typeOfOwner": "Investment Advisor",
            },
        ]

        client = FMPClient("test-key")
        with patch.object(client, "_get", return_value=mock_response):
            result = client.get_institutional_ownership_history("AAPL")

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["investorName"] == "Vanguard Group"
        assert result[0]["sharesNumberChange"] == 50_000_000

    def test_get_institutional_ownership_history_handles_error(self):
        """Should return empty list on API error."""
        from fmp_client import FMPClient

        client = FMPClient("test-key")
        with patch.object(client, "_get", side_effect=Exception("API error")):
            result = client.get_institutional_ownership_history("AAPL")

        assert result == []


class TestFinnhubInstitutionalOwnership:
    """Test Finnhub institutional ownership endpoint."""

    def test_get_institutional_ownership_returns_list(self):
        from finnhub_client import FinnhubClient

        mock_response = {
            "data": [
                {
                    "name": "Vanguard Group",
                    "share": 1_200_000_000,
                    "change": 50_000_000,
                    "filingDate": "2025-11-14",
                    "ownership": 8.5,
                },
                {
                    "name": "BlackRock",
                    "share": 1_000_000_000,
                    "change": -20_000_000,
                    "filingDate": "2025-11-14",
                    "ownership": 7.1,
                },
            ],
            "symbol": "AAPL",
        }

        client = FinnhubClient("test-key")
        with patch.object(client, "_get", return_value=mock_response):
            result = client.get_institutional_ownership("AAPL")

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["name"] == "Vanguard Group"

    def test_get_institutional_ownership_handles_error(self):
        from finnhub_client import FinnhubClient

        client = FinnhubClient("test-key")
        with patch.object(client, "_get", side_effect=Exception("API error")):
            result = client.get_institutional_ownership("AAPL")

        assert result == []


import tempfile
import os


class TestFMPFundamentalCacheInstitutional:
    """Test FMP cache methods for institutional data."""

    def test_round_trip_institutional_data(self):
        from quant.fmp_cache import FMPFundamentalCache

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_cache.db")
            cache = FMPFundamentalCache(db_path=db_path)

            test_data = [
                {"date": "2025-12-31", "investorName": "Vanguard", "sharesNumber": 1_000_000},
                {"date": "2025-12-31", "investorName": "BlackRock", "sharesNumber": 800_000},
            ]

            cache.set_institutional_quarterly("AAPL", test_data)
            result = cache.get_institutional_quarterly("AAPL")

            assert result is not None
            assert len(result) == 2
            assert result[0]["investorName"] == "Vanguard"

    def test_get_institutional_returns_none_when_missing(self):
        from quant.fmp_cache import FMPFundamentalCache

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_cache.db")
            cache = FMPFundamentalCache(db_path=db_path)

            result = cache.get_institutional_quarterly("MISSING")
            assert result is None


import numpy as np


class TestComputeInstitutionalFlowScore:
    """Test the core scoring function."""

    def test_strong_buying_returns_positive_score(self):
        from quant.institutional_flow import compute_institutional_flow_score

        current_snapshot = [
            {
                "investorName": f"Fund{i}",
                "sharesNumber": 1_000_000 + i * 100_000,
                "sharesNumberChange": 100_000,
            }
            for i in range(8)
        ] + [
            {"investorName": "Seller1", "sharesNumber": 500_000, "sharesNumberChange": -50_000},
            {"investorName": "Flat1", "sharesNumber": 300_000, "sharesNumberChange": 0},
        ]
        prior_snapshot = [
            {
                "investorName": f"Fund{i}",
                "sharesNumber": 1_000_000 + i * 100_000 - 100_000,
                "sharesNumberChange": 0,
            }
            for i in range(8)
        ] + [
            {"investorName": "Seller1", "sharesNumber": 550_000, "sharesNumberChange": 0},
            {"investorName": "Flat1", "sharesNumber": 300_000, "sharesNumberChange": 0},
        ]

        score, meta = compute_institutional_flow_score(
            current_snapshot=current_snapshot,
            prior_snapshot=prior_snapshot,
        )

        assert -1.0 <= score <= 1.0
        assert score > 0.3, f"Expected positive score for net buying, got {score}"
        assert meta["n_buying"] == 8
        assert meta["n_selling"] == 1

    def test_strong_selling_returns_negative_score(self):
        from quant.institutional_flow import compute_institutional_flow_score

        current_snapshot = [
            {"investorName": f"Fund{i}", "sharesNumber": 500_000, "sharesNumberChange": -200_000}
            for i in range(8)
        ] + [
            {"investorName": "Buyer1", "sharesNumber": 600_000, "sharesNumberChange": 50_000},
            {"investorName": "Flat1", "sharesNumber": 300_000, "sharesNumberChange": 0},
        ]
        prior_snapshot = [
            {"investorName": f"Fund{i}", "sharesNumber": 700_000, "sharesNumberChange": 0}
            for i in range(8)
        ] + [
            {"investorName": "Buyer1", "sharesNumber": 550_000, "sharesNumberChange": 0},
            {"investorName": "Flat1", "sharesNumber": 300_000, "sharesNumberChange": 0},
        ]

        score, meta = compute_institutional_flow_score(
            current_snapshot=current_snapshot,
            prior_snapshot=prior_snapshot,
        )

        assert -1.0 <= score <= 1.0
        assert score < -0.3, f"Expected negative score for net selling, got {score}"
        assert meta["n_selling"] == 8

    def test_insufficient_data_returns_zero(self):
        from quant.institutional_flow import compute_institutional_flow_score

        score, meta = compute_institutional_flow_score(
            current_snapshot=[
                {"investorName": "Solo", "sharesNumber": 100, "sharesNumberChange": 10}
            ],
            prior_snapshot=[],
        )

        assert score == 0.0
        assert "insufficient" in meta.get("error", "").lower() or meta.get("n_institutions", 0) < 3

    def test_empty_snapshots_returns_zero(self):
        from quant.institutional_flow import compute_institutional_flow_score

        score, meta = compute_institutional_flow_score(
            current_snapshot=[],
            prior_snapshot=[],
        )
        assert score == 0.0


class TestBlendInstitutionalFlow:
    """Test blending institutional flow into composite scores."""

    def test_blend_sets_institutional_flow_score(self):
        from quant.institutional_flow import blend_institutional_flow
        from quant.signals import SignalResult, SignalVector

        sv = SignalVector(
            sma_trend=SignalResult(0.0),
            mean_reversion_z=SignalResult(0.0),
            bollinger_pctb=SignalResult(0.0),
            rsi=SignalResult(0.0),
            obv_trend=SignalResult(0.5),
            atr_regime=SignalResult(0.0),
        )

        signals = {"AAPL": sv}
        flow_scores = {"AAPL": (0.8, {"n_institutions": 50, "data_source": "fmp"})}

        result = blend_institutional_flow(signals, flow_scores, weight=0.15)

        # Blend now sets the field instead of modifying composite
        assert result["AAPL"].institutional_flow_score == 0.8

    def test_blend_skips_missing_tickers(self):
        from quant.institutional_flow import blend_institutional_flow
        from quant.signals import SignalResult, SignalVector

        sv = SignalVector(
            sma_trend=SignalResult(0.0),
            mean_reversion_z=SignalResult(0.0),
            bollinger_pctb=SignalResult(0.0),
            rsi=SignalResult(0.0),
            obv_trend=SignalResult(0.5),
            atr_regime=SignalResult(0.0),
        )
        sv.composite_score = 0.5

        signals = {"AAPL": sv}
        flow_scores = {"MSFT": (0.8, {"n_institutions": 50, "data_source": "fmp"})}

        result = blend_institutional_flow(signals, flow_scores, weight=0.15)

        assert result["AAPL"].composite_score == 0.5  # unchanged
