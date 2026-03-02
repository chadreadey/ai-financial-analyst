"""
Orchestrator: Phase 1 fan-out + Phase 2 synthesis.

Phase 1: Run all 5 analyst agents in parallel via asyncio.gather().
Phase 2: Feed all agent outputs to a 6th synthesis agent that
         cross-references findings and produces the final brief.
"""

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agents import (
    DCFAgent,
    RiskAgent,
    EarningsAgent,
    CompetitiveAgent,
    PatternAgent,
)
from context_budget import trim_text
from llm import LLMProvider, get_provider
from market_enrichment import build_enrichment_context
from prompt_loader import load_prompt_file, render_prompt
from sec.client import SECClient
from sec.xbrl_parser import XBRLParser


SYNTHESIS_PROMPT_FILE = Path("prompts/synthesis.md")


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

    def prepare_data(self, ticker: str) -> Dict[str, Any]:
        """
        Fetch and parse all SEC data for a ticker.
        Returns the unified data dict that agents consume.
        """
        print(f"  Fetching SEC data for {ticker.upper()}...")
        raw = self.sec_client.fetch_all_data(ticker)

        print("  Parsing XBRL financial data...")
        parser = XBRLParser(raw["company_facts"])
        print("  Building optional market/research enrichment...")
        enrichment = build_enrichment_context(raw["ticker"], raw["company_name"])
        metrics = parser.compute_metrics()
        financial_summary = parser.to_summary_text(metrics=metrics)

        data = {
            "ticker": raw["ticker"],
            "company_name": raw["company_name"],
            "financial_core_summary": financial_summary,
            "financial_summary": (
                f"{financial_summary}\n\n{enrichment.get('text', '')}".strip()
                if enrichment.get("text")
                else financial_summary
            ),
            "metrics": metrics,
            "recent_filings": raw["recent_filings"],
            "historical_revenue": parser.get_historical_revenue(years=8),
            "historical_net_income": parser.get_historical_net_income(years=8),
            "enrichment_sections": enrichment.get("sections", {}),
            "enrichment_warnings": enrichment.get("warnings", []),
            "enrichment_sources": enrichment.get("sources", []),
            "enrichment_filter_stats": enrichment.get("filter_stats", {}),
        }
        return data

    async def run_phase1(
        self, data: Dict[str, Any]
    ) -> List[Tuple[str, str]]:
        """
        Phase 1: Run all agents in parallel.
        Returns list of (agent_name, analysis_text) tuples.
        """
        print("\n── Phase 1: Running analyst agents in parallel ──")

        async def run_agent(agent):
            print(f"  → {agent.name} analyzing...")
            result = await agent.analyze(data)
            print(f"  ✓ {agent.name} complete")
            return (agent.name, result)

        results = await asyncio.gather(
            *[run_agent(agent) for agent in self.agents]
        )
        return list(results)

    async def run_phase2(
        self,
        ticker: str,
        company_name: str,
        agent_reports: List[Tuple[str, str]],
    ) -> str:
        """
        Phase 2: Synthesis agent cross-references all reports.
        Returns the final synthesized analysis.
        """
        print("\n── Phase 2: Synthesis & cross-referencing ──")

        # Build the synthesis prompt with all agent reports
        report_sections = []
        per_report_cap = int(os.getenv("SYNTHESIS_REPORT_MAX_CHARS", "3200"))
        for agent_name, analysis in agent_reports:
            trimmed_analysis = trim_text(
                analysis,
                per_report_cap,
                marker="\n...[agent report trimmed]...",
            )
            report_sections.append(
                f"{'=' * 60}\n"
                f"REPORT FROM: {agent_name}\n"
                f"{'=' * 60}\n\n"
                f"{trimmed_analysis}\n"
            )

        combined_reports = "\n\n".join(report_sections)
        combined_reports = trim_text(
            combined_reports,
            int(os.getenv("SYNTHESIS_INPUT_MAX_CHARS", "14000")),
            marker="\n...[synthesis input trimmed]...",
        )
        synthesis_template = load_prompt_file(str(SYNTHESIS_PROMPT_FILE))
        synthesis_system_prompt = render_prompt(
            synthesis_template,
            {"company_name": company_name, "ticker": ticker},
        )

        synthesis_text = await self.provider.generate(
            system=synthesis_system_prompt,
            user=(
                f"Company: {company_name} ({ticker})\n\n"
                "Below are the five analyst reports. "
                "Synthesize them into a unified investment brief.\n\n"
                f"{combined_reports}"
            ),
            model=self.synthesis_model,
            max_tokens=int(os.getenv("MAX_SYNTHESIS_OUTPUT_TOKENS", "1500")),
        )

        print("  ✓ Synthesis complete")
        return synthesis_text

    async def run(self, ticker: str) -> Dict[str, Any]:
        """
        Execute the full two-phase analysis pipeline for a ticker.

        Returns:
            Dict with keys:
                - ticker
                - company_name
                - agent_reports: list of (name, analysis) tuples
                - synthesis: the final cross-referenced brief
                - metrics: raw computed metrics
        """
        # Fetch and prepare data (sync — must complete before agents run)
        data = self.prepare_data(ticker)

        # Phase 1: parallel agent execution
        agent_reports = await self.run_phase1(data)

        # Phase 2: synthesis
        synthesis = await self.run_phase2(
            data["ticker"],
            data["company_name"],
            agent_reports,
        )

        return {
            "ticker": data["ticker"],
            "company_name": data["company_name"],
            "agent_reports": agent_reports,
            "synthesis": synthesis,
            "metrics": data["metrics"],
            "enrichment_warnings": data.get("enrichment_warnings", []),
            "enrichment_sources": data.get("enrichment_sources", []),
            "enrichment_filter_stats": data.get("enrichment_filter_stats", {}),
        }
