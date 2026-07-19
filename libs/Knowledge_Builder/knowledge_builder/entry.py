"""Public orchestration entry point for the Knowledge Builder pipeline."""

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from knowledge_builder.batching import filter_empty_pages, make_batches
from knowledge_builder.bundle import write_bundle
from knowledge_builder.exceptions import KnowledgeBuilderError
from knowledge_builder.io_loader import load_pages
from knowledge_builder.merge import merge_document
from knowledge_builder.okf_generator import write_concepts
from knowledge_builder.registry import update_registry
from knowledge_builder.relationships import build_relationships
from knowledge_builder.scheduler import run_batches
from knowledge_builder.search_index import build_indexes
from knowledge_builder.types import BuildResult
from knowledge_builder.validation import validate_extractions


logger = logging.getLogger(__name__)


def _ensure_logging() -> None:
    """Attach a console handler to the knowledge_builder logger if absent."""
    kb_logger = logging.getLogger("knowledge_builder")
    if not kb_logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("%(name)s - %(levelname)s - %(message)s")
        )
        kb_logger.addHandler(handler)
    kb_logger.setLevel(logging.INFO)


def _slugify(value: str) -> str:
    """Return a stable document identifier slug."""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "document"


def _get_config(config: dict[str, Any], key: str, default: Any = None) -> Any:
    """Safely read a config value."""
    if not isinstance(config, dict):
        raise TypeError("config must be a dict")
    return config.get(key, default)


def _check_vision_capability(config: dict[str, Any]) -> None:
    """Fail loudly when a document has image pages but the model cannot see them.

    Raises if LiteLLM definitively reports the model lacks image input
    support; logs a warning and proceeds when support cannot be determined.
    """
    model_name = str(_get_config(config, "model_name", ""))
    provider = _get_config(config, "provider")
    if "/" in model_name:
        model_id = model_name
    elif provider:
        model_id = f"{provider}/{model_name}"
    else:
        model_id = model_name

    try:
        import litellm

        supports = litellm.supports_vision(model=model_id)
    except Exception:  # noqa: BLE001
        logger.warning(
            "Could not determine vision support for model %s; proceeding anyway.",
            model_id,
        )
        return
    if not supports:
        raise KnowledgeBuilderError(
            f"Configured model '{model_id}' does not support image input, but the "
            "document contains image pages. Choose a vision-capable model."
        )


def build_kb(file_path: str, config: dict[str, Any]) -> BuildResult:
    """Run the full knowledge-building pipeline on a parsed document.

    This is the only public entry point.  It loads the parsed document, batches
    content-bearing pages, extracts knowledge concurrently, validates and merges
    the results, writes a self-contained OKF bundle, and updates the global
    registry.
    """
    _ensure_logging()
    logger.info("Starting knowledge build for: %s", file_path)

    # 1. Load pages (text and image pages classified per page).
    image_storage_path = _get_config(config, "image_storage_path")
    file_name, metadata, pages = load_pages(file_path, image_storage_path=image_storage_path)
    logger.info("Loaded document: %s (%d total page(s))", file_name, len(pages))

    # 2. Filter empty pages (text: blank; image: missing file).
    content_pages, dropped_pages = filter_empty_pages(pages)

    # 2b. Image pages require a vision-capable model.
    if any(p.content_type == "image" for p in content_pages):
        _check_vision_capability(config)

    # 3. Build batches (never mixed text+image).
    page_batch = int(_get_config(config, "page_batch", 3))
    image_page_batch = int(_get_config(config, "image_page_batch", page_batch))
    batches = make_batches(content_pages, page_batch, image_page_batch)

    # 4. Run extraction batches concurrently.
    results, _usage_log = asyncio.run(run_batches(batches, {**config, "document_name": file_name}))

    # 5. Validate extractions.
    cleaned_results, validation_report = validate_extractions(results, batches)

    # 6. Merge across batches.
    document_id = _slugify(Path(file_name).stem)
    logger.info("Merging extractions into document: %s", document_id)
    merged = merge_document(
        cleaned_results,
        document_id=document_id,
        file_name=file_name,
        metadata=metadata,
        append_metadata=_get_config(config, "append_metadata", {}),
        pages_total=len(pages),
        dropped_pages=dropped_pages,
    )

    # 7. Build document-local relationship graph.
    graph = build_relationships(merged)

    # 8-9. Prepare bundle directory and write OKF artifacts.
    knowledge_store_path = _get_config(config, "knowledge_store_path", "./knowledge")
    bundle_dir = Path(knowledge_store_path) / document_id
    bundle_dir.mkdir(parents=True, exist_ok=True)

    write_concepts(merged, graph, str(bundle_dir))
    build_indexes(merged, str(bundle_dir))

    # 10. Assemble final bundle.
    bundle_path = write_bundle(
        str(bundle_dir),
        knowledge_store_path,
        document_id,
        validation_report,
        pages=pages,
        source_path=file_path,
    )

    # 11. Update global registry.
    update_registry(bundle_path, knowledge_store_path)

    validation_report_path = str((Path(bundle_path) / "validation_report.json").resolve())

    logger.info(
        "Knowledge build complete: %s | %d concept(s) | %d relationship(s) | bundle: %s",
        document_id,
        len(merged.concepts),
        len(graph.edges),
        bundle_path,
    )

    return BuildResult(
        document_id=document_id,
        bundle_path=bundle_path,
        pages_total=len(pages),
        pages_extracted=len(content_pages),
        concepts_count=len(merged.concepts),
        relationships_count=len(graph.edges),
        validation_report_path=validation_report_path,
    )
