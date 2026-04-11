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
