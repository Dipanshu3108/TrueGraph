"""LLM infrastructure shared by the understanding and generation stages.

The query pipeline reuses Knowledge_Builder's LiteLLM provider rather than
re-implementing one. This module resolves that import (the two packages live
side by side under ``libs/``) and bridges the provider's async interface into
the pipeline's synchronous stage functions.
"""

import asyncio
import threading
from pathlib import Path
from typing import Any, Coroutine, Optional

try:
    from knowledge_builder.config import ModelConfig
    from knowledge_builder.providers import LiteLLMProvider
except ImportError:  # pragma: no cover - depends on how the package is installed
    import sys

    # libs/Query_Pipeline/query_engine/llm.py -> libs/Knowledge_Builder
    _KB_ROOT = Path(__file__).resolve().parents[2] / "Knowledge_Builder"
    if _KB_ROOT.is_dir() and str(_KB_ROOT) not in sys.path:
        sys.path.insert(0, str(_KB_ROOT))
    from knowledge_builder.config import ModelConfig
    from knowledge_builder.providers import LiteLLMProvider


def build_provider(config: dict) -> LiteLLMProvider:
    """Create a LiteLLM provider from the query pipeline config dict.

    Only the model-related keys are consumed here; retrieval knobs such as
    ``top_k_concepts`` are handled by the pipeline stages themselves.
    """
    if not isinstance(config, dict):
        raise TypeError("config must be a dict")
    model_name = config.get("model_name")
    if not model_name:
        raise ValueError("config must include 'model_name'")
    return LiteLLMProvider(
        ModelConfig(
            model_name=model_name,
            provider=config.get("provider"),
            api_key=config.get("api_key"),
            base_url=config.get("base_url"),
            temperature=float(config.get("temperature", 0.0)),
            max_tokens=config.get("max_tokens"),
            timeout=config.get("timeout"),
            extra_headers=config.get("extra_headers"),
            extra_body=config.get("extra_body") or {},
        )
    )


def run_sync(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run an async provider call from synchronous pipeline code.

    Uses ``asyncio.run`` normally; when already inside a running event loop
    (e.g. Jupyter), the coroutine is executed on a fresh thread with its own
    loop instead, since ``asyncio.run`` cannot nest.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    outcome: dict[str, Any] = {}

    def _runner() -> None:
        try:
            outcome["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001
            outcome["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")
