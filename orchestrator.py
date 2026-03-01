"""
Orchestrator: Phase 1 fan-out + Phase 2 synthesis.

Phase 1: Run all 5 analyst agents in parallel via asyncio.gather().
Phase 2: Feed all agent outputs to a 6th synthesis agent that
         cross-references findings and produces the final brief.
"""

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from agents import (
    DCFAgent,
    RiskAgent,
    EarningsAgent,
    CompetitiveAgent,
    PatternAgent,
)
from llm import LLMProvider, get_provider
from sec.client import SECClient
from sec.xbrl_parser import XBRLParser


SYNTHESIS_MAX_TOKENS = 6000

SYNTHESIS_SYSTEM_PROMPT = """You are the Chief Investment Officer synthesizing \
research from your team of five specialist analysts. You have received reports from:

1. DCF Analyst (Morgan Stanley) — intrinsic valuation and price target
2. Risk Analyst (Bridgewater) — risk assessment and tail scenarios
3. Earnings Analyst (JPMorgan) — earnings quality and trajectory
4. Competitive Analyst (Bain) — competitive positioning and moat
5. Pattern Analyst (Renaissance Tech) — quantitative pattern recognition

Your job is to:

1. CROSS-REFERENCE: Identify where analysts agree and disagree. \
Flag contradictions (e.g., DCF says undervalued but Risk flags major concerns).

2. SYNTHESIZE: Weigh the evidence across all five lenses to form a unified view.

3. KEY RISKS & CATALYSTS: Distill the top 3 risks and top 3 catalysts \
from across all reports.

4. INVESTMENT VERDICT:
   - Overall rating: STRONG BUY / BUY / HOLD / SELL / STRONG SELL
   - Conviction level: HIGH / MEDIUM / LOW
   - Time horizon: short-term (<1 year) vs. long-term (3-5 years) view
   - One-paragraph executive summary

5. HEALTH SCORE: Assign scores from 1-10 for each dimension:
   - Valuation (from DCF)
   - Risk Profile (from Risk)
   - Earnings Quality (from Earnings)
   - Competitive Position (from Competitive)
   - Quantitative Signals (from Pattern)
   - Overall Health Score (weighted composite)

Be decisive. You're the CIO — your team has done the analysis, \
now you need to make the call. Don't hedge excessively."""


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

    def _prepare_data(self, ticker: str) -> Dict[str, Any]:
        """
        Fetch and parse all SEC data for a ticker.
        Returns the unified data dict that agents consume.
        """
        print(f"  Fetching SEC data for {ticker.upper()}...")
        raw = self.sec_client.fetch_all_data(ticker)

        print("  Parsing XBRL financial data...")
        parser = XBRLParser(raw["company_facts"])

        data = {
            "ticker": raw["ticker"],
            "company_name": raw["company_name"],
            "financial_summary": parser.to_summary_text(),
            "metrics": parser.compute_metrics(),
            "recent_filings": raw["recent_filings"],
            "historical_revenue": parser.get_historical_revenue(years=8),
            "historical_net_income": parser.get_historical_net_income(years=8),
        }
        return data

    async def _run_phase1(
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

    async def _run_phase2(
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
        for agent_name, analysis in agent_reports:
            report_sections.append(
                f"{'=' * 60}\n"
                f"REPORT FROM: {agent_name}\n"
                f"{'=' * 60}\n\n"
                f"{analysis}\n"
            )

        combined_reports = "\n\n".join(report_sections)

        synthesis_text = await self.provider.generate(
            system=SYNTHESIS_SYSTEM_PROMPT,
            user=(
                f"Company: {company_name} ({ticker})\n\n"
                "Below are the five analyst reports. "
                "Synthesize them into a unified investment brief.\n\n"
                f"{combined_reports}"
            ),
            model=self.synthesis_model,
            max_tokens=SYNTHESIS_MAX_TOKENS,
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
        data = self._prepare_data(ticker)

        # Phase 1: parallel agent execution
        agent_reports = await self._run_phase1(data)

        # Phase 2: synthesis
        synthesis = await self._run_phase2(
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
        }
