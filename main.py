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
import sys

from orchestrator import Orchestrator
from report import format_report, save_report
from sec.client import SECClient
from sec.cache import SECCache


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
    orchestrator = Orchestrator(sec_client=sec_client)

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

    # Save if requested
    if args.save or args.output:
        filepath = save_report(result, filepath=args.output)
        print(f"\nReport saved to: {filepath}")

    # Clean up
    cache.close()


if __name__ == "__main__":
    asyncio.run(main())
