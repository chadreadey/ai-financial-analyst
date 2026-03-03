"""
Base agent class that all analyst agents inherit from.

Each agent is defined by:
  - A system prompt that sets its analytical persona and methodology
  - A method to build user context from SEC data
  - An async analyze() method that calls Claude
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

from context_budget import trim_text
from llm import LLMProvider, get_provider
from prompt_loader import load_prompt_file, render_prompt


class BaseAgent:
    """
    Abstract base for all analyst agents.

    Subclasses must set:
      - self.name        : display name for the agent
      - self.system_prompt: the system prompt defining the agent's persona
    And may override:
      - build_context()  : to customize what data goes into the user message
    """

    name: str = "BaseAgent"
    context_limit_env: Optional[str] = None
    system_prompt: str = "You are a financial analyst."
    prompt_file: Optional[str] = None
    max_context_chars: int = 12000
    enrichment_sections: tuple[str, ...] = ()

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ):
        self.provider = provider or get_provider()
        self.model = model or self.provider.default_model
        self.max_tokens = max_tokens or int(os.getenv("MAX_AGENT_OUTPUT_TOKENS", "1200"))

    def build_context(self, data: Dict[str, Any]) -> str:
        """
        Build the user-message context from SEC data.
        Subclasses can override to select specific data slices.

        The default implementation uses `financial_core_summary` (SEC-only
        financials) and appends targeted enrichment sections declared in
        ``self.enrichment_sections``, matching the pattern used by all
        built-in agent subclasses.

        Args:
            data: Dict with keys like 'ticker', 'company_name',
                  'financial_core_summary', 'metrics', 'recent_filings',
                  'historical_revenue', 'historical_net_income'.
        """
        parts = [
            f"Company: {data.get('company_name', 'Unknown')} ({data.get('ticker', '?')})\n",
        ]

        if "financial_core_summary" in data:
            parts.append(data["financial_core_summary"])

        if "recent_filings" in data:
            parts.append("\n── Recent SEC Filings ──")
            for f in data["recent_filings"][:5]:
                parts.append(
                    f"  {f['form']} filed {f['filingDate']} "
                    f"(accession: {f['accessionNumber']})"
                )

        self.append_enrichment_sections(parts, data)
        return "\n".join(parts)

    def get_system_prompt(self, data: Dict[str, Any]) -> str:
        """
        Return the runtime system prompt.
        Prefers markdown prompt files, falls back to inline string.
        """
        if self.prompt_file and Path(self.prompt_file).exists():
            template = load_prompt_file(self.prompt_file)
            return render_prompt(
                template,
                {
                    "company_name": data.get("company_name", ""),
                    "ticker": data.get("ticker", ""),
                },
            )
        return self.system_prompt

    def get_context_limit(self) -> int:
        """Read per-agent context cap, falling back to global/default."""
        if self.context_limit_env:
            raw = os.getenv(self.context_limit_env)
            if raw:
                return int(raw)
        return int(os.getenv("MAX_AGENT_CONTEXT_CHARS", str(self.max_context_chars)))

    def trim_context(self, context: str) -> str:
        return trim_text(context, self.get_context_limit(), marker="\n...[context trimmed]...")

    def append_enrichment_sections(self, parts: list[str], data: Dict[str, Any]) -> None:
        """Append only the enrichment sections this agent needs."""
        sections = data.get("enrichment_sections", {}) or {}
        for section_key in self.enrichment_sections:
            text = sections.get(section_key)
            if text:
                parts.append("")
                parts.append(text)

    async def analyze(self, data: Dict[str, Any]) -> str:
        """
        Run the agent's analysis on the provided data.
        Returns the agent's written analysis as a string.
        """
        context = self.trim_context(self.build_context(data))
        system_prompt = self.get_system_prompt(data)

        return await self.provider.generate(
            system=system_prompt,
            user=(
                "Analyze the following company based on the SEC data provided. "
                f"Provide your professional analysis.\n\n{context}"
            ),
            model=self.model,
            max_tokens=self.max_tokens,
        )
