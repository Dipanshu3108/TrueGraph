"""Abstract provider interface for the LLM layer."""

from abc import ABC, abstractmethod
from typing import Any, Optional


class LLMProvider(ABC):
    """Provider-agnostic interface for LLM completion calls.

    Concrete implementations (e.g. :class:`LiteLLMProvider`) hide provider
    specifics behind ``complete`` and ``complete_json``. The rest of the
    pipeline only depends on this interface.
    """

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        retries: int = 3,
    ) -> str:
        """Call the LLM and return the raw text content of the response.

        Args:
            messages: OpenAI-style chat messages.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in the response.
            timeout: Per-call timeout in seconds.
            retries: Number of retries on transient failures.

        Returns:
            The raw response content.
        """
        ...

    @abstractmethod
    async def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        retries: int = 3,
    ) -> dict[str, Any]:
        """Call the LLM and parse the response as JSON.

        Args:
            messages: OpenAI-style chat messages.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in the response.
            timeout: Per-call timeout in seconds.
            retries: Number of retries on transient failures.

        Returns:
            The parsed JSON object.
        """
        ...
