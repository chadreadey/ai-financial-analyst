"""Tests for orchestrator module."""

import threading
from unittest.mock import MagicMock, patch

import pytest

from config import settings
from models import AgentReport
from orchestrator import Orchestrator, _extract_structured_block
from tests.conftest import FakeProvider


class TestExtractStructuredBlock:
    def test_valid_json_block(self):
        text = 'This is the analysis.\n\n```json\n{"verdict": "BUY", "conviction": "HIGH"}\n```'
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
        text = "Analysis text.\n\n```json\n{not valid json}\n```"
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
    mock_parser.compute_quarterly_metrics.return_value = []
    mock_parser.get_quarterly_summary_text.return_value = ""
    mock_parser.get_historical_margins.return_value = []
    mock_parser.get_historical_cash_flow.return_value = []
    mock_parser.get_historical_revenue.return_value = []
    mock_parser.get_historical_net_income.return_value = []

    with (
        patch("orchestrator.build_enrichment_context", side_effect=fake_enrich),
        patch("orchestrator.XBRLParser", return_value=mock_parser),
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


@pytest.mark.asyncio
async def test_split_gather_healthcare(sample_analysis_data, fake_provider, monkeypatch):
    """When sector = Healthcare, specialist runs wave 1, briefing injected, Competitive in wave 2."""
    monkeypatch.setattr(settings, "enable_sector_specialists", True)
    sample_analysis_data.sector = "Healthcare"
    sample_analysis_data.industry = "Drug Manufacturers"

    sec_client = MagicMock()
    sec_client.cache.save_analysis = MagicMock()

    orchestrator = Orchestrator(sec_client=sec_client, provider=fake_provider)

    with patch("orchestrator.asyncio.to_thread", return_value=sample_analysis_data):
        result = await orchestrator.run("PFE")

    assert "sector_briefing" in sample_analysis_data.enrichment_sections
    agent_names = [r.agent_name for r in result.agent_reports]
    assert "Competitive & Sector Analyst" in agent_names


@pytest.mark.asyncio
async def test_no_specialist_for_unknown_sector(sample_analysis_data, fake_provider, monkeypatch):
    """When sector is not in the map, fall back to single-gather run_phase1."""
    monkeypatch.setattr(settings, "enable_sector_specialists", True)
    sample_analysis_data.sector = "Utilities"

    sec_client = MagicMock()
    sec_client.cache.save_analysis = MagicMock()

    orchestrator = Orchestrator(sec_client=sec_client, provider=fake_provider)

    with patch("orchestrator.asyncio.to_thread", return_value=sample_analysis_data):
        result = await orchestrator.run("NEE")

    assert "sector_briefing" not in sample_analysis_data.enrichment_sections
    assert len(result.agent_reports) >= 5


@pytest.mark.asyncio
async def test_specialist_disabled_by_flag(sample_analysis_data, fake_provider, monkeypatch):
    """When the feature flag is off, no specialist runs even for Healthcare."""
    monkeypatch.setattr(settings, "enable_sector_specialists", False)
    sample_analysis_data.sector = "Healthcare"

    sec_client = MagicMock()
    sec_client.cache.save_analysis = MagicMock()

    orchestrator = Orchestrator(sec_client=sec_client, provider=fake_provider)

    with patch("orchestrator.asyncio.to_thread", return_value=sample_analysis_data):
        result = await orchestrator.run("PFE")

    assert "sector_briefing" not in sample_analysis_data.enrichment_sections
    assert len(result.agent_reports) >= 5


class _CapturingProvider(FakeProvider):
    def __init__(self):
        super().__init__("synthesis")
        self.user = None
        self.max_tokens = None

    async def generate(self, system, user, model=None, max_tokens=4096):
        self.user = user
        self.max_tokens = max_tokens
        return self._response


AGENT_NAMES = ["DCF", "Risk", "Earnings", "Pattern", "Macro", "Competitive"]


def _long_reports(n_chars=9000):
    return [
        AgentReport(
            agent_name=name,
            analysis="x" * n_chars + f'\n```json\n{{"a": 1}}\n```\nSIGNAL_SCORE: 0.{i + 1}0',
        )
        for i, name in enumerate(AGENT_NAMES)
    ]


@pytest.mark.asyncio
async def test_run_phase2_keeps_every_signal_score_when_trimming(monkeypatch):
    """Over-budget reports are cut in the middle, so each SIGNAL_SCORE survives."""
    monkeypatch.setattr(settings, "synthesis_report_max_chars", 4500)
    monkeypatch.setattr(settings, "synthesis_input_max_chars", 14000)
    provider = _CapturingProvider()
    orch = Orchestrator(sec_client=MagicMock(), provider=provider)

    await orch.run_phase2("TEST", "Test Corp", _long_reports())

    for i, name in enumerate(AGENT_NAMES):
        assert f"REPORT FROM: {name}" in provider.user
        assert f"SIGNAL_SCORE: 0.{i + 1}0" in provider.user
    assert provider.user.count('{"a": 1}') == len(AGENT_NAMES)
    assert "[synthesis input trimmed]" not in provider.user
    assert provider.user.count("[agent report trimmed]") == len(AGENT_NAMES)


@pytest.mark.asyncio
async def test_run_phase2_short_reports_pass_through_untrimmed(monkeypatch):
    monkeypatch.setattr(settings, "synthesis_report_max_chars", 4500)
    monkeypatch.setattr(settings, "synthesis_input_max_chars", 30000)
    provider = _CapturingProvider()
    orch = Orchestrator(sec_client=MagicMock(), provider=provider)

    reports = _long_reports(n_chars=1000)
    await orch.run_phase2("TEST", "Test Corp", reports)

    assert "trimmed]" not in provider.user
    for r in reports:
        assert r.analysis in provider.user


def test_default_output_budgets_leave_room_for_signal_score():
    """At 1200 tokens every showcase agent report was cut before SIGNAL_SCORE."""
    from backend.schemas import RunAnalysisRequest
    from config import Settings

    fields = Settings.model_fields
    assert fields["max_agent_output_tokens"].default >= 16000
    assert fields["max_synthesis_output_tokens"].default >= 16000
    assert fields["max_sector_briefing_tokens"].default >= 8000
    assert RunAnalysisRequest.model_fields["max_agent_output_tokens"].default == (
        fields["max_agent_output_tokens"].default
    )


@pytest.mark.asyncio
async def test_failed_sector_specialist_does_not_sink_the_run(
    sample_analysis_data, fake_provider, caplog
):
    """A specialist that runs out of tokens is optional context, not fatal."""
    orch = Orchestrator(sec_client=MagicMock(), provider=fake_provider)
    specialist = MagicMock()

    async def boom(data):
        raise RuntimeError("returned no text block (stop_reason=max_tokens)")

    specialist.analyze = boom
    with caplog.at_level("WARNING", logger="orchestrator"):
        assert await orch._run_specialist(specialist, sample_analysis_data) == ""
    assert "continuing without briefing" in caplog.text
