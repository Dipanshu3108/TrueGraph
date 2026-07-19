"""Schema validation and provenance checking for raw extractions."""

import logging
from pathlib import Path
from typing import Any

from knowledge_builder.types import Batch, Concept, ExtractionResult, Relationship, ValidationReport


logger = logging.getLogger(__name__)


def _pages_valid(page_numbers: list[int], allowed_pages: set[int]) -> bool:
    """Return True if every page number is present in the source document."""
    return bool(page_numbers) and all(p in allowed_pages for p in page_numbers)


def validate_extractions(
    results: list[ExtractionResult],
    batches: list[Batch] | None = None,
) -> tuple[list[ExtractionResult], ValidationReport]:
    """Schema-check every extraction, drop malformed entries, and verify pages.

    When ``batches`` is provided, image batches additionally get a provenance
    check: every referenced image file is confirmed readable, with failures
    recorded in the report (extraction itself already raises on missing
    files, so this is belt-and-braces provenance).
    """
    logger.info("Validating %d extraction result(s)...", len(results))
    allowed_pages: set[int] = set()
    for result in results:
        allowed_pages.update(result.page_numbers)

    batches_by_id = {b.batch_id: b for b in batches} if batches else {}

    report = ValidationReport(total_batches=len(results))
    cleaned_results: list[ExtractionResult] = []

    for result in results:
        batch_errors: list[str] = []
        kept_concepts: list[Concept] = []
        dropped_concepts: list[dict[str, Any]] = []

        batch = batches_by_id.get(result.batch_id)
        if result.content_type == "image" and batch is not None:
            for page_number, image_path in batch.content:  # type: ignore[union-attr]
                if not Path(image_path).is_file():
                    batch_errors.append(
                        f"Batch {result.batch_id}: image file for page {page_number} "
                        f"not readable: {image_path}"
                    )

        for concept in result.concepts:
            if not concept.name.strip():
                dropped_concepts.append({"reason": "missing name", "concept": concept.name})
                continue
            if not _pages_valid(concept.page_numbers, allowed_pages):
                dropped_concepts.append(
                    {
                        "reason": "invalid page numbers",
                        "concept": concept.name,
                        "pages": concept.page_numbers,
                    }
                )
                continue
            kept_concepts.append(concept)

        kept_relationships: list[Relationship] = []
        dropped_relationships: list[dict[str, Any]] = []
        for rel in result.relationships:
            if not rel.source.strip() or not rel.target.strip():
                dropped_relationships.append(
                    {"reason": "missing source or target", "relationship": rel}
                )
                continue
            if not _pages_valid(rel.page_numbers, allowed_pages):
                dropped_relationships.append(
                    {
                        "reason": "invalid page numbers",
                        "source": rel.source,
                        "target": rel.target,
                        "pages": rel.page_numbers,
                    }
                )
                continue
            kept_relationships.append(rel)

        kept_keywords = [k for k in result.keywords if isinstance(k, str) and k.strip()]
        dropped_keywords = [k for k in result.keywords if not (isinstance(k, str) and k.strip())]

        kept_aliases: list[tuple[str, str]] = []
        dropped_aliases: list[dict[str, Any]] = []
        for alias, concept_name in result.aliases:
            if alias.strip() and concept_name.strip():
                kept_aliases.append((alias.strip(), concept_name.strip()))
            else:
                dropped_aliases.append({"reason": "missing alias or concept", "alias": alias})

        def _has_pages(entry: dict[str, Any]) -> bool:
            pages = entry.get("page_numbers") or entry.get("pages")
            return isinstance(pages, list) and _pages_valid(
                [int(p) for p in pages if isinstance(p, int) or str(p).isdigit()], allowed_pages
            )

        kept_glossary = [e for e in result.glossary if e.get("term") and _has_pages(e)]
        kept_procedures = [e for e in result.procedures if e.get("name") and _has_pages(e)]
        kept_apis = [e for e in result.apis if e.get("name") and _has_pages(e)]

        report.dropped_concepts.extend(dropped_concepts)
        report.dropped_relationships.extend(dropped_relationships)
        report.dropped_keywords.extend(dropped_keywords)
        report.dropped_aliases.extend(dropped_aliases)

        if dropped_concepts or dropped_relationships or dropped_keywords or dropped_aliases:
            batch_errors.append(f"Dropped malformed entries from batch {result.batch_id}")

        cleaned = ExtractionResult(
            batch_id=result.batch_id,
            page_numbers=result.page_numbers,
            concepts=kept_concepts,
            relationships=kept_relationships,
            keywords=kept_keywords,
            aliases=kept_aliases,
            glossary=kept_glossary,
            procedures=kept_procedures,
            apis=kept_apis,
            raw=result.raw,
            content_type=result.content_type,
        )
        cleaned_results.append(cleaned)

        if batch_errors:
            report.invalid_batches += 1
            report.errors.extend(batch_errors)
        else:
            report.valid_batches += 1

    logger.info(
        "Validation complete: %d valid batch(es), %d invalid batch(es); "
        "dropped %d concept(s), %d relationship(s), %d keyword(s), %d alias(es)",
        report.valid_batches,
        report.invalid_batches,
        len(report.dropped_concepts),
        len(report.dropped_relationships),
        len(report.dropped_keywords),
        len(report.dropped_aliases),
    )
    return cleaned_results, report
