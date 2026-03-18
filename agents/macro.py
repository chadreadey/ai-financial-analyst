"""
Macro Strategist Agent — Goldman Sachs style.

Analyzes the macroeconomic environment and its implications for the
company: rate regime, monetary policy impact, sector positioning,
geopolitical factors, and a TAILWIND / NEUTRAL / HEADWIND verdict.
"""

import json
from typing import Any, Dict

from agents.base import BaseAgent


class MacroAgent(BaseAgent):
    name = "Macro Strategist"
    prompt_file = "prompts/macro.md"
    context_limit_env = "MAX_CONTEXT_MACRO_CHARS"
    enrichment_sections = (
        "macro_data",
        "price_history",
        "filing_mda",
        "peer_comparison",
        "external_industry",
        "rag_research",
    )

    system_prompt = """You are a senior macro strategist at Goldman Sachs Global \
Investment Research. Analyze the macroeconomic environment and its implications \
for the company under review.

Framework:
1. MACRO REGIME — expansion / late-cycle / recession / recovery
2. MONETARY POLICY IMPACT — rate sensitivity, cost of capital, demand effects
3. SECTOR POSITIONING — sector performance in current regime, rotation dynamics
4. GLOBAL & GEOPOLITICAL — trade, FX, commodities, geopolitical risk mapping
5. MACRO VERDICT — TAILWIND / NEUTRAL / HEADWIND with supporting data

Use actual rates and market data. Be specific about transmission mechanisms."""

    def build_context(self, data: Dict[str, Any]) -> str:
        parts = [
            f"Company: {data.get('company_name', 'Unknown')} ({data.get('ticker', '?')})\n",
        ]

        if "financial_core_summary" in data:
            parts.append(data["financial_core_summary"])

        if "metrics" in data:
            parts.append("\n── Macro-Relevant Metrics ──")
            m = data["metrics"]
            for key in [
                "revenue", "revenue_growth_yoy", "revenue_cagr_3y",
                "operating_margin", "net_margin",
                "long_term_debt", "cash", "debt_to_equity",
                "operating_cash_flow", "free_cash_flow",
            ]:
                if key in m and m[key] is not None:
                    parts.append(f"  {key}: {m[key]}")

        if "historical_revenue" in data:
            parts.append("\n── Historical Revenue ──")
            parts.append(json.dumps(data["historical_revenue"][:5], indent=2))

        self.append_enrichment_sections(parts, data)
        return "\n".join(parts)
