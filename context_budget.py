"""
Helpers for deterministic context budgeting.
"""


def trim_text(text: str, max_chars: int, marker: str = "\n...[trimmed]...") -> str:
    """Trim text to max_chars with a visible marker."""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    keep = max(0, max_chars - len(marker))
    return text[:keep] + marker
