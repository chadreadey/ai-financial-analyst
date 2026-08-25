"""
Sector Specialist Agent -- produces a short sector briefing that feeds
into the Competitive Agent's context via the split-gather pattern.
"""

import json
from typing import Optional

from agents.base import BaseAgent
from config import settings
from llm import LLMProvider
from models import AnalysisData


class SectorSpecialistAgent(BaseAgent):
    name = "Sector Specialist"
    context_limit_env = "MAX_CONTEXT_COMPETITIVE_CHARS"
    enrichment_sections = (
        "external_sector",
        "peer_comparison",
        "external_industry",
        "filing_business",
        "segment_data",
    )

    def __init__(
        self,
        prompt_file: str,
        provider: Optional[LLMProvider] = None,
        model: Optional[str] = None,
    ):
        super().__init__(
            provider=provider,
            model=model,
            max_tokens=settings.max_sector_briefing_tokens,
        )
        self.prompt_file = prompt_file

    def build_context(self, data: AnalysisData) -> str:
        parts = [
            f"Company: {data.company_name} ({data.ticker})",
            f"Sector: {data.sector}",
            f"Industry: {data.industry}",
            "",
        ]

        if data.financial_core_summary:
            parts.append(data.financial_core_summary)

        if data.metrics:
            parts.append("\n── Sector-Relevant Metrics ──")
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
                "roe",
                "roa",
                "roic",
            ]:
                if key in m and m[key] is not None:
                    parts.append(f"  {key}: {m[key]}")

        if data.margin_trends:
            parts.append("\n── Margin Trends ──")
            parts.append(json.dumps(data.margin_trends[:5], indent=2))

        self.append_enrichment_sections(parts, data)
        return "\n".join(parts)
