"""
Report formatter — takes the orchestrator output and produces
a clean, readable investment brief.
"""

import io
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fpdf import FPDF  # pyright: ignore[reportMissingModuleSource]


DIVIDER = "=" * 70
SECTION_DIVIDER = "-" * 70


def _collapse_spaced_letters(text: str) -> str:
    """
    Fix artifacts like 'r e v e n u e' -> 'revenue' when letters are split.
    """
    pattern = re.compile(r"(?:(?:\b[A-Za-z]\s+){3,}[A-Za-z]\b)")

    def repl(match: re.Match) -> str:
        return re.sub(r"\s+", "", match.group(0))

    return pattern.sub(repl, text)


def _merge_single_char_lines(text: str) -> str:
    """
    Merge pathological outputs where many consecutive lines contain one char.
    """
    lines = text.split("\n")
    out: List[str] = []
    run: List[tuple[str, bool]] = []

    def flush_run() -> None:
        nonlocal run
        if not run:
            return
        if len(run) >= 5:
            merged_parts: List[str] = []
            for idx, (ch, had_leading_space) in enumerate(run):
                if idx > 0 and had_leading_space and ch.isalpha():
                    merged_parts.append(" ")
                merged_parts.append(ch)
            out.append("".join(merged_parts))
        else:
            out.extend(ch for ch, _ in run)
        run = []

    for line in lines:
        stripped = line.strip()
        if len(stripped) == 1 and stripped.isprintable():
            run.append((stripped, line.startswith(" ")))
        else:
            flush_run()
            out.append(line)
    flush_run()
    return "\n".join(out)


