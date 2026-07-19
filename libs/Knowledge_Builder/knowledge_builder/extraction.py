"""LLM-based extraction of concepts and relationships from one batch."""

import logging
import re
import base64
from typing import Any
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from knowledge_builder.config import ModelConfig
from knowledge_builder.exceptions import ExtractionError
from knowledge_builder.providers.litellm_provider import LiteLLMProvider
from knowledge_builder.types import Batch, Concept, ExtractionResult, Relationship

logger = logging.getLogger(__name__)

_EXTRACTION_SYSTEM_PROMPT = (
    "You are a precise knowledge-extraction assistant. "
    "Read the provided document pages and return a single JSON object matching the schema below. "
    "Only cite page numbers that are explicitly listed in the user message. "
    "Do not include commentary outside the JSON.\n\n"
    "Schema:\n"
    "{\n"
    '  "concepts": [\n'
    "    {\n"
    '      "name": "Concise concept name",\n'
    '      "description": "One or two sentences explaining the concept.",\n'
    '      "page_numbers": [N],\n'
    '      "aliases": ["alternate name", "abbreviation"],\n'
    '      "keywords": ["relevant", "search", "terms"]\n'
    "    }\n"
    "  ],\n"
    '  "relationships": [\n'
    "    {\n"
    '      "source": "concept name or alias",\n'
    '      "target": "related concept name or alias",\n'
    '      "type": "one of: part_of, references, depends_on, causes, relates_to, example_of",\n'
    '      "page_numbers": [N]\n'
    "    }\n"
    "  ],\n"
    '  "keywords": ["global", "search", "terms"],\n'
    '  "aliases": [\n'
    '    {"alias": "alternate name", "concept": "canonical concept name"}\n'
    "  ],\n"
    '  "glossary": [\n'
    '    {"term": "term", "definition": "short definition", "page_numbers": [N]}\n'
    "  ],\n"
    '  "procedures": [\n'
    '    {"name": "procedure name", "steps": ["step 1", "step 2"], "page_numbers": [N]}\n'
    "  ],\n"
    '  "apis": [\n'
    '    {"name": "API or function name", "description": "...", "page_numbers": [N]}\n'
    "  ]\n"
    "}"
)

_EXTRACTION_SYSTEM_PROMPT_IMAGE = (
    "You are a precise knowledge-extraction assistant. "
    "Read the provided document page images and return a single JSON object matching the schema below. "
    "Treat figures, diagrams, charts, and tables as first-class extractable content, not just prose. "
    "Only cite page numbers that are explicitly listed in the user message. "
    "Do not include commentary outside the JSON.\n\n"
    "Schema:\n"
    "{\n"
    '  "concepts": [\n'
    "    {\n"
    '      "name": "Concise concept name",\n'
    '      "description": "One or two sentences explaining the concept.",\n'
    '      "page_numbers": [N],\n'
    '      "aliases": ["alternate name", "abbreviation"],\n'
    '      "keywords": ["relevant", "search", "terms"]\n'
    "    }\n"
    "  ],\n"
    '  "relationships": [\n'
    "    {\n"
    '      "source": "concept name or alias",\n'
    '      "target": "related concept name or alias",\n'
    '      "type": "one of: part_of, references, depends_on, causes, relates_to, example_of",\n'
    '      "page_numbers": [N]\n'
    "    }\n"
    "  ],\n"
    '  "keywords": ["global", "search", "terms"],\n'
    '  "aliases": [\n'
    '    {"alias": "alternate name", "concept": "canonical concept name"}\n'
    "  ],\n"
    '  "glossary": [\n'
    '    {"term": "term", "definition": "short definition", "page_numbers": [N]}\n'
    "  ],\n"
    '  "procedures": [\n'
    '    {"name": "procedure name", "steps": ["step 1", "step 2"], "page_numbers": [N]}\n'
    "  ],\n"
    '  "apis": [\n'
    '    {"name": "API or function name", "description": "...", "page_numbers": [N]}\n'
    "  ]\n"
    "}"
)

_MIME_BY_EXTENSION = {
    ".webp": "image/webp",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def _encode_image_block(page_number: int, image_path: str) -> list[dict[str, Any]]:
    """Build the text + image_url content blocks for one page image.

    Raises ExtractionError if the file cannot be read — image pages must
    never be dropped silently.
    """
    path = Path(image_path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ExtractionError(
            f"Page {page_number}: cannot read image file {image_path}: {exc}"
        ) from exc
    media_type = _MIME_BY_EXTENSION.get(path.suffix.lower(), "image/webp")
    encoded = base64.b64encode(data).decode("ascii")
    return [
        {"type": "text", "text": f"### Page {page_number}"},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{media_type};base64,{encoded}",
                "detail": "high",
            },
        },
    ]


