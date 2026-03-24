"""
Base agent class that all analyst agents inherit from.

Each agent is defined by:
  - A system prompt that sets its analytical persona and methodology
  - A method to build user context from SEC data
  - An async analyze() method that calls the LLM
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from config import settings
from context_budget import trim_text
from llm import LLMProvider, get_provider
from models import AnalysisData
from prompt_loader import load_prompt_file, render_prompt

logger = logging.getLogger(__name__)


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
        self.max_tokens = max_tokens or settings.max_agent_output_tokens

    def build_context(self, data: AnalysisData) -> str:
        parts = [
            f"Company: {data.company_name} ({data.ticker})\n",
        ]

        if data.financial_core_summary:
            parts.append(data.financial_core_summary)

        if data.recent_filings:
            parts.append("\n── Recent SEC Filings ──")
            for f in data.recent_filings[:5]:
                parts.append(
                    f"  {f.form} filed {f.filingDate} "
                    f"(accession: {f.accessionNumber})"
                )

        self.append_enrichment_sections(parts, data)
        return "\n".join(parts)

    def get_system_prompt(self, data: AnalysisData) -> str:
        if self.prompt_file and Path(self.prompt_file).exists():
            template = load_prompt_file(self.prompt_file)
            return render_prompt(
                template,
                {
                    "company_name": data.company_name,
                    "ticker": data.ticker,
                },
            )
        return self.system_prompt

    def get_context_limit(self) -> int:
        if self.context_limit_env:
            val = getattr(settings, self.context_limit_env.lower(), 0)
            if val:
                return val
        return settings.max_agent_context_chars or self.max_context_chars

    def trim_context(self, context: str) -> str:
        return trim_text(context, self.get_context_limit(), marker="\n...[context trimmed]...")

    def append_enrichment_sections(self, parts: list[str], data: AnalysisData) -> None:
        sections = data.enrichment_sections or {}
        for section_key in self.enrichment_sections:
            text = sections.get(section_key)
            if text:
                parts.append("")
                parts.append(text)

    async def analyze(self, data: AnalysisData) -> str:
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
