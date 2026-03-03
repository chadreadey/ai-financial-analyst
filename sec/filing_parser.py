"""
Extract narrative sections from SEC 10-K filing HTML.

Parses Item 1 (Business Description), Item 1A (Risk Factors),
and Item 7 (MD&A) from the raw HTML of a 10-K filing document.
"""

import os
import re
from typing import Dict, Optional

from bs4 import BeautifulSoup

from context_budget import trim_text


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


def parse_filing_sections(html: str) -> Dict[str, str]:
    """
    Extract key 10-K narrative sections from raw filing HTML.

    Returns a dict with keys: 'mda', 'risk_factors', 'business_description'.
    Each value is trimmed to its configured character budget.
    Missing sections return empty strings.
    """
    text = _clean_text(html)

    max_mda = int(os.getenv("MAX_MDA_CHARS", "4000"))
    max_risk = int(os.getenv("MAX_RISK_FACTORS_CHARS", "3000"))
    max_biz = int(os.getenv("MAX_BIZ_DESC_CHARS", "2000"))

    budgets = {
        "mda": max_mda,
        "risk_factors": max_risk,
        "business_description": max_biz,
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
