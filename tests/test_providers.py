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


class _Msg:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason


class _Block:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


def _provider_with(fake_create):
    from types import SimpleNamespace

    from llm.providers import AnthropicProvider

    p = AnthropicProvider(api_key="test")
    p._client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    return p


@pytest.mark.asyncio
async def test_anthropic_default_model_sonnet_5_5_thinking_off():
    seen = {}

    async def fake_create(**kw):
        seen.update(kw)
        return _Msg([_Block("text", "hi")])

    p = _provider_with(fake_create)
    assert p.default_model == "claude-sonnet-5-5"
    assert await p.generate("s", "u") == "hi"
    assert seen["model"] == "claude-sonnet-5-5"
    assert seen["thinking"] == {"type": "between_tools"}
    assert "temperature" not in seen


@pytest.mark.asyncio
async def test_anthropic_no_text_block_raises_clear_error():
    async def fake_create(**kw):
        return _Msg([_Block("thinking")], stop_reason="max_tokens")

    with pytest.raises(RuntimeError, match="max_tokens"):
        await _provider_with(fake_create).generate("s", "u")
