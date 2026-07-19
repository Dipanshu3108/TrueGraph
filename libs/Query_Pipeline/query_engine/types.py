"""Typed data structures passed between query pipeline stages.

Mirrors the discipline of Knowledge_Builder's ``types.py``: every stage
function takes explicit arguments and returns explicit outputs, and these
dataclasses are the only shapes that cross stage boundaries.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class QueryIntent:
    """Structured understanding of the natural language question."""

    intent: str
    keywords: list[str]
    concepts: list[str]
    filters: dict


@dataclass
class RetrievalPlan:
    """Deterministic retrieval strategy derived from the intent."""

    scope: list[str]
    concepts: list[str]
    keywords: list[str]
    relationship_depth: int


@dataclass
class Candidate:
    """A single retrieved concept, before or after ranking."""

    concept_id: str
    document_id: str
    score: float
    rank: int
    evidence_pages: list[int]
    description: str  # pulled straight from concepts/, no extra read


@dataclass
class Evidence:
    """Raw page text loaded for a top-ranked candidate."""

    document_id: str
    page_number: int
    content: str
    #: Relevance score in [0, 1] against the query intent (0.0 when unscored).
    score: float = 0.0


@dataclass
class QueryResult:
    """Public result returned by ``ask()``."""

    answer: str
    citations: list
    documents_used: list[str]
    concepts_used: list[str]
