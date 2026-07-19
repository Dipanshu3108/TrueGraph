"""Shared data types used across the Knowledge Builder pipeline."""

from dataclasses import dataclass, field
from typing import Any, Literal


ContentType = Literal["text", "image"]


@dataclass
class Page:
    """A single page from a parsed document.

    ``content`` is page text when ``content_type == "text"``, or a filesystem
    path to an image file when ``content_type == "image"``.
    """

    page_number: int
    content: str
    content_type: ContentType = "text"


@dataclass
class Batch:
    """A group of same-type pages sent to the LLM together.

    ``content`` is the pre-joined page text for text batches, or a list of
    ``(page_number, image_path)`` pairs for image batches. Batches are never
    mixed text+image.
    """

    batch_id: int
    page_numbers: list[int]
    content: "str | list[tuple[int, str]]"
    content_type: ContentType = "text"


@dataclass
class Concept:
    """A canonical concept extracted from the document."""

    id: str
    name: str
    description: str
    page_numbers: list[int] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass
class Relationship:
    """A typed edge between two concepts."""

    source: str
    target: str
    type: str
    page_numbers: list[int] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """Raw structured output returned by the LLM for one batch."""

    batch_id: int
    page_numbers: list[int]
    concepts: list[Concept] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    aliases: list[tuple[str, str]] = field(default_factory=list)
    glossary: list[dict[str, Any]] = field(default_factory=list)
    procedures: list[dict[str, Any]] = field(default_factory=list)
    apis: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    content_type: ContentType = "text"


@dataclass
class ValidationReport:
    """Summary of what passed and failed schema validation."""

    total_batches: int = 0
    valid_batches: int = 0
    invalid_batches: int = 0
    dropped_concepts: list[dict[str, Any]] = field(default_factory=list)
    dropped_relationships: list[dict[str, Any]] = field(default_factory=list)
    dropped_keywords: list[str] = field(default_factory=list)
    dropped_aliases: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class RelationshipGraph:
    """Document-local concept graph."""

    nodes: list[str] = field(default_factory=list)
    edges: list[Relationship] = field(default_factory=list)


@dataclass
class MergedConcepts:
    """De-duplicated concept set for a whole document."""

    document_id: str
    file_name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    append_metadata: dict[str, Any] = field(default_factory=dict)
    pages_total: int = 0
    pages_extracted: int = 0
    dropped_pages: list[int] = field(default_factory=list)
    concepts: list[Concept] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    keywords: set[str] = field(default_factory=set)
    aliases: dict[str, str] = field(default_factory=dict)
    glossary: list[dict[str, Any]] = field(default_factory=list)
    procedures: list[dict[str, Any]] = field(default_factory=list)
    apis: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BuildResult:
    """Summary returned by ``build_kb`` after processing a document."""

    document_id: str
    bundle_path: str
    pages_total: int
    pages_extracted: int
    concepts_count: int
    relationships_count: int
    validation_report_path: str
