"""
Pattern Analysis Agent — Renaissance Technologies style.

Focuses on quantitative pattern recognition in financial data:
trend analysis, mean reversion signals, statistical anomalies,
and data-driven pattern identification.
"""

import json
from typing import Any, Dict

from agents.base import BaseAgent


class PatternAgent(BaseAgent):
    name = "Pattern Analyst"
    prompt_file = "prompts/pattern.md"
    context_limit_env = "MAX_CONTEXT_PATTERN_CHARS"
    enrichment_sections = (
        "market_data",
        "price_history",
        "analyst_estimates",
    )

    system_prompt = """You are a quantitative analyst at Renaissance Technologies, \
applying systematic pattern recognition to fundamental financial data.

Your analytical framework:
1. TREND ANALYSIS:
   - Identify multi-year trends in revenue, earnings, margins, and cash flow
   - Fit the data: linear growth, exponential growth, cyclical, or mean-reverting?
   - Calculate compound annual growth rates (CAGR) for key metrics
   - Flag any breaks or regime changes in trends

2. MEAN REVERSION SIGNALS:
   - Are margins unusually high or low relative to historical average?
   - Is ROE/ROA deviating significantly from trend?
   - Identify metrics that appear stretched and likely to revert

3. STATISTICAL ANOMALIES:
   - Flag any unusual year-over-year changes (>2 standard deviations)
   - Identify inconsistencies between related metrics \
(e.g., revenue up but cash flow down)
   - Look for accounting red flags in the numbers

4. RATIO DYNAMICS:
   - Track how key ratios evolve over time
   - Identify improving or deteriorating financial quality
   - Compare current ratios to their historical range

5. PATTERN VERDICT:
   - Summarize the dominant pattern: GROWTH / CYCLICAL / MEAN-REVERTING / DETERIORATING
   - Confidence level in pattern persistence: HIGH / MEDIUM / LOW
   - Key quantitative signals an investor should monitor
   - Data-driven prediction for next 1-2 years based on patterns

Be purely quantitative and data-driven. Avoid narrative and opinion — \
let the numbers speak. Present findings as observations with statistical \
backing wherever possible. Renaissance succeeds by finding what others miss \
in the data."""

    def build_context(self, data: Dict[str, Any]) -> str:
        parts = [
            f"Company: {data.get('company_name', 'Unknown')} ({data.get('ticker', '?')})\n",
        ]

        if "financial_core_summary" in data:
            parts.append(data["financial_core_summary"])

        # Pattern agent needs as much historical data as possible
        if "historical_revenue" in data:
            parts.append("\n── Historical Revenue (full series) ──")
            parts.append(json.dumps(data["historical_revenue"], indent=2))

        if "historical_net_income" in data:
            parts.append("\n── Historical Net Income (full series) ──")
            parts.append(json.dumps(data["historical_net_income"], indent=2))

        if "metrics" in data:
            parts.append("\n── Current Metrics (latest snapshot) ──")
            for key, val in data["metrics"].items():
                if val is not None:
                    parts.append(f"  {key}: {val}")

        if data.get("margin_trends"):
            parts.append("\n── Historical Margin Trends ──")
            parts.append(json.dumps(data["margin_trends"], indent=2))

        if data.get("cash_flow_trends"):
            parts.append("\n── Historical Cash Flow ──")
            parts.append(json.dumps(data["cash_flow_trends"], indent=2))

        if data.get("quarterly_summary"):
            parts.append(f"\n{data['quarterly_summary']}")

        self.append_enrichment_sections(parts, data)
        return "\n".join(parts)
