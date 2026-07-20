"""
Competitive & Sector Analysis Agent — Bain & Company style.

Focuses on competitive positioning, market dynamics, moat analysis,
and sector trends using strategy consulting frameworks.
"""

import json

from agents.base import BaseAgent
from models import AnalysisData


class CompetitiveAgent(BaseAgent):
    name = "Competitive & Sector Analyst"
    prompt_file = "prompts/competitive.md"
    context_limit_env = "MAX_CONTEXT_COMPETITIVE_CHARS"
    enrichment_sections = (
        "sector_briefing",
        "external_sector",
        "external_company",
        "external_industry",
        "peer_comparison",
        "filing_business",
        "segment_data",
        "rag_research",
        "fmp_news",
    )

    system_prompt = """You are a senior partner at Bain & Company, specializing in \
competitive strategy and sector analysis for investor clients.

Your analytical framework:
1. COMPETITIVE POSITIONING:
   - Where does this company sit in its industry? Market leader, challenger, niche?
   - What is the company's core value proposition and differentiation?
   - Assess pricing power based on margin data and trends

2. MOAT ANALYSIS (Sources of Competitive Advantage):
   - Economies of scale (look at revenue scale and margin structure)
   - Switching costs / customer lock-in
   - Network effects
   - Intangible assets (brand, IP, regulatory licenses)
   - Cost advantages
   - Rate each moat source: STRONG / MODERATE / WEAK / ABSENT

3. SECTOR DYNAMICS:
   - What stage is this industry in? (growth, maturity, decline)
   - Key secular trends affecting the sector
   - Regulatory environment and potential changes
   - Technology disruption risks or opportunities

4. PORTER'S FIVE FORCES (brief assessment):
   - Threat of new entrants
   - Bargaining power of suppliers
   - Bargaining power of buyers
   - Threat of substitutes
   - Competitive rivalry intensity

5. STRATEGIC VERDICT:
   - Overall competitive position: DOMINANT / STRONG / AVERAGE / WEAK
   - Key strategic risks (what could erode the moat?)
   - Key strategic opportunities (where can they win?)
   - Is this a company you'd want to own for 5+ years? Why?

Write in the structured, insight-driven style of a Bain strategy deck. \
Use the financial data to support your competitive conclusions — \
margins, growth rates, and R&D spend reveal competitive dynamics."""

    def build_context(self, data: AnalysisData) -> str:
        parts = [
            f"Company: {data.company_name} ({data.ticker})\n",
        ]

        if data.financial_core_summary:
            parts.append(data.financial_core_summary)

        if data.historical_revenue:
            parts.append("\n── Historical Revenue (market share / growth signal) ──")
            parts.append(json.dumps(data.historical_revenue, indent=2))

        if data.metrics:
            parts.append("\n── Competitive-Relevant Metrics ──")
            m = data.metrics
            for key in [
                "revenue",
                "revenue_growth_yoy",
                "revenue_cagr_3y",
                "revenue_cagr_5y",
                "gross_margin",
                "operating_margin",
                "net_margin",
                "gross_profit",
                "operating_income",
                "operating_leverage_5y",
            ]:
                if key in m and m[key] is not None:
                    parts.append(f"  {key}: {m[key]}")

        if data.margin_trends:
            parts.append("\n── Historical Margin Trends ──")
            parts.append(json.dumps(data.margin_trends[:5], indent=2))

        if data.recent_filings:
            parts.append("\n── Recent SEC Filings ──")
            for f in data.recent_filings[:5]:
                parts.append(f"  {f.form} filed {f.filingDate}")

        self.append_enrichment_sections(parts, data)
        return "\n".join(parts)
