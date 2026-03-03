"""
Earnings Analyst Agent — JPMorgan style.

Focuses on earnings quality, EPS trajectory, margin analysis,
and forward earnings expectations in the style of JPM equity research.
"""

import json
from typing import Any, Dict

from agents.base import BaseAgent


class EarningsAgent(BaseAgent):
    name = "Earnings Analyst"
    prompt_file = "prompts/earnings.md"
    context_limit_env = "MAX_CONTEXT_EARNINGS_CHARS"
    enrichment_sections = (
        "market_data",
        "external_company",
        "analyst_estimates",
        "peer_comparison",
        "filing_mda",
    )

    system_prompt = """You are a senior equity research analyst at JPMorgan Chase, \
specializing in earnings analysis and quality assessment.

Your analytical framework:
1. EARNINGS TRAJECTORY:
   - Analyze EPS trend over the last several years
   - Revenue growth vs. earnings growth — is there operating leverage?
   - Identify inflection points or acceleration/deceleration patterns

2. MARGIN ANALYSIS:
   - Gross margin trends: pricing power vs. cost pressures
   - Operating margin: SG&A and R&D efficiency
   - Net margin: impact of interest expense, taxes, non-operating items
   - Compare margins to implied industry benchmarks

3. EARNINGS QUALITY:
   - Cash conversion: operating cash flow / net income ratio
   - Are earnings driven by core operations or one-time items?
   - Accruals analysis: growing gap between earnings and cash flow?
   - Revenue recognition red flags

4. FORWARD OUTLOOK:
   - Based on historical trends, what is a reasonable EPS trajectory?
   - What are the key drivers that could push earnings above or below trend?
   - Identify 2-3 catalysts (positive or negative) for near-term earnings

5. EARNINGS VERDICT:
   - Summarize earnings health: STRONG / STABLE / DETERIORATING / WEAK
   - Key earnings risks and opportunities
   - What would change your view?

Write in the concise, data-driven style of a JPM equity research note. \
Lead with conclusions, then support with data."""

    def build_context(self, data: Dict[str, Any]) -> str:
        parts = [
            f"Company: {data.get('company_name', 'Unknown')} ({data.get('ticker', '?')})\n",
        ]

        if "financial_core_summary" in data:
            parts.append(data["financial_core_summary"])

        # Earnings agent needs trend data
        if "historical_revenue" in data:
            parts.append("\n── Historical Revenue ──")
            parts.append(json.dumps(data["historical_revenue"], indent=2))

        if "historical_net_income" in data:
            parts.append("\n── Historical Net Income ──")
            parts.append(json.dumps(data["historical_net_income"], indent=2))

        if "metrics" in data:
            parts.append("\n── Earnings Metrics ──")
            m = data["metrics"]
            for key in [
                "revenue", "gross_profit", "operating_income", "net_income",
                "eps_basic", "eps_diluted",
                "gross_margin", "operating_margin", "net_margin",
                "revenue_growth_yoy", "operating_cash_flow", "free_cash_flow",
                "roe", "roa",
                "revenue_cagr_3y", "revenue_cagr_5y",
                "net_income_cagr_3y", "net_income_cagr_5y",
                "operating_leverage_5y",
            ]:
                if key in m and m[key] is not None:
                    parts.append(f"  {key}: {m[key]}")

        if data.get("margin_trends"):
            parts.append("\n── Historical Margin Trends ──")
            parts.append(json.dumps(data["margin_trends"][:5], indent=2))

        if data.get("quarterly_summary"):
            parts.append(f"\n{data['quarterly_summary']}")

        self.append_enrichment_sections(parts, data)
        return "\n".join(parts)
