"""
Utilities for loading markdown prompts with token replacement.
"""

from pathlib import Path
from typing import Dict


def load_prompt_file(path: str) -> str:
    """Load a UTF-8 prompt file."""
    return Path(path).read_text(encoding="utf-8")


def render_prompt(template: str, data: Dict[str, str]) -> str:
    """
    Replace common prompt tokens with runtime values.

    Supported tokens:
    - [COMPANY NAME]
    - [STOCK NAME]
    - [TICKER]
    """
    company_name = data.get("company_name", "")
    ticker = data.get("ticker", "")
    return (
        template.replace("[COMPANY NAME]", company_name)
        .replace("[STOCK NAME]", company_name)
        .replace("[TICKER]", ticker)
    )

