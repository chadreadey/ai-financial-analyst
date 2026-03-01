"""
Base agent class that all analyst agents inherit from.

Each agent is defined by:
  - A system prompt that sets its analytical persona and methodology
  - A method to build user context from SEC data
  - An async analyze() method that calls Claude
"""

from typing import Any, Dict, Optional

from llm import LLMProvider, get_provider


DEFAULT_MODEL = None
DEFAULT_MAX_TOKENS = 4096


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
    system_prompt: str = "You are a financial analyst."

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        model: Optional[str] = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        self.provider = provider or get_provider()
        self.model = model or self.provider.default_model
        self.max_tokens = max_tokens

    def build_context(self, data: Dict[str, Any]) -> str:
        """
        Build the user-message context from SEC data.
        Subclasses can override to select specific data slices.

        Args:
            data: Dict with keys like 'ticker', 'company_name',
                  'financial_summary', 'metrics', 'recent_filings',
                  'historical_revenue', 'historical_net_income'.
        """
        parts = [
            f"Company: {data.get('company_name', 'Unknown')} ({data.get('ticker', '?')})\n",
        ]

        if "financial_summary" in data:
            parts.append(data["financial_summary"])

        if "recent_filings" in data:
            parts.append("\n── Recent SEC Filings ──")
            for f in data["recent_filings"][:5]:
                parts.append(
                    f"  {f['form']} filed {f['filingDate']} "
                    f"(accession: {f['accessionNumber']})"
                )

        return "\n".join(parts)

    async def analyze(self, data: Dict[str, Any]) -> str:
        """
        Run the agent's analysis on the provided data.
        Returns the agent's written analysis as a string.
        """
        context = self.build_context(data)

        return await self.provider.generate(
            system=self.system_prompt,
            user=(
                "Analyze the following company based on the SEC data provided. "
                f"Provide your professional analysis.\n\n{context}"
            ),
            model=self.model,
            max_tokens=self.max_tokens,
        )
