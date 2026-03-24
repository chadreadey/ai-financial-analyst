"""Tests for LLM provider abstraction."""

import pytest

from llm.providers import (
    AnthropicProvider,
    LLMProvider,
    OpenAIProvider,
    get_provider,
)


def test_get_provider_anthropic():
    provider = get_provider("anthropic")
    assert isinstance(provider, AnthropicProvider)
    assert provider.name == "anthropic"


def test_get_provider_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    provider = get_provider("openai")
    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "openai"


def test_get_provider_case_insensitive():
    provider = get_provider("  Anthropic  ")
    assert isinstance(provider, AnthropicProvider)


def test_get_provider_unknown_raises():
    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        get_provider("mistral")


def test_provider_is_abstract():
    assert hasattr(LLMProvider, "generate")


@pytest.mark.asyncio
async def test_fake_provider_generate(fake_provider):
    result = await fake_provider.generate(
        system="You are helpful.",
        user="Say hello.",
    )
    assert result == "Test analysis output."