def clean_generated_text(text: str) -> str:
    """Normalize model output for cleaner rendering/export."""
    if not text:
        return ""
    cleaned = text.replace("\u2217", "*").replace("\u00a0", " ")
    cleaned = cleaned.replace("\r\n", "\n")
    cleaned = _merge_single_char_lines(cleaned)
    cleaned = _collapse_spaced_letters(cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def clean_result_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy with cleaned synthesis + agent report text."""
    out = dict(result)
    out["synthesis"] = clean_generated_text(result.get("synthesis", ""))
    reports: List[Tuple[str, str]] = result.get("agent_reports", [])
    out["agent_reports"] = [(name, clean_generated_text(text)) for name, text in reports]
    return out


def format_report(result: Dict[str, Any]) -> str:
    """
    Format the full orchestrator result into a readable text report.

    Args:
        result: Dict from Orchestrator.run() with keys:
            ticker, company_name, agent_reports, synthesis, metrics
    """
    cleaned_result = clean_result_payload(result)
    lines: List[str] = []

    # Header
    lines.append(DIVIDER)
    lines.append(
        f"  AI FINANCIAL ANALYST — INVESTMENT BRIEF"
    )
    lines.append(f"  {cleaned_result['company_name']} ({cleaned_result['ticker']})")
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(DIVIDER)

    # Executive synthesis (Phase 2 output) — the most important section
    lines.append("")
    lines.append("SYNTHESIS & INVESTMENT VERDICT")
    lines.append(SECTION_DIVIDER)
    lines.append(cleaned_result["synthesis"])
    lines.append("")

    enrichment_sources = cleaned_result.get("enrichment_sources", [])
    if enrichment_sources:
        lines.append("EXTERNAL ENRICHMENT SOURCES")
        lines.append(SECTION_DIVIDER)
        for source in enrichment_sources:
            lines.append(f"- {source}")
        lines.append("")

    enrichment_warnings = cleaned_result.get("enrichment_warnings", [])
    if enrichment_warnings:
        lines.append("ENRICHMENT WARNINGS")
        lines.append(SECTION_DIVIDER)
        for warning in enrichment_warnings:
            lines.append(f"- {warning}")
        lines.append("")

    # Individual analyst reports
    lines.append(DIVIDER)
    lines.append("  DETAILED ANALYST REPORTS")
    lines.append(DIVIDER)

    agent_reports: List[Tuple[str, str]] = cleaned_result["agent_reports"]
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


def build_pdf_report(result: Dict[str, Any]) -> bytes:
    """Build a human-readable PDF report with basic section formatting."""
    cleaned = clean_result_payload(result)
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 18)
    title = f"{cleaned.get('company_name', 'Company')} ({cleaned.get('ticker', '')})"
    pdf.multi_cell(pdf.epw, 10, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(
        pdf.epw,
        6,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(3)

    def _break_long_words(line: str, max_len: int = 70) -> str:
        words = line.split(" ")
        out: List[str] = []
        for w in words:
            while len(w) > max_len:
                out.append(w[:max_len])
                w = w[max_len:]
            out.append(w)
        return " ".join(out)

    def _strip_markdown(line: str) -> str:
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        line = re.sub(r"\*(.*?)\*", r"\1", line)
        line = re.sub(r"`(.*?)`", r"\1", line)
        return line

    def _write_markdown_block(md_text: str) -> None:
        for raw_line in clean_generated_text(md_text).splitlines():
            line = _strip_markdown(raw_line.strip())
            if not line:
                pdf.ln(3)
                continue
            safe_line = _break_long_words(
                line.encode("latin-1", errors="replace").decode("latin-1")
            )
            if raw_line.strip().startswith("## "):
                pdf.set_font("Helvetica", "B", 13)
                pdf.ln(2)
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(pdf.epw, 7, safe_line, new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 10)
                continue
            if raw_line.strip().startswith("# "):
                pdf.set_font("Helvetica", "B", 15)
                pdf.ln(3)
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(pdf.epw, 8, safe_line, new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 10)
                continue
            if raw_line.strip().startswith(("- ", "* ")):
                safe_line = f"- {safe_line[2:]}" if len(safe_line) > 2 else "- "
            try:
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(pdf.epw, 5, safe_line, new_x="LMARGIN", new_y="NEXT")
            except Exception:
                pdf.set_x(pdf.l_margin)
                pdf.cell(pdf.epw, 5, "[line skipped]", new_x="LMARGIN", new_y="NEXT")

    # Synthesis section
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pdf.epw, 8, "Executive Synthesis", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    _write_markdown_block(cleaned.get("synthesis", ""))

    # Enrichment diagnostics
    sources = cleaned.get("enrichment_sources", [])
    warnings = cleaned.get("enrichment_warnings", [])
    if sources:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 8, "Enrichment Sources", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for source in sources:
            safe = _break_long_words(source.encode("latin-1", errors="replace").decode("latin-1"))
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(pdf.epw, 5, f"- {safe}", new_x="LMARGIN", new_y="NEXT")
    if warnings:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 7, "Enrichment Warnings", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for warning in warnings:
            safe = _break_long_words(warning.encode("latin-1", errors="replace").decode("latin-1"))
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(pdf.epw, 5, f"- {safe}", new_x="LMARGIN", new_y="NEXT")

    # Agent sections
    for agent_name, analysis in cleaned.get("agent_reports", []):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 8, agent_name, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        _write_markdown_block(analysis)

    disclaimer = (
        "Disclaimer: This analysis is AI-generated from SEC filings and should not "
        "be considered financial advice."
    )
    pdf.add_page()
    pdf.set_font("Helvetica", "I", 10)
    for line in disclaimer.splitlines():
        safe_line = line.encode("latin-1", errors="replace").decode("latin-1")
        safe_line = _break_long_words(safe_line)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 5, safe_line, new_x="LMARGIN", new_y="NEXT")

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def save_pdf_report(result: Dict[str, Any], filepath: Optional[str] = None) -> str:
    """Build and save the PDF report. Returns filepath."""
    if filepath is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"reports/{result['ticker']}_{timestamp}.pdf"
    out_path = Path(filepath)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(build_pdf_report(result))
    return str(out_path)


def list_cached_reports(limit: int = 30) -> List[Path]:
    """Return recent cached text reports, newest first."""
    reports_dir = Path("reports")
    if not reports_dir.exists():
        return []
    files = sorted(
        reports_dir.glob("*.txt"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[:limit]
