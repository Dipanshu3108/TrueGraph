"""Configuration models for the Knowledge Builder pipeline."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ModelConfig:
    """LLM provider configuration.

    Fields mirror the ``model`` section of the pipeline config. ``provider`` and
    ``model_name`` are combined into the LiteLLM model identifier when needed.
    """

    model_name: str
    provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    timeout: Optional[float] = None
    extra_headers: Optional[dict[str, str]] = None
    extra_body: Optional[dict[str, Any]] = field(default_factory=dict)


@dataclass
class PipelineConfig:
    """Top-level configuration passed to ``build_knowledge``.

    This shape is consumed by the scheduler, extraction, validation, and
    registry stages. Only a subset is handled by the LLM provider layer.
    """

    model_name: str
    provider: str
    api_key: str
    base_url: Optional[str] = None
    knowledge_store_path: str = "./knowledge"
    num_sub_agents: int = 4
    page_batch: int = 3
    image_page_batch: Optional[int] = None
    image_storage_path: Optional[str] = None
    append_metadata: dict[str, Any] = field(default_factory=dict)
    model_config: Optional[ModelConfig] = None

    def __post_init__(self) -> None:
        if self.model_config is None:
            self.model_config = ModelConfig(
                model_name=self.model_name,
                provider=self.provider,
                api_key=self.api_key,
                base_url=self.base_url,
            )
