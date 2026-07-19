"""LiteLLM-backed implementation of the LLM provider interface."""

import asyncio
import json
import logging
import re
from typing import Any, Optional, cast

from knowledge_builder.config import ModelConfig
from knowledge_builder.exceptions import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from knowledge_builder.providers.base import LLMProvider

logger = logging.getLogger(__name__)

try:
    import litellm
    from litellm.exceptions import (
        AuthenticationError as LiteLLMAuthenticationError,
        BadRequestError as LiteLLMBadRequestError,
        RateLimitError as LiteLLMRateLimitError,
        Timeout as LiteLLMTimeout,
    )

    _LITELLM_AVAILABLE = True
except ImportError as _import_error:  # pragma: no cover
    litellm = None  # type: ignore[assignment]
    LiteLLMAuthenticationError = Exception  # type: ignore[misc, assignment]
    LiteLLMBadRequestError = Exception  # type: ignore[misc, assignment]
    LiteLLMRateLimitError = Exception  # type: ignore[misc, assignment]
    LiteLLMTimeout = Exception  # type: ignore[misc, assignment]
    _LITELLM_AVAILABLE = False
    _LITELLM_IMPORT_ERROR = _import_error


class LiteLLMProvider(LLMProvider):
    """Provider-agnostic LLM layer implemented with LiteLLM.

    The class converts the pipeline's ``ModelConfig`` into LiteLLM's
    ``acompletion`` parameters, applies exponential-backoff retries, and
    normalizes responses so callers receive plain strings or parsed JSON.
    """

    def __init__(self, config: ModelConfig):
        if not _LITELLM_AVAILABLE or litellm is None:
            raise ImportError(
                "LiteLLM is required for LiteLLMProvider. " "Install it with: pip install litellm"
            ) from _LITELLM_IMPORT_ERROR
        self.config = config
        self._model = self._resolve_model_name(config.model_name, config.provider)

    @staticmethod
    def _resolve_model_name(model_name: str, provider: Optional[str]) -> str:
        """Return the LiteLLM model identifier.

        If ``model_name`` already contains a provider prefix it is used as-is.
        Otherwise the configured ``provider`` is prepended when available.
        """
        if "/" in model_name:
            return model_name
        if provider:
            return f"{provider}/{model_name}"
        return model_name

    def get_last_usage(self) -> tuple[int, int]:
        """Returns (input_tokens, output_tokens) from the most recent call."""
        u = getattr(self, "_last_usage", None)
        if u is None:
            return 0, 0
        return getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0

    def _build_completion_kwargs(
        self,
        messages: list[dict[str, Any]],
        temperature: Optional[float],
        max_tokens: Optional[int],
        timeout: Optional[float],
    ) -> dict[str, Any]:
        """Build the keyword arguments passed to ``litellm.acompletion``."""
        effective_temperature = self.config.temperature if temperature is None else temperature
        effective_max_tokens = self.config.max_tokens if max_tokens is None else max_tokens
        effective_timeout = self.config.timeout if timeout is None else timeout

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": effective_temperature,
        }
        if self.config.api_key is not None:
            kwargs["api_key"] = self.config.api_key
        if self.config.base_url is not None:
            kwargs["api_base"] = self.config.base_url
        if effective_max_tokens is not None:
            kwargs["max_tokens"] = effective_max_tokens
        if effective_timeout is not None:
            kwargs["timeout"] = effective_timeout
        if self.config.extra_headers is not None:
            kwargs["extra_headers"] = self.config.extra_headers
        if self.config.extra_body:
            kwargs["extra_body"] = self.config.extra_body
        return kwargs

    @staticmethod
    def _extract_content(response: Any) -> str:
        """Pull the text content out of a LiteLLM ``ModelResponse``."""
        try:
            choices = response.choices
        except AttributeError as exc:
            raise ProviderError(f"Unexpected response shape from LiteLLM: {response!r}") from exc

        if not choices:
            raise ProviderError("LiteLLM response contains no choices.")

        message = choices[0].message
        content = message.content if message.content is not None else ""
        return content

    @staticmethod
    def _extract_json(content: str) -> dict[str, Any]:
        """Parse JSON from an LLM response, tolerating markdown fences."""
        if not content or not content.strip():
            raise ProviderError("LLM returned empty content; expected JSON.")

        stripped = content.strip()

        # Try direct parse first.
        try:
            return cast(dict[str, Any], json.loads(stripped))
        except json.JSONDecodeError:
            pass

        # Look for a fenced JSON block.
        fence_pattern = re.compile(
            r"```(?:json)?\s*(.*?)\s*```",
            re.DOTALL | re.IGNORECASE,
        )
        match = fence_pattern.search(stripped)
        if match:
            try:
                return cast(dict[str, Any], json.loads(match.group(1).strip()))
            except json.JSONDecodeError as exc:
                raise ProviderError(f"Failed to parse JSON inside markdown fence: {exc}") from exc

        # As a last resort, try to locate the first JSON object/array.
        object_start = stripped.find("{")
        array_start = stripped.find("[")
        starts = [(object_start, "object"), (array_start, "array")]
        valid_starts = [(idx, kind) for idx, kind in starts if idx != -1]
        if valid_starts:
            start_idx, _ = min(valid_starts, key=lambda x: x[0])
            try:
                return cast(dict[str, Any], json.loads(stripped[start_idx:]))
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    f"Failed to parse JSON from LLM response: {exc}\nContent: {stripped[:500]}"
                ) from exc

        raise ProviderError(f"LLM response did not contain valid JSON. Content: {stripped[:500]}")

    @staticmethod
    def _classify_exception(exc: Exception) -> ProviderError:
        """Map LiteLLM exceptions to pipeline-specific provider errors."""
        if isinstance(exc, LiteLLMRateLimitError):
            return ProviderRateLimitError(str(exc))
        if isinstance(exc, LiteLLMAuthenticationError):
            return ProviderAuthenticationError(str(exc))
        if isinstance(exc, LiteLLMTimeout):
            return ProviderTimeoutError(str(exc))
        if isinstance(exc, LiteLLMBadRequestError):
            return ProviderError(f"Bad request to provider: {exc}")
        return ProviderError(f"LLM provider call failed: {exc}")

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        retries: int = 3,
    ) -> str:
        """Call LiteLLM and return raw text content with exponential backoff."""
        kwargs = self._build_completion_kwargs(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

        last_error: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                response = await litellm.acompletion(**kwargs)
                self._last_usage = getattr(response, "usage", None)
                return self._extract_content(response)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                classified = self._classify_exception(exc)
                if isinstance(classified, ProviderAuthenticationError):
                    # Auth errors are not retryable.
                    raise classified from exc
                if attempt == retries:
                    raise classified from exc

                backoff = 2**attempt
                logger.warning(
                    "LiteLLM call failed (attempt %d/%d), retrying in %ds: %s",
                    attempt + 1,
                    retries + 1,
                    backoff,
                    exc,
                )
                await asyncio.sleep(backoff)

        # Should never be reached, but keeps type checkers happy.
        raise ProviderError(f"LLM provider call failed after {retries} retries: {last_error}")

    async def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        retries: int = 3,
    ) -> dict[str, Any]:
        """Call LiteLLM and parse the response as JSON."""
        content = await self.complete(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            retries=retries,
        )
        return self._extract_json(content)
