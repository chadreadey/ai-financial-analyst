"""
Extract narrative sections from SEC 10-K filing HTML.

Primary path: edgartools TenK object (clean, structured access).
Fallback path: BeautifulSoup + regex parsing of raw HTML.

Returns dict with keys: 'mda', 'risk_factors', 'business_description'.
"""

import logging
import re
from typing import Dict, Optional

from bs4 import BeautifulSoup

from config import settings
from context_budget import trim_text

logger = logging.getLogger(__name__)


# ── Legacy regex patterns (fallback path) ─────────────────────

ITEM_PATTERNS = {
    "business_description": [
        re.compile(
            r"item\s*1[.\s]*[-–—]?\s*business",
            re.IGNORECASE,
        ),
    ],
    "risk_factors": [
        re.compile(
            r"item\s*1a[.\s]*[-–—]?\s*risk\s+factors",
            re.IGNORECASE,
        ),
    ],
    "mda": [
        re.compile(
            r"item\s*7[.\s]*[-–—]?\s*management.{0,10}s?\s+discussion",
            re.IGNORECASE,
        ),
    ],
}

NEXT_ITEM_PATTERN = re.compile(
    r"item\s*\d+[a-z]?[.\s]*[-–—]",
    re.IGNORECASE,
)


def _clean_text(html_text: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    soup = BeautifulSoup(html_text, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _find_section_boundaries(text: str, section_key: str) -> Optional[tuple[int, int]]:
    """Find the start and end character positions of a section in cleaned text."""
    patterns = ITEM_PATTERNS.get(section_key, [])
    start_pos = None
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            start_pos = match.start()
            break

    if start_pos is None:
        return None

    search_from = start_pos + 50
    end_pos = len(text)
    for match in NEXT_ITEM_PATTERN.finditer(text[search_from:]):
        candidate = search_from + match.start()
        if candidate - start_pos > 200:
            end_pos = candidate
            break

    return (start_pos, end_pos)


def _parse_filing_sections_legacy(html: str) -> Dict[str, str]:
    """Regex-based extraction from raw filing HTML (fallback)."""
    text = _clean_text(html)

    budgets = {
        "mda": settings.max_mda_chars,
        "risk_factors": settings.max_risk_factors_chars,
        "business_description": settings.max_biz_desc_chars,
    }

    result: Dict[str, str] = {}
    for key, budget in budgets.items():
        bounds = _find_section_boundaries(text, key)
        if bounds:
            raw = text[bounds[0]:bounds[1]].strip()
            result[key] = trim_text(raw, budget, marker="\n...[section trimmed]...")
        else:
            result[key] = ""

    return result


def _extract_edgartools_section(tenk, attr_name: str) -> str:
    """Safely extract a section from a TenK object by attribute name."""
    try:
        val = getattr(tenk, attr_name, None)
        if val is None:
            return ""
        text = str(val).strip()
        text = re.sub(r"\s+", " ", text)
        return text
    except (AttributeError, TypeError, ValueError):
        return ""


def _parse_filing_sections_edgartools(ticker: str) -> Optional[Dict[str, str]]:
    """
    Extract 10-K sections via edgartools.
    Returns None if edgartools is unavailable or fails entirely.
    """
    try:
        from edgar import Company

        company = Company(ticker.upper())
        if company.not_found:
            return None

        tenk = company.latest_tenk
        if tenk is None:
            return None

        risk = _extract_edgartools_section(tenk, "risk_factors")
        biz = _extract_edgartools_section(tenk, "business")

        mda = ""
        for attr in ("mda", "management_discussion", "item7"):
            mda = _extract_edgartools_section(tenk, attr)
            if mda:
                break

        sections: Dict[str, str] = {
            "mda": trim_text(mda, settings.max_mda_chars, marker="\n...[section trimmed]...") if mda else "",
            "risk_factors": trim_text(risk, settings.max_risk_factors_chars, marker="\n...[section trimmed]...") if risk else "",
            "business_description": trim_text(biz, settings.max_biz_desc_chars, marker="\n...[section trimmed]...") if biz else "",
        }

        extracted_count = sum(1 for v in sections.values() if v)
        if extracted_count == 0:
            return None

        return sections
    except (ImportError, AttributeError, ValueError):
        return None


def parse_filing_sections(html: str, ticker: str = "") -> Dict[str, str]:
    """
    Extract key 10-K narrative sections.

    Strategy:
    1. If edgartools is enabled and ticker is provided, try edgartools first.
    2. For any sections edgartools didn't extract, fall back to legacy regex on html.
    3. If edgartools is disabled or fails entirely, use legacy regex for all sections.

    Returns dict with keys: 'mda', 'risk_factors', 'business_description'.
    """
    result: Dict[str, str] = {"mda": "", "risk_factors": "", "business_description": ""}

    if ticker and settings.enable_edgartools:
        edgar_result = _parse_filing_sections_edgartools(ticker)
        if edgar_result is not None:
            result.update(edgar_result)

    missing = [k for k, v in result.items() if not v]
    if missing and html:
        legacy = _parse_filing_sections_legacy(html)
        for key in missing:
            if legacy.get(key):
                result[key] = legacy[key]

    return result
