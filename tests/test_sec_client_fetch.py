"""Tests for SECClient.fetch_filings_and_facts."""

from unittest.mock import MagicMock

from sec.client import SECClient


def test_fetch_filings_and_facts_delegates_to_helpers():
    client = SECClient()
    filings = [{"form": "10-K", "accessionNumber": "1", "filingDate": "2025-01-01", "primaryDocument": "x.htm"}]
    facts = {"entityName": "Test"}

    client.get_recent_filings = MagicMock(return_value=filings)
    client.get_company_facts = MagicMock(return_value=facts)

    out_filings, out_facts = client.fetch_filings_and_facts("TEST")

    assert out_filings == filings
    assert out_facts == facts
    client.get_recent_filings.assert_called_once()
    client.get_company_facts.assert_called_once()
