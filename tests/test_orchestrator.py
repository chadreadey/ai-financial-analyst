"""Tests for orchestrator module."""

import threading
from unittest.mock import MagicMock, patch

import pytest

from config import settings
from orchestrator import Orchestrator, _extract_structured_block


class TestExtractStructuredBlock:
    def test_valid_json_block(self):
        text = (
            "This is the analysis.\n\n"
            "```json\n"
            '{"verdict": "BUY", "conviction": "HIGH"}\n'
            "```"
        )
        parsed, prose = _extract_structured_block(text)
        assert parsed is not None
        assert parsed["verdict"] == "BUY"
        assert parsed["conviction"] == "HIGH"
        assert "```json" not in prose
        assert prose.strip() == "This is the analysis."

    def test_no_json_block(self):
        text = "Just a plain analysis with no JSON."
        parsed, prose = _extract_structured_block(text)
        assert parsed is None
        assert prose == text

    def test_malformed_json(self):
        text = (
            "Analysis text.\n\n"
            "```json\n"
            '{not valid json}\n'
            "```"
        )
        parsed, prose = _extract_structured_block(text)
        assert parsed is None
        assert prose == text

    def test_json_with_health_scores(self):
        text = (
            "Full report here.\n\n"
            "```json\n"
            '{"verdict": "HOLD", "health_scores": {"overall": 7, "valuation": 6}}\n'
            "```"
        )
        parsed, prose = _extract_structured_block(text)
        assert parsed is not None
        assert parsed["health_scores"]["overall"] == 7
        assert "Full report here." in prose

    def test_empty_string(self):
        parsed, prose = _extract_structured_block("")
        assert parsed is None
        assert prose == ""


def test_prepare_data_overlaps_enrichment_with_sec_fetch(monkeypatch):
    """Enrichment thread reaches overlap point while SEC fetch is still in progress."""
    monkeypatch.setattr(settings, "enable_filing_text", False)
    monkeypatch.setattr(settings, "enable_edgartools", False)

    barrier = threading.Barrier(2, timeout=3)
    events: list[str] = []

    def fake_enrich(ticker: str, company_name: str):
        events.append("enrich_at_barrier")
        barrier.wait()
        events.append("enrich_done")
        return {
            "text": "",
            "sections": {},
            "warnings": [],
            "sources": [],
            "filter_stats": {},
        }

    sec = MagicMock()
    sec.resolve_ticker.return_value = {"name": "TestCo", "cik": "1234567"}

    def fake_fetch_filings_and_facts(t: str):
        events.append("sec_at_barrier")
        barrier.wait()
        events.append("sec_done")
        return [], {"facts": "stub"}

    sec.fetch_filings_and_facts.side_effect = fake_fetch_filings_and_facts

    mock_parser = MagicMock()
    mock_parser.compute_metrics.return_value = {"revenue": 1}
    mock_parser.to_summary_text.return_value = "summary"
    mock_parser.compute_quarterly_metrics.return_value = {}
    mock_parser.get_quarterly_summary_text.return_value = ""
    mock_parser.get_historical_margins.return_value = []
    mock_parser.get_historical_cash_flow.return_value = []
    mock_parser.get_historical_revenue.return_value = []
    mock_parser.get_historical_net_income.return_value = []

    with patch("orchestrator.build_enrichment_context", side_effect=fake_enrich), patch(
        "orchestrator.XBRLParser", return_value=mock_parser
    ):
        orch = Orchestrator(sec_client=sec)
        orch.prepare_data("xom")

    assert events.index("enrich_at_barrier") < events.index("sec_done")
    assert events.index("sec_at_barrier") < events.index("enrich_done")


@pytest.mark.asyncio
async def test_run_phase1(sample_analysis_data, fake_provider):
    """Verify Phase 1 runs all agents and returns AgentReports."""
    from orchestrator import Orchestrator
    from unittest.mock import MagicMock

    sec_client = MagicMock()
    orchestrator = Orchestrator(
        sec_client=sec_client,
        provider=fake_provider,
    )

    reports = await orchestrator.run_phase1(sample_analysis_data)
    assert len(reports) >= 5
    for r in reports:
        assert r.agent_name
        assert r.analysis == "Test analysis output."
