"""
DCF Analyst Agent — Morgan Stanley style.

Focuses on intrinsic valuation through discounted cash flow analysis,
free cash flow projections, WACC estimation, and fair-value derivation.
"""

import json
from typing import Any, Dict

from agents.base import BaseAgent


class DCFAgent(BaseAgent):
    name = "DCF Analyst"

    system_prompt = """You are a senior equity research analyst at Morgan Stanley, \
specializing in Discounted Cash Flow (DCF) valuation.

Your analytical framework:
1. REVENUE PROJECTION: Analyze historical revenue trends, growth rates, and market \
dynamics to project 5-year forward revenues. Be explicit about your growth assumptions.

2. FREE CASH FLOW: Derive projected free cash flows from revenue projections. \
Consider operating margins, capex requirements, working capital changes, and \
tax rates. Use historical patterns as your baseline.

3. WACC ESTIMATION: Estimate the weighted average cost of capital. Consider:
   - Risk-free rate (current 10-year Treasury)
   - Equity risk premium
   - Beta (systematic risk)
   - Cost of debt (from the company's actual borrowing rates)
   - Capital structure (debt/equity mix from balance sheet)

4. TERMINAL VALUE: Calculate terminal value using a perpetuity growth model. \
Justify your terminal growth rate assumption (typically 2-3% for mature companies).

5. FAIR VALUE: Derive per-share intrinsic value. Compare to current trading price \
and state your implied upside/downside.

Format your analysis with clear sections, show your key assumptions in a table, \
and provide a sensitivity analysis on WACC and terminal growth rate. \
End with a clear BUY / HOLD / SELL recommendation with a price target.

Be rigorous but concise. Use actual numbers from the provided financials."""

    def build_context(self, data: Dict[str, Any]) -> str:
        parts = [
            f"Company: {data.get('company_name', 'Unknown')} ({data.get('ticker', '?')})\n",
        ]

        if "financial_summary" in data:
            parts.append(data["financial_summary"])

        # DCF agent needs historical trends for projection
        if "historical_revenue" in data:
            parts.append("\n── Historical Revenue ──")
            parts.append(json.dumps(data["historical_revenue"], indent=2))

        if "historical_net_income" in data:
            parts.append("\n── Historical Net Income ──")
            parts.append(json.dumps(data["historical_net_income"], indent=2))

        if "metrics" in data:
            parts.append("\n── Key Metrics ──")
            m = data["metrics"]
            for key in [
                "free_cash_flow", "operating_cash_flow", "capex",
                "long_term_debt", "cash", "stockholders_equity",
                "shares_outstanding", "revenue_growth_yoy",
            ]:
                if key in m and m[key] is not None:
                    parts.append(f"  {key}: {m[key]}")

        return "\n".join(parts)
