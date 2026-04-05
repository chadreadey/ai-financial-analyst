"""
Risk Analyst Agent — Bridgewater style.

Focuses on systematic risk assessment, macro exposure, balance sheet
vulnerabilities, and tail risk scenarios using Bridgewater's
principles-based analytical framework.
"""

import json
from typing import Any, Dict

from agents.base import BaseAgent
from models import AnalysisData


class RiskAgent(BaseAgent):
    name = "Risk Analyst"
    prompt_file = "prompts/risk.md"
    context_limit_env = "MAX_CONTEXT_RISK_CHARS"
    enrichment_sections = (
        "market_data",
        "external_risks",
        "macro_data",
        "price_history",
        "filing_risk_factors",
        "filing_mda",
        "rag_research",
        "timesfm_price",
        "fmp_institutional",
        "fmp_news",
    )

    system_prompt = """You are a senior risk analyst at Bridgewater Associates, \
applying Ray Dalio's principles-based framework to company risk assessment.

Your analytical framework:
1. BALANCE SHEET RISK: Analyze the company's financial health:
   - Debt levels and debt-to-equity ratio
   - Interest coverage and debt maturity profile
   - Liquidity position (current ratio, cash reserves)
   - Off-balance-sheet risks if apparent

2. EARNINGS QUALITY & SUSTAINABILITY:
   - Gap between reported earnings and cash flow
   - Reliance on non-recurring items
   - Revenue concentration risks
   - Margin sustainability under different scenarios

3. MACRO SENSITIVITY:
   - How exposed is this company to interest rate changes?
   - Currency risk and international exposure
   - Commodity price sensitivity
   - Regulatory and geopolitical risk factors

4. TAIL RISK SCENARIOS: Describe 2-3 realistic adverse scenarios:
   - What could go severely wrong? (recession, disruption, regulation)
   - Quantify potential downside in each scenario
   - How resilient is the balance sheet under stress?

5. RISK SCORE: Assign a risk rating from 1 (very low risk) to 10 (extreme risk) \
across these dimensions:
   - Financial Risk (leverage, liquidity)
   - Operational Risk (margins, concentration)
   - Market Risk (macro sensitivity, cyclicality)
   - Overall Composite Risk

Format as a structured risk report. Be direct about vulnerabilities — \
Bridgewater's culture values radical transparency. Don't sugarcoat risks, \
but also acknowledge genuine strengths in the risk profile."""

    def build_context(self, data: AnalysisData) -> str:
        parts = [
            f"Company: {data.company_name} ({data.ticker})\n",
        ]

        if data.financial_core_summary:
            parts.append(data.financial_core_summary)

        if data.metrics:
            parts.append("\n── Risk-Relevant Metrics ──")
            m = data.metrics
            for key in [
                "total_assets", "total_liabilities", "stockholders_equity",
                "cash", "long_term_debt", "debt_to_equity",
                "operating_cash_flow", "free_cash_flow",
                "net_income", "operating_income", "revenue",
                "roe", "roa", "net_margin", "operating_margin",
            ]:
                if key in m and m[key] is not None:
                    parts.append(f"  {key}: {m[key]}")

        if data.historical_net_income:
            parts.append("\n── Historical Net Income (trend stability) ──")
            parts.append(json.dumps(data.historical_net_income, indent=2))

        if data.cash_flow_trends:
            parts.append("\n── Historical Cash Flow ──")
            parts.append(json.dumps(data.cash_flow_trends[:5], indent=2))

        if data.quarterly_summary:
            parts.append(f"\n{data.quarterly_summary}")

        self.append_enrichment_sections(parts, data)
        return "\n".join(parts)
