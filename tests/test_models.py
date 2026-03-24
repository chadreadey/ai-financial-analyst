"""Tests for Pydantic data models."""

from models import AgentReport, AnalysisData, AnalysisResult, FilingInfo


def test_filing_info_construction():
    f = FilingInfo(
        form="10-K",
        filingDate="2025-01-15",
        accessionNumber="0001234567-25-000001",
    )
    assert f.form == "10-K"
    assert f.primaryDocument == ""


def test_analysis_data_defaults():
    data = AnalysisData(ticker="AAPL", company_name="Apple Inc")
    assert data.financial_core_summary == ""
    assert data.metrics == {}
    assert data.recent_filings == []
    assert data.enrichment_sections == {}


def test_analysis_data_with_filings(sample_analysis_data):
    assert sample_analysis_data.ticker == "TEST"
    assert len(sample_analysis_data.recent_filings) == 2
    assert sample_analysis_data.recent_filings[0].form == "10-K"


def test_analysis_data_serialization(sample_analysis_data):
    d = sample_analysis_data.model_dump()
    assert d["ticker"] == "TEST"
    assert isinstance(d["recent_filings"], list)
    assert d["recent_filings"][0]["form"] == "10-K"

    roundtrip = AnalysisData.model_validate(d)
    assert roundtrip.ticker == sample_analysis_data.ticker


def test_agent_report():
    r = AgentReport(agent_name="Test Agent", analysis="Analysis text.")
    assert r.agent_name == "Test Agent"
    assert r.analysis == "Analysis text."


def test_analysis_result_defaults():
    result = AnalysisResult(
        ticker="AAPL",
        company_name="Apple Inc",
        agent_reports=[],
        synthesis="Buy it.",
    )
    assert result.structured_verdict is None
    assert result.metrics == {}
    assert result.enrichment_warnings == []


def test_analysis_result_with_verdict():
    result = AnalysisResult(
        ticker="AAPL",
        company_name="Apple Inc",
        agent_reports=[
            AgentReport(agent_name="DCF", analysis="$200 target"),
        ],
        synthesis="Strong buy.",
        structured_verdict={"verdict": "BUY", "conviction": "HIGH"},
    )
    assert result.structured_verdict["verdict"] == "BUY"
    assert len(result.agent_reports) == 1
