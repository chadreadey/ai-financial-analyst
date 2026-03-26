"""
Orchestrator: Phase 1 fan-out + Phase 2 synthesis.

Phase 1: Run all analyst agents (5 core + optional Macro) in parallel via asyncio.gather().
Phase 2: Feed all agent outputs to a synthesis agent that
         cross-references findings and produces the final brief.
"""

import asyncio
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agents import (
    DCFAgent,
    RiskAgent,
    EarningsAgent,
    CompetitiveAgent,
    PatternAgent,
    MacroAgent,
    SectorSpecialistAgent,
)
from config import settings
from context_budget import trim_text
from llm import LLMProvider, get_provider
from market_enrichment import build_enrichment_context
from models import AgentReport, AnalysisData, AnalysisResult, FilingInfo
from prompt_loader import load_prompt_file, render_prompt
from sec.client import SECClient
from sec.filing_parser import parse_filing_sections
from sec.xbrl_parser import XBRLParser

logger = logging.getLogger(__name__)


def _extract_structured_block(synthesis_text: str) -> Tuple[Optional[dict], str]:
    """
    Extract the structured JSON block from the end of synthesis output.
    Returns (parsed_dict_or_None, prose_text_with_json_removed).
    """
    pattern = r"```json\s*\n(\{.*?\})\s*\n```"
    match = re.search(pattern, synthesis_text, re.DOTALL)
    if not match:
        return None, synthesis_text

    try:
        data = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None, synthesis_text

    prose = synthesis_text[:match.start()].rstrip()
    return data, prose


SYNTHESIS_PROMPT_FILE = Path("prompts/synthesis.md")

SECTOR_SPECIALIST_MAP: dict[str, str] = {
    "Healthcare": "prompts/sector_healthcare.md",
    "Technology": "prompts/sector_technology.md",
    "Energy": "prompts/sector_energy.md",
    "Financial Services": "prompts/sector_financials.md",
    "Financials": "prompts/sector_financials.md",
    "Consumer Cyclical": "prompts/sector_consumer.md",
    "Consumer Defensive": "prompts/sector_consumer.md",
}


