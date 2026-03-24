"""
Pattern Analysis Agent — Renaissance Technologies style.

Focuses on quantitative pattern recognition in financial data:
trend analysis, mean reversion signals, statistical anomalies,
and data-driven pattern identification.
"""

import json
import logging
from typing import Optional

from agents.base import BaseAgent
from config import settings
from models import AnalysisData

logger = logging.getLogger(__name__)


def _compute_risk_metrics(ticker: str) -> Optional[str]:
    """Compute risk-adjusted return metrics from 2-year daily price history."""
    try:
        import yfinance as yf
        import numpy as np

        hist = yf.Ticker(ticker).history(period="2y", interval="1d")
        if hist.empty or len(hist) < 60:
            return None

        close = hist["Close"]
        returns = close.pct_change().dropna()
        if len(returns) < 60:
            return None

        ann_factor = 252
        mean_ret = float(returns.mean())
        std_ret = float(returns.std())

        sharpe = (mean_ret * ann_factor) / (std_ret * np.sqrt(ann_factor)) if std_ret > 0 else 0.0

        downside = returns[returns < 0]
        downside_std = float(downside.std()) if len(downside) > 1 else std_ret
        sortino = (mean_ret * ann_factor) / (downside_std * np.sqrt(ann_factor)) if downside_std > 0 else 0.0

        cumulative = (1 + returns).cumprod()
        running_max = cumulative.cummax()
        drawdowns = (cumulative - running_max) / running_max
        max_dd = float(drawdowns.min())

        ann_ret = float((cumulative.iloc[-1]) ** (ann_factor / len(returns)) - 1)
        calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0.0

        var_95 = float(np.percentile(returns, 5))

        skew = float(returns.skew())
        kurt = float(returns.kurtosis())

        monthly_returns = close.resample("ME").last().pct_change().dropna()
        best_month = float(monthly_returns.max()) if len(monthly_returns) > 0 else None
        worst_month = float(monthly_returns.min()) if len(monthly_returns) > 0 else None

        lines = [
            "=== Quantitative Risk Metrics ===",
            f"  Sharpe Ratio (ann.): {sharpe:.2f}",
            f"  Sortino Ratio (ann.): {sortino:.2f}",
            f"  Max Drawdown: {max_dd*100:.1f}%",
            f"  Calmar Ratio: {calmar:.2f}",
            f"  Value at Risk (95%): {var_95*100:.2f}% daily",
            f"  Return Skewness: {skew:.2f}",
            f"  Return Kurtosis: {kurt:.2f}",
            f"  Annualized Return: {ann_ret*100:.1f}%",
            f"  Annualized Volatility: {std_ret * np.sqrt(ann_factor)*100:.1f}%",
        ]
        if best_month is not None:
            lines.append(f"  Best Month: {best_month*100:+.1f}%")
        if worst_month is not None:
            lines.append(f"  Worst Month: {worst_month*100:+.1f}%")

        return "\n".join(lines)
    except Exception:
        return None


class PatternAgent(BaseAgent):
    name = "Pattern Analyst"
    prompt_file = "prompts/pattern.md"
    context_limit_env = "MAX_CONTEXT_PATTERN_CHARS"
    enrichment_sections = (
        "market_data",
        "price_history",
        "analyst_estimates",
        "rag_research",
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

    def build_context(self, data: AnalysisData) -> str:
        parts = [
            f"Company: {data.company_name} ({data.ticker})\n",
        ]

        if data.financial_core_summary:
            parts.append(data.financial_core_summary)

        if data.historical_revenue:
            parts.append("\n── Historical Revenue (full series) ──")
            parts.append(json.dumps(data.historical_revenue, indent=2))

        if data.historical_net_income:
            parts.append("\n── Historical Net Income (full series) ──")
            parts.append(json.dumps(data.historical_net_income, indent=2))

        if data.metrics:
            parts.append("\n── Current Metrics (latest snapshot) ──")
            for key, val in data.metrics.items():
                if val is not None:
                    parts.append(f"  {key}: {val}")

        if data.margin_trends:
            parts.append("\n── Historical Margin Trends ──")
            parts.append(json.dumps(data.margin_trends, indent=2))

        if data.cash_flow_trends:
            parts.append("\n── Historical Cash Flow ──")
            parts.append(json.dumps(data.cash_flow_trends, indent=2))

        if data.quarterly_summary:
            parts.append(f"\n{data.quarterly_summary}")

        if settings.enable_quantstats:
            ticker = data.ticker
            if ticker:
                risk_block = _compute_risk_metrics(ticker)
                if risk_block:
                    parts.append(f"\n{risk_block}")

        self.append_enrichment_sections(parts, data)
        return "\n".join(parts)
