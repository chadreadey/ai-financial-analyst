"""
Helpers for deterministic context budgeting.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RunBudgets:
    """Context and output budgets for one analysis run.

    Passed explicitly rather than read from ``config.settings``: the settings
    singleton is built once at import, so per-request values written to
    ``os.environ`` never reached it, and mutating it would leak between
    concurrent jobs.
    """

    agent_context_chars: int
    agent_output_tokens: int
    synthesis_report_max_chars: int
    synthesis_input_max_chars: int
    synthesis_output_tokens: int

    @classmethod
    def from_settings(cls, settings) -> "RunBudgets":
        return cls(
            agent_context_chars=settings.max_agent_context_chars,
            agent_output_tokens=settings.max_agent_output_tokens,
            synthesis_report_max_chars=settings.synthesis_report_max_chars,
            synthesis_input_max_chars=settings.synthesis_input_max_chars,
            synthesis_output_tokens=settings.max_synthesis_output_tokens,
        )


def trim_text(text: str, max_chars: int, marker: str = "\n...[trimmed]...") -> str:
    """Trim text to max_chars with a visible marker."""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    keep = max(0, max_chars - len(marker))
    return text[:keep] + marker


def trim_middle(
    text: str,
    max_chars: int,
    tail_chars: int,
    marker: str = "\n...[trimmed]...\n",
) -> str:
    """Trim text to max_chars by cutting the middle, keeping the last tail_chars.

    Agent reports end with their machine-read outputs (structured JSON block,
    SIGNAL_SCORE line), so a prefix-only trim deletes exactly what synthesis is
    told to trust.
    """
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    tail_chars = min(tail_chars, max(0, max_chars - len(marker)))
    head_chars = max(0, max_chars - len(marker) - tail_chars)
    tail = text[len(text) - tail_chars :] if tail_chars else ""
    return text[:head_chars] + marker + tail
