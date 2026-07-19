"""De-duplicate and reconcile extractions across all batches of a document."""

import logging
import re
from typing import Any

from knowledge_builder.types import Concept, ExtractionResult, MergedConcepts, Relationship


logger = logging.getLogger(__name__)


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "unknown"


def merge_document(
    results: list[ExtractionResult],
    *,
    document_id: str = "",
    file_name: str = "",
    metadata: dict[str, Any] | None = None,
    append_metadata: dict[str, Any] | None = None,
    pages_total: int = 0,
    dropped_pages: list[int] | None = None,
) -> MergedConcepts:
    """De-duplicate/reconcile concepts across all of a document's batches."""
    logger.info("Merging %d extraction result(s)...", len(results))
    concepts_by_id: dict[str, Concept] = {}
    relationships: list[Relationship] = []
    seen_relationships: set[tuple[str, str, str, tuple[int, ...]]] = set()
    keywords: set[str] = set()
    aliases: dict[str, str] = {}
    glossary_by_term: dict[str, dict[str, Any]] = {}
    procedures_by_name: dict[str, dict[str, Any]] = {}
    apis_by_name: dict[str, dict[str, Any]] = {}

    for result in results:
        # Merge concepts by canonical id.
        for concept in result.concepts:
            if concept.id in concepts_by_id:
                existing = concepts_by_id[concept.id]
                existing.page_numbers = sorted(
                    set(existing.page_numbers) | set(concept.page_numbers)
                )
                existing.aliases = sorted(
                    set(a.lower() for a in existing.aliases)
                    | set(a.lower() for a in concept.aliases)
                )
                existing.keywords = sorted(
                    set(k.lower() for k in existing.keywords)
                    | set(k.lower() for k in concept.keywords)
                )
                if len(concept.description) > len(existing.description):
                    existing.description = concept.description
            else:
                concepts_by_id[concept.id] = Concept(
                    id=concept.id,
                    name=concept.name,
                    description=concept.description,
                    page_numbers=sorted(set(concept.page_numbers)),
                    aliases=sorted(set(a.lower() for a in concept.aliases)),
                    keywords=sorted(set(k.lower() for k in concept.keywords)),
                )

        # Merge relationships.
        for rel in result.relationships:
            key = (rel.source, rel.target, rel.type, tuple(sorted(rel.page_numbers)))
            if key not in seen_relationships:
                seen_relationships.add(key)
                relationships.append(rel)

        # Global keywords.
        keywords.update(k.lower() for k in result.keywords if k.strip())

        # Aliases: map alias -> canonical concept id.
        for alias, concept_name in result.aliases:
            alias_key = alias.lower().strip()
            concept_id = _slugify(concept_name)
            if alias_key and concept_id:
                aliases[alias_key] = concept_id

        # Glossary / procedures / APIs.
        for entry in result.glossary:
            term = str(entry.get("term", "")).strip().lower()
            if term:
                glossary_by_term.setdefault(term, entry)
        for entry in result.procedures:
            name = str(entry.get("name", "")).strip().lower()
            if name:
                procedures_by_name.setdefault(name, entry)
        for entry in result.apis:
            name = str(entry.get("name", "")).strip().lower()
            if name:
                apis_by_name.setdefault(name, entry)

    merged = MergedConcepts(
        document_id=document_id,
        file_name=file_name,
        metadata=metadata or {},
        append_metadata=append_metadata or {},
        pages_total=pages_total,
        pages_extracted=sum(len(r.page_numbers) for r in results),
        dropped_pages=dropped_pages or [],
        concepts=list(concepts_by_id.values()),
        relationships=relationships,
        keywords=keywords,
        aliases=aliases,
        glossary=list(glossary_by_term.values()),
        procedures=list(procedures_by_name.values()),
        apis=list(apis_by_name.values()),
    )
    logger.info(
        "Merged document: %d concept(s), %d relationship(s), %d keyword(s), "
        "%d alias(es), %d glossary term(s), %d procedure(s), %d API(s)",
        len(merged.concepts),
        len(merged.relationships),
        len(merged.keywords),
        len(merged.aliases),
        len(merged.glossary),
        len(merged.procedures),
        len(merged.apis),
    )
    return merged
