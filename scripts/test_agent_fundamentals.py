#!/usr/bin/env python3
"""
A/B test: EarningsAgent and RiskAgent with vs without cached fundamentals.

Runs each agent twice on the same ticker — once with cached quarterly data
injected, once without — and prints both outputs for comparison.

Usage:
    python scripts/test_agent_fundamentals.py --ticker MSFT
    python scripts/test_agent_fundamentals.py --ticker MSFT --agent earnings
    python scripts/test_agent_fundamentals.py --ticker MSFT --agent risk
"""

import argparse
import asyncio
import sys
import time
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from agents.earnings import EarningsAgent
from agents.risk import RiskAgent
from models import AnalysisData
from quant.fmp_cache import FMPFundamentalCache
from quant.fundamentals import load_cached_fundamentals
from llm.providers import get_provider


def build_test_data(ticker: str) -> AnalysisData:
    """Build AnalysisData with real XBRL data if available, else minimal stub."""
    try:
        from sec.client import SECClient
        from sec.xbrl_parser import XBRLParser

        client = SECClient()
        info = client.resolve_ticker(ticker)
        filings, facts = client.fetch_filings_and_facts(ticker)
        parser = XBRLParser(facts)
        metrics = parser.compute_metrics()
        summary = parser.to_summary_text(metrics=metrics)

        return AnalysisData(
            ticker=ticker.upper(),
            company_name=info["name"],
            financial_core_summary=summary,
            metrics=metrics,
            historical_revenue=parser.get_historical_revenue(years=5),
            historical_net_income=parser.get_historical_net_income(years=5),
            margin_trends=parser.get_historical_margins(years=5),
            cash_flow_trends=parser.get_historical_cash_flow(years=5),
            quarterly_summary=parser.get_quarterly_summary_text(
                parser.compute_quarterly_metrics(quarters=4)
            ),
        )
    except Exception as exc:
        print(f"  (SEC data unavailable: {exc} — using minimal stub)")
        return AnalysisData(
            ticker=ticker.upper(),
            company_name=f"{ticker.upper()} Inc.",
            financial_core_summary=f"Annual 10-K data for {ticker.upper()} not loaded.",
        )


async def run_comparison(ticker: str, agent_filter: str):
    provider = get_provider()
    cache = FMPFundamentalCache()
    cached_fund = load_cached_fundamentals(ticker.upper(), fmp_cache=cache)

    if not cached_fund:
        print(f"ERROR: No cached fundamentals for {ticker}. Run prefetch first.")
        return

    print(f"Cached data keys: {list(cached_fund.keys())}")
    if cached_fund.get("balance_sheet"):
        bs = cached_fund["balance_sheet"]
        print(f"  Balance sheet as of: {bs['as_of_date']}")
    if cached_fund.get("earnings_revision"):
        rev = cached_fund["earnings_revision"]
        print(f"  Earnings revision: {rev['direction']} {rev['revision_pct']:+.1f}%")
    print()

    print("Loading SEC XBRL data...")
    base_data = build_test_data(ticker)
    print(f"  Company: {base_data.company_name}")
    print(f"  Metrics: {len(base_data.metrics)} fields")
    print()

    # Prepare A/B variants
    data_without = deepcopy(base_data)
    data_without.cached_fundamentals = {}

    data_with = deepcopy(base_data)
    data_with.cached_fundamentals = cached_fund

    agents_to_test = []
    if agent_filter in ("all", "earnings"):
        agents_to_test.append(("Earnings", EarningsAgent(provider=provider)))
    if agent_filter in ("all", "risk"):
        agents_to_test.append(("Risk", RiskAgent(provider=provider)))

    for agent_name, agent in agents_to_test:
        print("=" * 80)
        print(f"  {agent_name} Agent — WITHOUT cached fundamentals")
        print("=" * 80)

        t0 = time.time()
        result_without = await agent.analyze(data_without)
        print(f"  ({time.time() - t0:.1f}s)")
        print(result_without)

        print()
        print("=" * 80)
        print(f"  {agent_name} Agent — WITH cached fundamentals")
        print("=" * 80)

        t0 = time.time()
        result_with = await agent.analyze(data_with)
        print(f"  ({time.time() - t0:.1f}s)")
        print(result_with)

        print()
        print("-" * 80)
        print(f"  {agent_name} Agent — CONTEXT DIFF (extra lines with fundamentals)")
        print("-" * 80)
        ctx_without = agent.build_context(data_without)
        ctx_with = agent.build_context(data_with)
        lines_without = set(ctx_without.split("\n"))
        new_lines = [l for l in ctx_with.split("\n") if l not in lines_without and l.strip()]
        for line in new_lines:
            print(f"  + {line}")
        print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", default="MSFT")
    parser.add_argument("--agent", default="all", choices=["all", "earnings", "risk"])
    args = parser.parse_args()

    asyncio.run(run_comparison(args.ticker, args.agent))


if __name__ == "__main__":
    main()
