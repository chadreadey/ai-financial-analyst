"""
LLM provider abstraction and concrete provider implementations.

Supports:
- Anthropic (default, backward-compatible)
- OpenAI-compatible APIs
"""

import os
from abc import ABC, abstractmethod
from typing import Optional

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

DEFAULT_OPENAI_BASE_URL = "https://cbsai.business.columbia.edu/api/v1"


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
        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client = AsyncAnthropic(api_key=key)

    async def generate(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> str:
        message = await self._client.messages.create(
            model=model or self.default_model,
            max_tokens=max_tokens,
            system=system,
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
        key = api_key or os.getenv("OPENAI_API_KEY")
        # Default to the Columbia OpenAI-compatible endpoint to preserve
        # backward behavior from the previous codebase.
        url = base_url or os.getenv("OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL
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
            )
            return response.output_text or ""
        except Exception:
            # Fallback for OpenAI-compatible providers that only implement chat.
            chat = await self._client.chat.completions.create(
                model=selected_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
            )
            return chat.choices[0].message.content or ""


def get_provider(provider_name: Optional[str] = None) -> LLMProvider:
    """
    Return a provider instance from config.

    Priority:
    1) explicit provider_name argument
    2) LLM_PROVIDER environment variable
    3) default: anthropic
    """
    name = (provider_name or os.getenv("LLM_PROVIDER", "anthropic")).strip().lower()
    if name == "anthropic":
        return AnthropicProvider()
    if name == "openai":
        return OpenAIProvider()
    raise ValueError(f"Unsupported LLM_PROVIDER '{name}'. Use 'anthropic' or 'openai'.")