class Orchestrator:
    """
    Coordinates the two-phase analysis pipeline.

    Usage:
        orchestrator = Orchestrator()
        result = asyncio.run(orchestrator.run("AAPL"))
    """

    def __init__(
        self,
        sec_client: Optional[SECClient] = None,
        provider: Optional[LLMProvider] = None,
        llm_provider_name: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.sec_client = sec_client or SECClient()
        self.provider = provider or get_provider(llm_provider_name)
        self.synthesis_model = model or self.provider.default_model
        self.agents = [
            DCFAgent(provider=self.provider, model=self.synthesis_model),
            RiskAgent(provider=self.provider, model=self.synthesis_model),
            EarningsAgent(provider=self.provider, model=self.synthesis_model),
            CompetitiveAgent(provider=self.provider, model=self.synthesis_model),
            PatternAgent(provider=self.provider, model=self.synthesis_model),
        ]
        if settings.enable_macro_agent:
            self.agents.append(
                MacroAgent(provider=self.provider, model=self.synthesis_model)
            )

    def prepare_data(self, ticker: str) -> AnalysisData:
        """
        Fetch and parse all SEC data for a ticker.
        Returns the unified AnalysisData that agents consume.
        """
        if os.getenv("ENABLE_WAREHOUSE", "").lower() == "true":
            try:
                from warehouse.db import WarehouseDB
                from warehouse.bootstrap import bootstrap_ticker
                from warehouse.change_detector import needs_update, incremental_update
                from warehouse.reader import build_analysis_data_from_warehouse

                db = WarehouseDB()
                company = db.get_company(ticker.upper())
                if company is None:
                    logger.info("Warehouse: bootstrapping %s...", ticker.upper())
                    bootstrap_ticker(ticker.upper(), db, self.sec_client)
                elif needs_update(ticker.upper(), db, self.sec_client):
                    logger.info("Warehouse: updating %s...", ticker.upper())
                    incremental_update(ticker.upper(), db, self.sec_client)

                data = build_analysis_data_from_warehouse(ticker.upper(), db)
                if data is not None:
                    logger.info("Warehouse: loaded %s from warehouse", ticker.upper())
                    info = self.sec_client.resolve_ticker(ticker)
                    with ThreadPoolExecutor(max_workers=1) as overlap_pool:
                        enrich_future = overlap_pool.submit(
                            build_enrichment_context, ticker.upper(), info["name"]
                        )
                    enrichment = enrich_future.result()

                    live_sections = dict(enrichment.get("sections", {}))
                    data.enrichment_sections = {**data.enrichment_sections, **live_sections}
                    data.financial_summary = (
                        f"{data.financial_core_summary}\n\n{enrichment.get('text', '')}".strip()
                        if enrichment.get("text")
                        else data.financial_core_summary
                    )
                    data.enrichment_warnings = enrichment.get("warnings", [])
                    data.enrichment_sources = enrichment.get("sources", [])
                    data.enrichment_filter_stats = enrichment.get("filter_stats", {})

                    raw_sector = enrichment.get("sector", "")
                    if raw_sector and raw_sector.lower() not in ("n/a", "none"):
                        data.sector = raw_sector
                    raw_industry = enrichment.get("industry", "")
                    if raw_industry and raw_industry.lower() not in ("n/a", "none"):
                        data.industry = raw_industry

                    return data
            except Exception as exc:
                logger.warning("Warehouse read failed, falling back to live: %s", exc)

        logger.info("Fetching SEC data for %s...", ticker.upper())
        info = self.sec_client.resolve_ticker(ticker)
        ticker_upper = ticker.upper()
        # Overlap enrichment (Yahoo/Tavily/peers/etc.) with SEC filings + facts.
        with ThreadPoolExecutor(max_workers=1) as overlap_pool:
            enrich_future = overlap_pool.submit(
                build_enrichment_context, ticker_upper, info["name"]
            )
            filings, company_facts = self.sec_client.fetch_filings_and_facts(ticker)
        enrichment = enrich_future.result()

        raw = {
            "ticker": ticker_upper,
            "company_name": info["name"],
            "cik": info["cik"],
            "recent_filings": filings,
            "company_facts": company_facts,
        }

        logger.info("Parsing XBRL financial data...")
        parser = XBRLParser(raw["company_facts"])
        metrics = parser.compute_metrics()

        if settings.enable_edgartools:
            try:
                metrics = parser.supplement_with_edgartools(raw["ticker"], metrics)
                logger.info("Supplemented metrics via edgartools")
            except (ImportError, AttributeError, ValueError, RuntimeError) as exc:
                logger.warning("edgartools supplement skipped: %s", exc)

        financial_summary = parser.to_summary_text(metrics=metrics)

        quarterly_metrics = parser.compute_quarterly_metrics(quarters=8)
        quarterly_summary = parser.get_quarterly_summary_text(quarterly_metrics)
        margin_trends = parser.get_historical_margins(years=8)
        cash_flow_trends = parser.get_historical_cash_flow(years=8)

        filing_sections: dict = {"mda": "", "risk_factors": "", "business_description": ""}
        if settings.enable_filing_text:
            try:
                tenk_filings = [
                    f for f in raw["recent_filings"]
                    if f.get("form") == "10-K" and f.get("primaryDocument")
                ]
                if tenk_filings:
                    latest_10k = tenk_filings[0]
                    logger.info("Fetching 10-K filing text for narrative extraction...")
                    html = self.sec_client.get_filing_text(
                        raw["ticker"],
                        latest_10k["accessionNumber"],
                        latest_10k["primaryDocument"],
                    )
                    filing_sections = parse_filing_sections(html, ticker=raw["ticker"])
                    section_count = sum(1 for v in filing_sections.values() if v)
                    logger.info("Extracted %d/3 filing sections", section_count)
            except Exception as exc:
                logger.warning("Filing text extraction failed: %s", exc)

        enrichment_sections = dict(enrichment.get("sections", {}))
        if filing_sections.get("mda"):
            enrichment_sections["filing_mda"] = f"=== 10-K MD&A ===\n{filing_sections['mda']}"
        if filing_sections.get("risk_factors"):
            enrichment_sections["filing_risk_factors"] = f"=== 10-K Risk Factors ===\n{filing_sections['risk_factors']}"
        if filing_sections.get("business_description"):
            enrichment_sections["filing_business"] = f"=== 10-K Business Description ===\n{filing_sections['business_description']}"

        segment_data = metrics.pop("_segment_data", None)  # always pop, even if edgartools was skipped
        if segment_data:
            enrichment_sections["segment_data"] = f"=== Revenue Segments ===\n{segment_data}"

        recent_filings = [
            FilingInfo(**{k: f[k] for k in FilingInfo.model_fields if k in f})
            for f in raw["recent_filings"]
        ]

        raw_sector = enrichment.get("sector", "")
        if not raw_sector or raw_sector.lower() in ("n/a", "none"):
            raw_sector = ""
        raw_industry = enrichment.get("industry", "")
        if not raw_industry or raw_industry.lower() in ("n/a", "none"):
            raw_industry = ""

        return AnalysisData(
            ticker=raw["ticker"],
            company_name=raw["company_name"],
            sector=raw_sector,
            industry=raw_industry,
            financial_core_summary=financial_summary,
            financial_summary=(
                f"{financial_summary}\n\n{enrichment.get('text', '')}".strip()
                if enrichment.get("text")
                else financial_summary
            ),
            metrics=metrics,
            recent_filings=recent_filings,
            historical_revenue=parser.get_historical_revenue(years=8),
            historical_net_income=parser.get_historical_net_income(years=8),
            margin_trends=margin_trends,
            cash_flow_trends=cash_flow_trends,
            quarterly_metrics=quarterly_metrics,
            quarterly_summary=quarterly_summary,
            enrichment_sections=enrichment_sections,
            enrichment_warnings=enrichment.get("warnings", []),
            enrichment_sources=enrichment.get("sources", []),
            enrichment_filter_stats=enrichment.get("filter_stats", {}),
        )

    def _get_sector_specialist(self, data: AnalysisData) -> Optional[SectorSpecialistAgent]:
        prompt_path = SECTOR_SPECIALIST_MAP.get(data.sector)
        if not prompt_path or not Path(prompt_path).exists():
            return None
        return SectorSpecialistAgent(
            prompt_file=prompt_path,
            provider=self.provider,
            model=self.synthesis_model,
        )

    async def _run_agent(self, agent, data: AnalysisData) -> AgentReport:
        logger.info("  %s analyzing...", agent.name)
        result = await agent.analyze(data)
        logger.info("  %s complete", agent.name)
        return AgentReport(agent_name=agent.name, analysis=result)

    async def run_phase1(
        self, data: AnalysisData
    ) -> List[AgentReport]:
        """
        Phase 1: Run all agents in parallel.
        Returns list of AgentReport instances.
        """
        logger.info("Phase 1: Running analyst agents in parallel")
        results = await asyncio.gather(
            *[self._run_agent(agent, data) for agent in self.agents]
        )
        return list(results)

    async def run_phase2(
        self,
        ticker: str,
        company_name: str,
        agent_reports: List[AgentReport],
    ) -> str:
        """
        Phase 2: Synthesis agent cross-references all reports.
        Returns the final synthesized analysis.
        """
        logger.info("Phase 2: Synthesis & cross-referencing")

        report_sections = []
        per_report_cap = settings.synthesis_report_max_chars
        for report in agent_reports:
            trimmed_analysis = trim_text(
                report.analysis,
                per_report_cap,
                marker="\n...[agent report trimmed]...",
            )
            report_sections.append(
                f"{'=' * 60}\n"
                f"REPORT FROM: {report.agent_name}\n"
                f"{'=' * 60}\n\n"
                f"{trimmed_analysis}\n"
            )

        combined_reports = "\n\n".join(report_sections)
        combined_reports = trim_text(
            combined_reports,
            settings.synthesis_input_max_chars,
            marker="\n...[synthesis input trimmed]...",
        )
        synthesis_template = load_prompt_file(str(SYNTHESIS_PROMPT_FILE))
        synthesis_system_prompt = render_prompt(
            synthesis_template,
            {"company_name": company_name, "ticker": ticker},
        )

        agent_count = len(agent_reports)
        synthesis_text = await self.provider.generate(
            system=synthesis_system_prompt,
            user=(
                f"Company: {company_name} ({ticker})\n\n"
                f"Below are the {agent_count} analyst reports. "
                "Synthesize them into a unified investment brief.\n\n"
                f"{combined_reports}"
            ),
            model=self.synthesis_model,
            max_tokens=settings.max_synthesis_output_tokens,
        )

        logger.info("Synthesis complete")
        return synthesis_text

    async def run(self, ticker: str) -> AnalysisResult:
        """
        Execute the full two-phase analysis pipeline for a ticker.

        When a sector specialist is available, uses a split-gather pattern:
          Wave 1: specialist + all non-competitive agents in parallel
          Inject specialist briefing into enrichment_sections
          Wave 2: CompetitiveAgent (sees the briefing)
        Otherwise falls back to the single-gather run_phase1.
        """
        data = await asyncio.to_thread(self.prepare_data, ticker)

        specialist = (
            self._get_sector_specialist(data)
            if settings.enable_sector_specialists
            else None
        )

        if specialist:
            non_competitive = [a for a in self.agents if not isinstance(a, CompetitiveAgent)]
            competitive_agents = [a for a in self.agents if isinstance(a, CompetitiveAgent)]

            logger.info("Phase 1 wave 1: Sector specialist + %d agents", len(non_competitive))
            specialist_coro = specialist.analyze(data)
            wave1_coros = [self._run_agent(a, data) for a in non_competitive]
            specialist_result, *wave1_reports = await asyncio.gather(
                specialist_coro, *wave1_coros
            )

            data.enrichment_sections = {
                **data.enrichment_sections,
                "sector_briefing": trim_text(
                    specialist_result, settings.max_sector_briefing_chars
                ),
            }

            logger.info("Phase 1 wave 2: Competitive agent (with sector briefing)")
            wave2_reports = [await self._run_agent(a, data) for a in competitive_agents]
            agent_reports = list(wave1_reports) + list(wave2_reports)
        else:
            agent_reports = await self.run_phase1(data)

        raw_synthesis = await self.run_phase2(
            data.ticker,
            data.company_name,
            agent_reports,
        )

        structured, synthesis = _extract_structured_block(raw_synthesis)

        if structured:
            try:
                health = structured.get("health_scores", {})
                self.sec_client.cache.save_analysis(
                    ticker=data.ticker,
                    verdict=structured.get("verdict", ""),
                    conviction=structured.get("conviction", ""),
                    time_horizon=structured.get("time_horizon", ""),
                    composite_score=health.get("overall"),
                    health_scores=health,
                )
                logger.info("Analysis saved to history")
            except Exception as exc:
                logger.warning("Failed to save analysis history: %s", exc)

        return AnalysisResult(
            ticker=data.ticker,
            company_name=data.company_name,
            agent_reports=agent_reports,
            synthesis=synthesis,
            structured_verdict=structured,
            metrics=data.metrics,
            enrichment_warnings=data.enrichment_warnings,
            enrichment_sources=data.enrichment_sources,
            enrichment_filter_stats=data.enrichment_filter_stats,
        )
