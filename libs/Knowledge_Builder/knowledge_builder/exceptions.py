"""Exceptions raised by the Knowledge Builder pipeline."""


class KnowledgeBuilderError(Exception):
    """Base exception for all Knowledge Builder errors."""


class ProviderError(KnowledgeBuilderError):
    """Raised when the LLM provider fails to return a usable response."""


class ProviderRateLimitError(ProviderError):
    """Raised when the provider returns a rate-limit error."""


class ProviderAuthenticationError(ProviderError):
    """Raised when authentication with the provider fails."""


class ProviderTimeoutError(ProviderError):
    """Raised when the provider call times out."""


class ExtractionError(KnowledgeBuilderError):
    """Raised when concept extraction fails or returns invalid data."""


class ValidationError(KnowledgeBuilderError):
    """Raised when extracted content fails schema validation."""
