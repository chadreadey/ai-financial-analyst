"""
Pattern Analysis Agent — Renaissance Technologies style.

Focuses on quantitative pattern recognition in financial data:
trend analysis, mean reversion signals, statistical anomalies,
and data-driven pattern identification.
"""

import json
import logging
import os
from typing import Optional

from agents.base import BaseAgent
from config import settings
from models import AnalysisData
from utils import env_flag

logger = logging.getLogger(__name__)


def _format_risk_lines(returns, close) -> str:
    """Format risk metrics from a returns Series and close Series."""
    import numpy as np
    from quant import metrics

    ann_factor = 252
    std_ret = float(returns.std())

    sharpe = metrics.compute_sharpe(returns) or 0.0
    sortino = metrics.compute_sortino(returns) or 0.0

    cumulative = (1 + returns).cumprod()
    max_dd_pct = metrics.compute_max_drawdown(cumulative)
    max_dd = -max_dd_pct / 100  # convert back to negative fraction for display

    ann_ret = float((cumulative.iloc[-1]) ** (ann_factor / len(returns)) - 1)
    calmar = metrics.compute_calmar(ann_ret * 100, max_dd_pct) or 0.0

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


def _compute_risk_metrics(ticker: str) -> Optional[str]:
    """Compute risk-adjusted return metrics from 2-year daily price history."""
    if env_flag("ENABLE_TIINGO") and os.getenv("TIINGO_API_KEY", "").strip():
        try:
            from tiingo_client import TiingoClient
            import pandas as pd
            from datetime import datetime, timedelta

            client = TiingoClient(os.getenv("TIINGO_API_KEY", ""))
            start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
            data = client.get_eod_history(ticker, start)
            if data and len(data) >= 60:
                df = pd.DataFrame(data)
                df["date"] = pd.to_datetime(df["date"]).dt.tz_convert(None)
                df = df.sort_values("date").set_index("date")
                close = df["adjClose"]
                returns = close.pct_change().dropna()
                if len(returns) >= 60:
                    return _format_risk_lines(returns, close)
        except Exception:
            logger.debug("Tiingo risk metrics failed, falling to Yahoo", exc_info=True)

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

        return _format_risk_lines(returns, close)
    except Exception:
        return None


class PatternAgent(BaseAgent):
    name = "Pattern Analyst"
    prompt_file = "prompts/pattern.md"
    context_limit_env = "MAX_CONTEXT_PATTERN_CHARS"
    enrichment_sections = (
        "market_data",
        "price_history",
        "computed_signals",
        "analyst_estimates",
        "rag_research",
        "timesfm_price",
    )

    system_prompt = """You are a quantitative signal analyst at Renaissance Technologies, \
interpreting pre-computed trading signals and fundamental data patterns.

IMPORTANT: All signals are PRE-COMPUTED with exact math and provided in the enrichment \
data. DO NOT recompute them. DO NOT override the scores. Your job is to INTERPRET them.

== SIGNAL HIERARCHY (ranked by validated predictive power) ==

PRIMARY SIGNALS (drive your directional view):
  - OBV trend: Volume-confirmed price trend. The only technical signal with \
    validated alpha. Strong OBV divergence from price is a high-conviction signal.
  - Fundamental patterns: Revenue/earnings trends, margin trajectory, estimate \
    revisions, balance sheet quality. These carry IC 0.04-0.10. Anomalies \
    (>2σ moves in YoY changes) are especially significant.

REGIME CONTEXT (describe the environment, NOT directional):
  - ATR regime: Volatility environment — high ATR = choppy/risky, low ATR = quiet. \
    Use to assess conviction sizing, not direction.
  - RSI: Only meaningful at extremes (<20 or >80) as a reversion warning. \
    Mid-range RSI carries no information.
  - SMA trend, Bollinger %B, Mean reversion Z: Describe what price is doing \
    (trending vs ranging, stretched vs compressed). Use for PATTERN CLASSIFICATION, \
    not for scoring direction. These signals are correlated with each other and \
    have near-zero standalone predictive power.

YOUR TASKS:
1. READ the pre-computed signal vector from the enrichment data.
2. COPY the signal scores exactly into your JSON output — do not modify them.
3. WEIGHT your directional view primarily on OBV and fundamental patterns. \
   Do not let regime context signals override a clear OBV + fundamentals picture.
4. CLASSIFY the pattern: TRENDING, MEAN-REVERTING, BREAKOUT, or RANGE-BOUND. \
   This is where SMA/Bollinger/mean-reversion context is useful.
5. IDENTIFY conflicts between primary signals (OBV vs fundamentals) — these are \
   the conflicts that matter. SMA disagreeing with RSI is noise, not a conflict.

EMIT JSON FIRST (inside ```json block), then 3-5 sentences of commentary.

JSON must include:
- signal_vector: copy from computed signals
- composite_score and composite_direction: copy from computed signals
- actionable: copy from computed signals
- flags: copy + add any fundamental flags
- pattern_classification: your assessment
- fundamental_patterns: your analysis of revenue/earnings/margins
- primary_signal_view: your read of OBV + fundamentals alignment
- key_conflict: the most important PRIMARY signal disagreement
- confidence: HIGH/MEDIUM/LOW based on primary signal agreement

No narrative filler. Numbers only. Focus on what the signals MEAN, not what they ARE."""

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
