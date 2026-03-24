"""
DCF Analyst Agent — Morgan Stanley style.

Focuses on intrinsic valuation through discounted cash flow analysis,
free cash flow projections, WACC estimation, and fair-value derivation.
"""

import json
import logging
from typing import Optional

from agents.base import BaseAgent
from config import settings
from models import AnalysisData

logger = logging.getLogger(__name__)


class DCFAgent(BaseAgent):
    name = "DCF Analyst"
    prompt_file = "prompts/dcf.md"
    context_limit_env = "MAX_CONTEXT_DCF_CHARS"
    enrichment_sections = (
        "market_data",
        "external_company",
        "analyst_estimates",
        "price_history",
        "macro_data",
        "peer_comparison",
        "filing_mda",
        "segment_data",
        "rag_research",
    )

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
            parts.append("\n── Key Metrics ──")
            m = data.metrics
            for key in [
                "free_cash_flow", "operating_cash_flow", "capex",
                "long_term_debt", "cash", "stockholders_equity",
                "shares_outstanding", "revenue_growth_yoy",
                "revenue_cagr_3y", "revenue_cagr_5y",
                "net_income_cagr_3y", "net_income_cagr_5y",
                "operating_leverage_5y",
            ]:
                if key in m and m[key] is not None:
                    parts.append(f"  {key}: {m[key]}")

        if data.margin_trends:
            parts.append("\n── Historical Margin Trends ──")
            parts.append(json.dumps(data.margin_trends[:5], indent=2))

        if data.cash_flow_trends:
            parts.append("\n── Historical Cash Flow ──")
            parts.append(json.dumps(data.cash_flow_trends[:5], indent=2))

        if data.quarterly_summary:
            parts.append(f"\n{data.quarterly_summary}")

        if settings.enable_wacc_helpers:
            wacc_block = self._build_wacc_context()
            if wacc_block:
                parts.append(f"\n{wacc_block}")

        self.append_enrichment_sections(parts, data)
        return "\n".join(parts)

    @staticmethod
    def _build_wacc_context() -> Optional[str]:
        """Compute and format WACC inputs from FRED yield curve data."""
        try:
            from quant.discount_rate import (
                get_risk_free_rate,
                get_yield_curve_snapshot,
                format_wacc_context,
            )

            risk_free = get_risk_free_rate(maturity_years=10.0)
            curve = get_yield_curve_snapshot()
            if risk_free is None and curve is None:
                return None
            return format_wacc_context("", risk_free, curve)
        except Exception:
            return None
