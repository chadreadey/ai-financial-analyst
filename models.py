"""
Typed data models for the analysis pipeline.

These replace the untyped ``Dict[str, Any]`` blobs that previously
flowed between the orchestrator, agents, and report layer.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class FilingInfo(BaseModel):
    form: str
    filingDate: str
    accessionNumber: str
    primaryDocument: str = ""


class AnalysisData(BaseModel):
    """Unified data payload that all agents consume."""

    ticker: str
    company_name: str
    sector: str = ""
    industry: str = ""
    financial_core_summary: str = ""
    financial_summary: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    recent_filings: list[FilingInfo] = Field(default_factory=list)
    historical_revenue: list[Any] = Field(default_factory=list)
    historical_net_income: list[Any] = Field(default_factory=list)
    margin_trends: list[Any] = Field(default_factory=list)
    cash_flow_trends: list[Any] = Field(default_factory=list)
    quarterly_metrics: list[Any] = Field(default_factory=list)
    quarterly_summary: str = ""
    enrichment_sections: dict[str, str] = Field(default_factory=dict)
    enrichment_warnings: list[str] = Field(default_factory=list)
    enrichment_sources: list[str] = Field(default_factory=list)
    enrichment_filter_stats: dict[str, int] = Field(default_factory=dict)


class AgentReport(BaseModel):
    agent_name: str
    analysis: str


class AnalysisResult(BaseModel):
    """Return type of ``Orchestrator.run()``."""

    ticker: str
    company_name: str
    agent_reports: list[AgentReport]
    synthesis: str
    structured_verdict: Optional[dict[str, Any]] = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    enrichment_warnings: list[str] = Field(default_factory=list)
    enrichment_sources: list[str] = Field(default_factory=list)
    enrichment_filter_stats: dict[str, int] = Field(default_factory=dict)