def _build_image_messages(batch: Batch) -> list[dict[str, Any]]:
    """Build a single multimodal user message covering the whole image batch."""
    user_blocks: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": "Extract structured knowledge from the following page images:",
        }
    ]
    for page_number, image_path in batch.content:  # type: ignore[union-attr]
        user_blocks.extend(_encode_image_block(page_number, image_path))
    return [
        {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT_IMAGE},
        {"role": "user", "content": user_blocks},
    ]
# Usage tracking =========================================================
USAGE_DIR = Path(__file__).resolve().parent.parent / "Usage"
"""Directory where per-document usage logs are written."""

@dataclass(frozen=True)
class UsageCall:
    """Token usage for a single LLM completion."""

    call_number: int
    model: str
    provider: Optional[str]
    input_tokens: int
    output_tokens: int
    total_tokens: int
    timestamp: str


class UsageTracker:
    """Accumulate LLM usage across many calls and persist a human-readable log.

    The tracker is graph-safe: it is passed by reference into every parallel worker and mutated
    in-place.  A single log is written after the full document run finishes.
    """

    def __init__(self, document_name: str) -> None:
        self.document_name = document_name
        self.calls: list[UsageCall] = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_calls = 0

    def record(
        self,
        *,
        model: str,
        provider: Optional[str],
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Record one LLM completion's token usage."""
        self.total_calls += 1
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.calls.append(
            UsageCall(
                call_number=self.total_calls,
                model=model,
                provider=provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                timestamp=datetime.now().isoformat(),
            )
        )

    def write_log(self) -> Path:
        """Write the accumulated usage to ``Usage/Usage_<document>.log``.

        Returns the path of the written log file.
        """
        USAGE_DIR.mkdir(parents=True, exist_ok=True)
        safe_stem = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(self.document_name).stem)
        log_path = USAGE_DIR / f"Usage_{safe_stem}.log"

        with log_path.open("w", encoding="utf-8") as handle:
            first_model = self.calls[0].model if self.calls else "unknown"
            first_provider = (self.calls[0].provider or "unknown") if self.calls else "unknown"

            handle.write(f"Document: {self.document_name}\n")
            handle.write(f"Model: {first_model}\n")
            handle.write(f"Provider: {first_provider}\n")
            handle.write(f"Total LLM Calls: {self.total_calls}\n")
            handle.write(f"Total Input Tokens: {self.total_input_tokens}\n")
            handle.write(f"Total Output Tokens: {self.total_output_tokens}\n")
            handle.write(f"Total Tokens: {self.total_input_tokens + self.total_output_tokens}\n")
            handle.write("Per-Call Usage:\n")

            for call in self.calls:
                handle.write(f"  Call {call.call_number}:\n")
                handle.write(f"    Timestamp: {call.timestamp}\n")
                handle.write(f"    Model: {call.model}\n")
                handle.write(f"    Provider: {call.provider or 'unknown'}\n")
                handle.write(f"    Input Tokens: {call.input_tokens}\n")
                handle.write(f"    Output Tokens: {call.output_tokens}\n")
                handle.write(f"    Total Tokens: {call.total_tokens}\n")

        logger.info("Usage log written: %s", log_path)
        return log_path
# Usage tracking =========================================================    

def _slugify(value: str) -> str:
    """Create a stable id slug from a concept name."""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "unknown"


