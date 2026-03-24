"""Shared test fixtures."""

from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock

import pytest

from config import Settings
from llm import LLMProvider
from models import AgentReport, AnalysisData, FilingInfo


class FakeProvider(LLMProvider):
    """Deterministic LLM provider for tests."""

    name = "fake"
    default_model = "fake-model"

    def __init__(self, response: str = "Test analysis output."):
        self._response = response

    async def generate(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> str:
        return self._response


@pytest.fixture()
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture()
def sample_analysis_data() -> AnalysisData:
    return AnalysisData(
        ticker="TEST",
        company_name="Test Corp",
        financial_core_summary="Revenue: $100B\nNet Income: $20B",
        financial_summary="Revenue: $100B\nNet Income: $20B\n\nMarket data...",
        metrics={
            "revenue": 100_000_000_000,
            "net_income": 20_000_000_000,
            "gross_margin": 0.45,
            "operating_margin": 0.30,
            "net_margin": 0.20,
            "free_cash_flow": 25_000_000_000,
            "debt_to_equity": 0.5,
        },
        recent_filings=[
            FilingInfo(
                form="10-K",
                filingDate="2025-02-15",
                accessionNumber="0001234567-25-000001",
                primaryDocument="test-10k.htm",
            ),
            FilingInfo(
                form="10-Q",
                filingDate="2025-05-01",
                accessionNumber="0001234567-25-000002",
                primaryDocument="test-10q.htm",
            ),
        ],
        historical_revenue=[
            {"year": 2023, "value": 90_000_000_000},
            {"year": 2024, "value": 100_000_000_000},
        ],
        historical_net_income=[
            {"year": 2023, "value": 18_000_000_000},
            {"year": 2024, "value": 20_000_000_000},
        ],
        enrichment_sections={
            "market_data": "=== Market Data ===\nPrice: $150",
        },
    )


@pytest.fixture()
def sample_agent_reports() -> list[AgentReport]:
    return [
        AgentReport(agent_name="DCF Analyst", analysis="DCF says BUY at $180."),
        AgentReport(agent_name="Risk Analyst", analysis="Risk score: 4/10."),
    ]
