"""
LLM provider abstraction and concrete provider implementations.

Supports:
- Anthropic (default, backward-compatible)
- OpenAI-compatible APIs
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI, APIStatusError, NotFoundError

from config import settings

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract async provider interface."""

    name: str = "base"
    default_model: str = ""

    @abstractmethod
    async def generate(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> str:
        """Generate text for a system + user prompt pair."""


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""

    name = "anthropic"
    default_model = "claude-sonnet-4-20250514"

    def __init__(self, api_key: Optional[str] = None):
        import os
        key = api_key or os.getenv("ANTHROPIC_API_KEY") or settings.anthropic_api_key or None
        self._client = AsyncAnthropic(api_key=key)
        self._prompt_caching = settings.enable_prompt_caching

    async def generate(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> str:
        system_param = (
            [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            if self._prompt_caching
            else system
        )
        message = await self._client.messages.create(
            model=model or self.default_model,
            max_tokens=max_tokens,
            temperature=0.0,
            system=system_param,
            messages=[{"role": "user", "content": user}],
        )
        return message.content[0].text


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible provider."""

    name = "openai"
    default_model = "gpt-4o-mini"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        import os
        # Read live env vars so per-request overrides from jobs.py take effect.
        # settings.* is a frozen Pydantic singleton and won't see runtime changes.
        key = api_key or os.getenv("OPENAI_API_KEY") or settings.openai_api_key or None
        url = base_url or os.getenv("OPENAI_BASE_URL") or settings.openai_base_url
        self._client = AsyncOpenAI(api_key=key, base_url=url)

    async def generate(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> str:
        selected_model = model or self.default_model
        try:
            response = await self._client.responses.create(
                model=selected_model,
                instructions=system,
                input=user,
                max_output_tokens=max_tokens,
                temperature=0.0,
            )
            return response.output_text or ""
        except (NotFoundError, APIStatusError, AttributeError):
            chat = await self._client.chat.completions.create(
                model=selected_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=0.0,
            )
            return chat.choices[0].message.content or ""


def get_provider(provider_name: Optional[str] = None) -> LLMProvider:
    """
    Return a provider instance from config.

    Priority:
    1) explicit provider_name argument
    2) settings.llm_provider
    3) default: anthropic
    """
    name = (provider_name or settings.llm_provider).strip().lower()
    if name == "anthropic":
        return AnthropicProvider()
    if name == "openai":
        return OpenAIProvider()
    raise ValueError(f"Unsupported LLM_PROVIDER '{name}'. Use 'anthropic' or 'openai'.")
