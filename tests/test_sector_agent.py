"""Tests for the SectorSpecialistAgent."""

import pytest

from agents.sector import SectorSpecialistAgent
from config import settings
from models import AnalysisData


def test_specialist_loads_correct_prompt(tmp_path, fake_provider):
    prompt = tmp_path / "sector_test.md"
    prompt.write_text("You are a test sector analyst for [COMPANY NAME] ([TICKER]).")

    agent = SectorSpecialistAgent(prompt_file=str(prompt), provider=fake_provider)
    data = AnalysisData(
        ticker="PFE",
        company_name="Pfizer Inc.",
        sector="Healthcare",
        industry="Drug Manufacturers",
    )

    system = agent.get_system_prompt(data)
    assert "Pfizer Inc." in system
    assert "PFE" in system
    assert "test sector analyst" in system


def test_specialist_respects_max_tokens(fake_provider):
    agent = SectorSpecialistAgent(
        prompt_file="prompts/sector_healthcare.md", provider=fake_provider
    )
    assert agent.max_tokens == settings.max_sector_briefing_tokens


def test_specialist_enrichment_sections_include_external_sector():
    agent = SectorSpecialistAgent(prompt_file="prompts/sector_healthcare.md")
    assert "external_sector" in agent.enrichment_sections
    assert agent.enrichment_sections[0] == "external_sector"


def test_build_context_includes_sector_and_industry(fake_provider):
    agent = SectorSpecialistAgent(
        prompt_file="prompts/sector_healthcare.md", provider=fake_provider
    )
    data = AnalysisData(
        ticker="PFE",
        company_name="Pfizer Inc.",
        sector="Healthcare",
        industry="Drug Manufacturers",
        financial_core_summary="Revenue: $50B",
        metrics={"revenue": 50_000_000_000, "gross_margin": 0.65},
    )
    context = agent.build_context(data)
    assert "Sector: Healthcare" in context
    assert "Industry: Drug Manufacturers" in context
    assert "Revenue: $50B" in context
    assert "gross_margin" in context


@pytest.mark.asyncio
async def test_specialist_analyze_returns_string(tmp_path, fake_provider):
    prompt = tmp_path / "sector_test.md"
    prompt.write_text("You are a test sector analyst.")

    agent = SectorSpecialistAgent(prompt_file=str(prompt), provider=fake_provider)
    data = AnalysisData(
        ticker="PFE",
        company_name="Pfizer Inc.",
        sector="Healthcare",
    )
    result = await agent.analyze(data)
    assert isinstance(result, str)
    assert len(result) > 0
