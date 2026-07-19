"""Tests for ``LiteLLMProvider``."""

import json
from types import SimpleNamespace
from unittest import mock

import pytest

from knowledge_builder.config import ModelConfig
from knowledge_builder.exceptions import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from knowledge_builder.providers.litellm_provider import LiteLLMProvider


def _make_response(content: str):
    """Return a LiteLLM-like response object."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def config():
    return ModelConfig(
        model_name="claude-3-sonnet-20240229",
        provider="anthropic",
        api_key="test-key",
        base_url="https://example.com/v1",
    )


@pytest.fixture
def provider(config):
    return LiteLLMProvider(config)


class TestResolveModelName:
    def test_prefixes_model_when_provider_given(self):
        result = LiteLLMProvider._resolve_model_name("gpt-4", "openai")
        assert result == "openai/gpt-4"

    def test_uses_model_as_is_when_it_contains_slash(self):
        result = LiteLLMProvider._resolve_model_name("anthropic/claude-3", "openai")
        assert result == "anthropic/claude-3"

    def test_uses_model_when_provider_is_none(self):
        result = LiteLLMProvider._resolve_model_name("gpt-4", None)
        assert result == "gpt-4"


class TestExtractContent:
    def test_extracts_string_content(self):
        response = _make_response("hello world")
        assert LiteLLMProvider._extract_content(response) == "hello world"

    def test_raises_when_no_choices(self):
        response = SimpleNamespace(choices=[])
        with pytest.raises(ProviderError, match="no choices"):
            LiteLLMProvider._extract_content(response)

    def test_raises_on_unexpected_shape(self):
        with pytest.raises(ProviderError, match="Unexpected response shape"):
            LiteLLMProvider._extract_content("not a response")


class TestExtractJson:
    def test_parses_plain_json(self):
        payload = {"concept": "authentication", "pages": [5]}
        assert LiteLLMProvider._extract_json(json.dumps(payload)) == payload

    def test_parses_fenced_json(self):
        content = '```json\n{"concept": "auth"}\n```'
        assert LiteLLMProvider._extract_json(content) == {"concept": "auth"}

    def test_parses_json_after_preamble(self):
        content = 'Here is the result:\n{"concept": "auth"}'
        assert LiteLLMProvider._extract_json(content) == {"concept": "auth"}

    def test_raises_on_empty_content(self):
        with pytest.raises(ProviderError, match="empty content"):
            LiteLLMProvider._extract_json("")

    def test_raises_on_invalid_json(self):
        with pytest.raises(ProviderError, match="valid JSON"):
            LiteLLMProvider._extract_json("not json at all")


class TestComplete:
    @pytest.mark.asyncio
    async def test_returns_content(self, provider):
        with mock.patch(
            "knowledge_builder.providers.litellm_provider.litellm.acompletion",
            return_value=_make_response("hello"),
        ) as mock_completion:
            result = await provider.complete([{"role": "user", "content": "hi"}])

        assert result == "hello"
        mock_completion.assert_awaited_once()
        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["model"] == "anthropic/claude-3-sonnet-20240229"
        assert call_kwargs["api_key"] == "test-key"
        assert call_kwargs["api_base"] == "https://example.com/v1"

    @pytest.mark.asyncio
    async def test_complete_json_parses_response(self, provider):
        payload = {"concepts": [{"name": "wizard"}]}
        with mock.patch(
            "knowledge_builder.providers.litellm_provider.litellm.acompletion",
            return_value=_make_response(json.dumps(payload)),
        ):
            result = await provider.complete_json([{"role": "user", "content": "extract"}])
        assert result == payload

    @pytest.mark.asyncio
    async def test_retries_on_transient_error(self, provider):
        from litellm.exceptions import APIError

        with mock.patch(
            "knowledge_builder.providers.litellm_provider.litellm.acompletion",
            side_effect=[APIError(500, "transient", llm_provider="anthropic", model="claude")] * 2
            + [_make_response("success")],
        ) as mock_completion:
            with mock.patch("asyncio.sleep") as mock_sleep:
                result = await provider.complete([{"role": "user", "content": "hi"}], retries=2)

        assert result == "success"
        assert mock_completion.await_count == 3
        mock_sleep.assert_called()

    @pytest.mark.asyncio
    async def test_rate_limit_raises_without_infinite_retry(self, provider):
        from litellm.exceptions import RateLimitError

        with mock.patch(
            "knowledge_builder.providers.litellm_provider.litellm.acompletion",
            side_effect=RateLimitError(
                "rate limited",
                llm_provider="anthropic",
                model="claude",
            ),
        ):
            with pytest.raises(ProviderRateLimitError):
                await provider.complete([{"role": "user", "content": "hi"}], retries=0)

    @pytest.mark.asyncio
    async def test_authentication_error_not_retried(self, provider):
        from litellm.exceptions import AuthenticationError

        with mock.patch(
            "knowledge_builder.providers.litellm_provider.litellm.acompletion",
            side_effect=AuthenticationError(
                "bad key",
                llm_provider="anthropic",
                model="claude",
            ),
        ) as mock_completion:
            with pytest.raises(ProviderAuthenticationError):
                await provider.complete([{"role": "user", "content": "hi"}], retries=3)

        assert mock_completion.await_count == 1

    @pytest.mark.asyncio
    async def test_timeout_error_is_classified(self, provider):
        from litellm.exceptions import Timeout

        with mock.patch(
            "knowledge_builder.providers.litellm_provider.litellm.acompletion",
            side_effect=Timeout(
                "timed out",
                model="claude",
                llm_provider="anthropic",
            ),
        ):
            with pytest.raises(ProviderTimeoutError):
                await provider.complete([{"role": "user", "content": "hi"}], retries=0)


class TestBuildCompletionKwargs:
    def test_includes_optional_parameters(self):
        cfg = ModelConfig(
            model_name="gpt-4o",
            provider="openai",
            api_key="key",
            base_url="https://proxy",
            temperature=0.1,
            max_tokens=1024,
            timeout=30.0,
            extra_headers={"X-Custom": "yes"},
            extra_body={"foo": "bar"},
        )
        provider = LiteLLMProvider(cfg)
        kwargs = provider._build_completion_kwargs(
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.5,
            max_tokens=512,
            timeout=60.0,
        )
        assert kwargs["model"] == "openai/gpt-4o"
        assert kwargs["temperature"] == 0.5
        assert kwargs["max_tokens"] == 512
        assert kwargs["timeout"] == 60.0
        assert kwargs["api_key"] == "key"
        assert kwargs["api_base"] == "https://proxy"
        assert kwargs["extra_headers"] == {"X-Custom": "yes"}
        assert kwargs["extra_body"] == {"foo": "bar"}
