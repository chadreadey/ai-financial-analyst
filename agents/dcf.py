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
        "timesfm_eps",
        "fmp_dcf",
        "fmp_analyst_grades",
        "fmp_news",
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

6. MULTIPLES CALIBRATION: Cross-check your DCF fair value against sector trading multiples. \
Most stocks trade at a premium to DCF intrinsic value. If your DCF target is materially \
below current trading multiples, state this explicitly and provide a blended valuation \
(e.g., 70% DCF + 30% comps) as your price target. Never ignore that markets price on \
EV/EBITDA and P/E as primary valuation language.

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
                "free_cash_flow",
                "operating_cash_flow",
                "capex",
                "long_term_debt",
                "cash",
                "stockholders_equity",
                "shares_outstanding",
                "revenue_growth_yoy",
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

        if data.cash_flow_trends:
            parts.append("\n── Historical Cash Flow ──")
            parts.append(json.dumps(data.cash_flow_trends[:5], indent=2))

        if data.quarterly_summary:
            parts.append(f"\n{data.quarterly_summary}")

        comps_block = self._build_comps_context(data)
        if comps_block:
            parts.append(f"\n{comps_block}")

        if settings.enable_wacc_helpers:
            wacc_block = self._build_wacc_context(data)
            if wacc_block:
                parts.append(f"\n{wacc_block}")

        self.append_enrichment_sections(parts, data)
        return "\n".join(parts)

    @staticmethod
    def _build_comps_context(data: AnalysisData) -> Optional[str]:
        """Build a sector multiples context block from available metrics and peer data."""
        m = data.metrics or {}

        # Collect subject company multiples — check both common key naming conventions
        multiples: list[str] = []
        pe = m.get("pe_ratio") or m.get("pe_ttm") or m.get("trailing_pe")
        forward_pe = m.get("forward_pe")
        ev_ebitda = m.get("ev_to_ebitda") or m.get("ev_ebitda")
        ps = m.get("price_to_sales") or m.get("ps_ttm") or m.get("ps_ratio")

        if pe is not None:
            multiples.append(f"  P/E (TTM):      {float(pe):.1f}x")
        if forward_pe is not None:
            multiples.append(f"  Forward P/E:    {float(forward_pe):.1f}x")
        if ev_ebitda is not None:
            multiples.append(f"  EV/EBITDA:      {float(ev_ebitda):.1f}x")
        if ps is not None:
            multiples.append(f"  P/S (TTM):      {float(ps):.1f}x")

        # Summarize peer median multiples from the peer_comparison enrichment section
        peer_lines: list[str] = []
        peer_text = (data.enrichment_sections or {}).get("peer_comparison", "")
        if peer_text:
            import re

            # Extract median PE and EV/EBITDA if present in the peer table text
            for pattern, label in [
                (r"[Mm]edian.*?P/?E[^0-9]*([0-9]+\.?[0-9]*)", "Peer Median P/E"),
                (r"[Mm]edian.*?EV/EBITDA[^0-9]*([0-9]+\.?[0-9]*)", "Peer Median EV/EBITDA"),
            ]:
                m_re = re.search(pattern, peer_text)
                if m_re:
                    peer_lines.append(f"  {label}: {m_re.group(1)}x")

        if not multiples and not peer_lines:
            return None

        lines = ["── Sector Multiples Context ──"]
        if multiples:
            lines.append("Subject Company:")
            lines.extend(multiples)
        if peer_lines:
            lines.append("Peer Benchmarks:")
            lines.extend(peer_lines)
        lines.append(
            "NOTE: Use these multiples in step 6 (MULTIPLES CALIBRATION) to cross-check"
            " your DCF fair value. Provide a blended valuation if warranted."
        )
        return "\n".join(lines)

    @staticmethod
    def _build_wacc_context(data: AnalysisData) -> Optional[str]:
        """Compute and format WACC inputs from FRED yield curve + XBRL balance sheet."""
        try:
            from quant.discount_rate import (
                estimate_wacc,
                get_risk_free_rate,
                get_yield_curve_snapshot,
                format_wacc_context,
            )

            risk_free = get_risk_free_rate(maturity_years=10.0)
            curve = get_yield_curve_snapshot()
            if risk_free is None and curve is None:
                return None
            base_block = format_wacc_context("", risk_free, curve)

            # Try to compute a full WACC from XBRL balance sheet data
            m = data.metrics or {}
            debt = m.get("long_term_debt")
            equity = m.get("stockholders_equity")
            if risk_free and debt is not None and equity is not None and equity > 0:
                total_capital = debt + equity
                debt_ratio = debt / total_capital if total_capital > 0 else 0.3
                # Use sector-average beta=1.0 as default; agents can adjust
                wacc_val, components = estimate_wacc(
                    risk_free_rate=risk_free,
                    beta=1.0,
                    debt_ratio=min(debt_ratio, 0.9),
                )
                base_block += (
                    f"\n  Pre-computed WACC Estimate: {wacc_val * 100:.2f}%"
                    f"\n    (debt_ratio={debt_ratio:.2f}, beta=1.0 default, Rf={risk_free * 100:.2f}%)"
                    f"\n    Cost of Equity: {components['cost_of_equity'] * 100:.2f}%"
                    f"\n    Cost of Debt (after-tax): {components['cost_of_debt_aftertax'] * 100:.2f}%"
                    f"\n  NOTE: Use this WACC as your baseline. Adjust beta only if you have"
                    f" strong evidence the company's systematic risk differs materially from 1.0."
                )

            return base_block
        except Exception:
            return None