def _as_list(value: Any) -> list[Any]:
    """Normalize a JSON field to a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _parse_page_numbers(value: Any, allowed_pages: set[int]) -> list[int]:
    """Return sorted, de-duplicated page numbers that are in the allowed set."""
    numbers: set[int] = set()
    for item in _as_list(value):
        try:
            num = int(item)
        except (TypeError, ValueError):
            continue
        if num in allowed_pages:
            numbers.add(num)
    return sorted(numbers)


def _parse_concepts(raw_concepts: list[Any], allowed_pages: set[int]) -> list[Concept]:
    """Convert raw concept dicts into typed :class:`Concept` objects."""
    concepts: list[Concept] = []
    for entry in raw_concepts:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        description = str(entry.get("description", "")).strip()
        page_numbers = _parse_page_numbers(entry.get("page_numbers"), allowed_pages)
        aliases = [str(a).strip() for a in _as_list(entry.get("aliases")) if str(a).strip()]
        keywords = [str(k).strip() for k in _as_list(entry.get("keywords")) if str(k).strip()]
        concepts.append(
            Concept(
                id=_slugify(name),
                name=name,
                description=description,
                page_numbers=page_numbers,
                aliases=aliases,
                keywords=keywords,
            )
        )
    return concepts


def _parse_relationships(
    raw_relationships: list[Any],
    concept_name_to_id: dict[str, str],
    allowed_pages: set[int],
) -> list[Relationship]:
    """Convert raw relationship dicts into typed :class:`Relationship` objects."""
    relationships: list[Relationship] = []
    for entry in raw_relationships:
        if not isinstance(entry, dict):
            continue
        source_name = str(entry.get("source", "")).strip()
        target_name = str(entry.get("target", "")).strip()
        if not source_name or not target_name:
            continue
        source_id = concept_name_to_id.get(_slugify(source_name), _slugify(source_name))
        target_id = concept_name_to_id.get(_slugify(target_name), _slugify(target_name))
        rel_type = str(entry.get("type", "relates_to")).strip().lower() or "relates_to"
        page_numbers = _parse_page_numbers(entry.get("page_numbers"), allowed_pages)
        relationships.append(
            Relationship(
                source=source_id,
                target=target_id,
                type=rel_type,
                page_numbers=page_numbers,
            )
        )
    return relationships


def _parse_aliases(raw_aliases: list[Any]) -> list[tuple[str, str]]:
    """Return canonical (alias, concept_name) tuples."""
    aliases: list[tuple[str, str]] = []
    for entry in raw_aliases:
        if isinstance(entry, dict):
            alias = str(entry.get("alias", "")).strip()
            concept = str(entry.get("concept", "")).strip()
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            alias = str(entry[0]).strip()
            concept = str(entry[1]).strip()
        else:
            continue
        if alias and concept:
            aliases.append((alias, concept))
    return aliases


def _sanitize_entries(raw_entries: list[Any], allowed_pages: set[int]) -> list[dict[str, Any]]:
    """Clean glossary/procedure/api entries and keep only allowed page numbers."""
    cleaned: list[dict[str, Any]] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        entry = {
            k: (_parse_page_numbers(v, allowed_pages) if k in {"page_numbers", "pages"} else v)
            for k, v in entry.items()
        }
        cleaned.append(entry)
    return cleaned


async def extract_batch(batch: Batch, config: dict[str, Any], tracker: Optional["UsageTracker"] = None) -> ExtractionResult:
    """One LLM call for one batch.

    Returned concepts/relationships/keywords only cite page numbers present in
    ``batch.page_numbers``.
    """
    model_config = ModelConfig(
        model_name=config["model_name"],
        provider=config.get("provider"),
        api_key=config.get("api_key"),
        base_url=config.get("base_url"),
        temperature=config.get("temperature", 0.0),
        extra_body=config.get("extra_body", {})
    )
    provider = LiteLLMProvider(model_config)

    if batch.content_type == "image":
        messages = _build_image_messages(batch)
    else:
        messages = [
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Extract structured knowledge from the following pages:\n\n{batch.content}",
            },
        ]

    logger.debug("Calling LLM for batch %d (pages %s)", batch.batch_id, batch.page_numbers)
    try:
        # Retries are handled by the scheduler; avoid double retrying here.
        raw = await provider.complete_json(messages, retries=0)
        if tracker is not None:
            input_tok, output_tok = provider.get_last_usage()
            tracker.record(
                model=model_config.model_name,
                provider=model_config.provider,
                input_tokens=input_tok,
                output_tokens=output_tok,
            )
        logger.info("LLM call completed for batch %d", batch.batch_id)
    except Exception as exc:
        raise ExtractionError(
            f"Extraction failed for batch {batch.batch_id} (pages {batch.page_numbers}): {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise ExtractionError(
            f"Batch {batch.batch_id}: expected JSON object, got {type(raw).__name__}"
        )

    allowed_pages = set(batch.page_numbers)
    concepts = _parse_concepts(raw.get("concepts", []), allowed_pages)
    name_to_id = {c.id: c.id for c in concepts}
    name_to_id.update({_slugify(c.name): c.id for c in concepts})
    for c in concepts:
        for alias in c.aliases:
            name_to_id[_slugify(alias)] = c.id

    relationships = _parse_relationships(raw.get("relationships", []), name_to_id, allowed_pages)
    keywords = [str(k).strip() for k in _as_list(raw.get("keywords")) if str(k).strip()]
    aliases = _parse_aliases(raw.get("aliases", []))
    glossary = _sanitize_entries(_as_list(raw.get("glossary", [])), allowed_pages)
    procedures = _sanitize_entries(_as_list(raw.get("procedures", [])), allowed_pages)
    apis = _sanitize_entries(_as_list(raw.get("apis", [])), allowed_pages)

    return ExtractionResult(
        batch_id=batch.batch_id,
        page_numbers=batch.page_numbers,
        concepts=concepts,
        relationships=relationships,
        keywords=keywords,
        aliases=aliases,
        glossary=glossary,
        procedures=procedures,
        apis=apis,
        raw=raw,
        content_type=batch.content_type,
    )
