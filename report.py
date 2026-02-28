"""
Report formatter — takes the orchestrator output and produces
a clean, readable investment brief.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


DIVIDER = "=" * 70
SECTION_DIVIDER = "-" * 70


def format_report(result: Dict[str, Any]) -> str:
    """
    Format the full orchestrator result into a readable text report.

    Args:
        result: Dict from Orchestrator.run() with keys:
            ticker, company_name, agent_reports, synthesis, metrics
    """
    lines: List[str] = []

    # Header
    lines.append(DIVIDER)
    lines.append(
        f"  AI FINANCIAL ANALYST — INVESTMENT BRIEF"
    )
    lines.append(f"  {result['company_name']} ({result['ticker']})")
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(DIVIDER)

    # Executive synthesis (Phase 2 output) — the most important section
    lines.append("")
    lines.append("SYNTHESIS & INVESTMENT VERDICT")
    lines.append(SECTION_DIVIDER)
    lines.append(result["synthesis"])
    lines.append("")

    # Individual analyst reports
    lines.append(DIVIDER)
    lines.append("  DETAILED ANALYST REPORTS")
    lines.append(DIVIDER)

    agent_reports: List[Tuple[str, str]] = result["agent_reports"]
    for agent_name, analysis in agent_reports:
        lines.append("")
        lines.append(f"  [{agent_name}]")
        lines.append(SECTION_DIVIDER)
        lines.append(analysis)
        lines.append("")

    # Footer
    lines.append(DIVIDER)
    lines.append(
        "  Disclaimer: This analysis is AI-generated from SEC filings and "
        "should not be considered financial advice. Always consult a qualified "
        "financial advisor before making investment decisions."
    )
    lines.append(DIVIDER)

    return "\n".join(lines)


def save_report(result: Dict[str, Any], filepath: Optional[str] = None) -> str:
    """
    Format and save the report to a file.
    Returns the filepath used.
    """
    report_text = format_report(result)

    if filepath is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"reports/{result['ticker']}_{timestamp}.txt"

    # Ensure directory exists
    import os
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)

    with open(filepath, "w") as f:
        f.write(report_text)

    return filepath
