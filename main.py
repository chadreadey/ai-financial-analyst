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
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from config import settings
from orchestrator import Orchestrator
from report import format_report, save_report
from sec.client import SECClient
from sec.cache import SECCache

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    logging.basicConfig(
        format="%(levelname)s | %(name)s | %(message)s",
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )


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
    _setup_logging()
    args = parse_args()
    ticker = args.ticker.upper()

    logger.info("AI Financial Analyst")
    logger.info("Analyzing: %s", ticker)

    cache = SECCache()
    sec_client = SECClient(user_agent=args.user_agent, cache=cache)

    provider_name = args.provider or settings.llm_provider
    orchestrator = Orchestrator(
        sec_client=sec_client,
        llm_provider_name=provider_name,
        model=args.model,
    )

    if args.inspect_context:
        data = orchestrator.prepare_data(ticker)
        logger.debug("Context inspection (no LLM calls)")
        logger.debug("Company: %s (%s)", data.company_name, data.ticker)
        logger.debug("financial_summary chars: %d", len(data.financial_summary))
        logger.debug("historical_revenue points: %d", len(data.historical_revenue))
        logger.debug("historical_net_income points: %d", len(data.historical_net_income))
        logger.debug("metrics count: %d", len(data.metrics))
        section_sizes = {k: len(v) for k, v in data.enrichment_sections.items()}
        logger.debug("enrichment section sizes: %s", section_sizes)
        logger.debug("enrichment filter stats: %s", data.enrichment_filter_stats)
        logger.debug("enrichment sources: %d", len(data.enrichment_sources))
        logger.debug("enrichment warnings: %d", len(data.enrichment_warnings))
        logger.debug("Per-agent estimated payload sizes:")
        for agent in orchestrator.agents:
            context = agent.build_context(data)
            trimmed = agent.trim_context(context)
            system = agent.get_system_prompt(data)
            logger.debug(
                "  - %s: system=%d chars, context_raw=%d chars, "
                "context_sent=%d chars, context_cap=%d chars",
                agent.name, len(system), len(context),
                len(trimmed), agent.get_context_limit(),
            )
        preview_chars = max(200, args.preview_chars)
        summary = data.financial_summary
        logger.debug("--- financial_summary preview ---")
        logger.debug(summary[:preview_chars])
        logger.debug("--- end preview ---")
        cache.close()
        return

    try:
        result = await orchestrator.run(ticker)
    except ValueError as e:
        logger.error("Error: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        raise

    result_dict = result.model_dump()
    result_dict["agent_reports"] = [
        (r.agent_name, r.analysis) for r in result.agent_reports
    ]
    report = format_report(result_dict)
    print(f"\n{report}")

    if result.enrichment_warnings:
        print("\n[Enrichment warnings]")
        for warning in result.enrichment_warnings:
            print(f"  - {warning}")

    if args.save or args.output:
        filepath = save_report(result_dict, filepath=args.output)
        logger.info("Report saved to: %s", filepath)

    cache.close()


if __name__ == "__main__":
    asyncio.run(main())
