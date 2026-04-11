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
