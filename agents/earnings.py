"""
Earnings Analyst Agent — JPMorgan style.

Focuses on earnings quality, EPS trajectory, margin analysis,
and forward earnings expectations in the style of JPM equity research.
"""

import json

from agents.base import BaseAgent
from models import AnalysisData


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
        "rag_research",
        "fmp_analyst_grades",
        "fmp_news",
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

    def build_context(self, data: AnalysisData) -> str:
        parts = [
            f"Company: {data.company_name} ({data.ticker})\n",
        ]

        if data.financial_core_summary:
            parts.append(data.financial_core_summary)

        if data.historical_revenue:
            parts.append("\n── Historical Revenue ──")
            parts.append(json.dumps(data.historical_revenue, indent=2))

        if data.historical_net_income:
            parts.append("\n── Historical Net Income ──")
            parts.append(json.dumps(data.historical_net_income, indent=2))

        if data.metrics:
            parts.append("\n── Earnings Metrics ──")
            m = data.metrics
            for key in [
                "revenue",
                "gross_profit",
                "operating_income",
                "net_income",
                "eps_basic",
                "eps_diluted",
                "gross_margin",
                "operating_margin",
                "net_margin",
                "revenue_growth_yoy",
                "operating_cash_flow",
                "free_cash_flow",
                "roe",
                "roa",
                "revenue_cagr_3y",
                "revenue_cagr_5y",
                "net_income_cagr_3y",
                "net_income_cagr_5y",
                "operating_leverage_5y",
            ]:
                if key in m and m[key] is not None:
                    parts.append(f"  {key}: {m[key]}")

        if data.margin_trends:
            parts.append("\n── Historical Margin Trends ──")
            parts.append(json.dumps(data.margin_trends[:5], indent=2))

        if data.quarterly_summary:
            parts.append(f"\n{data.quarterly_summary}")

        # Cached fundamental signals (fresher than 10-K)
        cf = data.cached_fundamentals
        if cf:
            rev = cf.get("earnings_revision")
            if rev:
                if rev.get("is_analyst_consensus"):
                    parts.append(
                        "\n── Analyst Consensus EPS Revision (more recent than SEC filing) ──"
                    )
                    parts.append(f"  Direction: {rev['direction']}")
                    parts.append(
                        f"  Current consensus EPS: ${rev['current_eps']:.3f} ({rev['current_date']}, {rev.get('num_analysts', '?')} analysts)"
                    )
                    parts.append(
                        f"  Prior consensus EPS: ${rev['prior_eps']:.3f} ({rev['prior_date']})"
                    )
                    parts.append(f"  Revision: {rev['revision_pct']:+.1f}%")
                    if rev["direction"] == "UP":
                        parts.append(
                            "  NOTE: Positive analyst revisions are a leading bullish indicator (IC 0.04-0.10)"
                        )
                    elif rev["direction"] == "DOWN":
                        parts.append(
                            "  NOTE: Negative analyst revisions often precede earnings misses"
                        )
                else:
                    parts.append("\n── Sequential Quarterly EPS Trend ──")
                    parts.append(f"  Latest EPS: ${rev['current_eps']:.3f} ({rev['current_date']})")
                    parts.append(
                        f"  Prior quarter EPS: ${rev['prior_eps']:.3f} ({rev['prior_date']})"
                    )
                    parts.append(f"  Change: {rev['revision_pct']:+.1f}%")
                    parts.append(f"  Direction: {rev['direction']}")

            inc = cf.get("latest_income")
            if inc:
                parts.append(f"\n── Latest Quarterly Income (as of {inc['as_of_date']}) ──")
                if inc.get("revenue"):
                    parts.append(f"  Revenue: ${inc['revenue']:,.0f}")
                if inc.get("net_income"):
                    parts.append(f"  Net Income: ${inc['net_income']:,.0f}")
                if inc.get("eps_diluted"):
                    parts.append(f"  EPS (diluted): ${inc['eps_diluted']:.2f}")
                if inc.get("revenue_qoq_pct") is not None:
                    parts.append(f"  Revenue QoQ: {inc['revenue_qoq_pct']:+.1f}%")
                if inc.get("net_income_qoq_pct") is not None:
                    parts.append(f"  Net Income QoQ: {inc['net_income_qoq_pct']:+.1f}%")

        self.append_enrichment_sections(parts, data)
        return "\n".join(parts)
