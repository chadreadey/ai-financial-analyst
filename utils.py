"""
Shared utility helpers used across the codebase.
"""

import os
from typing import Optional, Union


def env_flag(name: str, default: bool = True) -> bool:
    """Read a boolean flag from an environment variable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def format_money(value: Optional[Union[float, int]], abbreviate: bool = True) -> str:
    """
    Format a numeric value as a human-readable dollar string.

    Args:
        value: The dollar amount (or None).
        abbreviate: If True, use T/B/M suffixes for large values.
    """
    if value is None:
        return "N/A"
    if not abbreviate:
        return f"${value:,.0f}"
    if abs(value) >= 1e12:
        return f"${value / 1e12:.2f}T"
    if abs(value) >= 1e9:
        return f"${value / 1e9:.2f}B"
    if abs(value) >= 1e6:
        return f"${value / 1e6:.1f}M"
    return f"${value:,.0f}"
