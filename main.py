#!/usr/bin/env python3
"""
AI Financial Analyst — Entry Point

Usage:
    python main.py AAPL
    python main.py MSFT --save
    python main.py TSLA --output report.txt
"""

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

from orchestrator import Orchestrator
from report import format_report, save_report
from sec.client import SECClient
from sec.cache import SECCache

load_dotenv()

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Financial Analyst — agentic financial analysis powered by SEC data and Claude",
    )
    parser.add_argument(
        "ticker",
        type=str,
        help="Stock ticker symbol to analyze (e.g., AAPL, MSFT, TSLA)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save the report to a file in the reports/ directory",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Save the report to a specific file path",
    )
    parser.add_argument(
        "--user-agent",
        type=str,
        default="AIFinancialAnalyst admin@example.com",
        help="User-Agent string for SEC API requests",
    )
    parser.add_argument(
        "--provider",
        type=str,
        choices=["anthropic", "openai"],
        default=None,
        help="LLM provider override (default: uses LLM_PROVIDER env var, fallback anthropic)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model override (default: provider-specific default model)",
    )
    parser.add_argument(
        "--inspect-context",
        action="store_true",
        help="Build and print context sizing details without calling any LLM",
    )
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=900,
        help="Character count for context preview when --inspect-context is used",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    ticker = args.ticker.upper()

    print(f"\n{'=' * 50}")
    print(f"  AI Financial Analyst")
    print(f"  Analyzing: {ticker}")
    print(f"{'=' * 50}\n")

    # Set up SEC client with caching
    cache = SECCache()
    sec_client = SECClient(user_agent=args.user_agent, cache=cache)

    # Run the orchestrator
    provider_name = args.provider or os.getenv("LLM_PROVIDER")
    orchestrator = Orchestrator(
        sec_client=sec_client,
        llm_provider_name=provider_name,
        model=args.model,
    )

    if args.inspect_context:
        data = orchestrator._prepare_data(ticker)
        print("\n── Context inspection (no LLM calls) ──")
        print(f"Company: {data['company_name']} ({data['ticker']})")
        print(f"financial_summary chars: {len(data.get('financial_summary', ''))}")
        print(f"historical_revenue points: {len(data.get('historical_revenue', []))}")
        print(f"historical_net_income points: {len(data.get('historical_net_income', []))}")
        print(f"metrics count: {len(data.get('metrics', {}))}")
        sections = data.get("enrichment_sections", {}) or {}
        section_sizes = {k: len(v) for k, v in sections.items()}
        print(f"enrichment section sizes: {section_sizes}")
        print(f"enrichment filter stats: {data.get('enrichment_filter_stats', {})}")
        print(f"enrichment sources: {len(data.get('enrichment_sources', []))}")
        print(f"enrichment warnings: {len(data.get('enrichment_warnings', []))}")
        print("\nPer-agent estimated payload sizes:")
        for agent in orchestrator.agents:
            context = agent.build_context(data)
            trimmed = agent.trim_context(context)
            system = agent.get_system_prompt(data)
            print(
                f"  - {agent.name}: "
                f"system={len(system)} chars, context_raw={len(context)} chars, "
                f"context_sent={len(trimmed)} chars, "
                f"context_cap={agent.get_context_limit()} chars"
            )
        preview_chars = max(200, args.preview_chars)
        summary = data.get("financial_summary", "")
        print("\n--- financial_summary preview ---")
        print(summary[:preview_chars])
        print("--- end preview ---")
        cache.close()
        return

    try:
        result = await orchestrator.run(ticker)
    except ValueError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}", file=sys.stderr)
        raise

    # Format and display the report
    report = format_report(result)
    print(f"\n{report}")

    warnings = result.get("enrichment_warnings", [])
    if warnings:
        print("\n[Enrichment warnings]")
        for warning in warnings:
            print(f"  - {warning}")

    # Save if requested
    if args.save or args.output:
        filepath = save_report(result, filepath=args.output)
        print(f"\nReport saved to: {filepath}")

    # Clean up
    cache.close()


if __name__ == "__main__":
    asyncio.run(main())
