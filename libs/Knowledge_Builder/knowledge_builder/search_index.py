"""Build deterministic document-local search indexes."""

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from knowledge_builder.types import MergedConcepts


logger = logging.getLogger(__name__)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def build_indexes(merged: MergedConcepts, bundle_dir: str) -> None:
    """Write keyword/alias/glossary indexes under ``bundle_dir/indexes/``."""
    bundle_path = Path(bundle_dir)
    indexes_dir = bundle_path / "indexes"
    indexes_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Building search indexes in %s", indexes_dir)

    # keyword -> concept ids
    keyword_index: dict[str, set[str]] = defaultdict(set)
    for concept in merged.concepts:
        for keyword in concept.keywords:
            keyword_index[keyword].add(concept.id)
        # Also index the concept name itself.
        keyword_index[concept.name.lower()].add(concept.id)

    # alias -> concept id
    alias_index: dict[str, str] = {}
    for alias, concept_id in merged.aliases.items():
        alias_index[alias] = concept_id

    # page -> concept ids
    page_index: dict[int, list[str]] = defaultdict(list)
    for concept in merged.concepts:
        for page_number in concept.page_numbers:
            if concept.id not in page_index[page_number]:
                page_index[page_number].append(concept.id)

    # glossary / procedure / api lookups
    glossary_index = {
        str(entry.get("term", ""))
        .strip()
        .lower(): {
            "definition": entry.get("definition", ""),
            "page_numbers": entry.get("page_numbers", []),
        }
        for entry in merged.glossary
        if entry.get("term")
    }
    procedure_index = {
        str(entry.get("name", ""))
        .strip()
        .lower(): {
            "steps": entry.get("steps", []),
            "page_numbers": entry.get("page_numbers", []),
        }
        for entry in merged.procedures
        if entry.get("name")
    }
    api_index = {
        str(entry.get("name", ""))
        .strip()
        .lower(): {
            "description": entry.get("description", ""),
            "page_numbers": entry.get("page_numbers", []),
        }
        for entry in merged.apis
        if entry.get("name")
    }

    _write_json(
        indexes_dir / "keyword_index.json",
        {k: sorted(v) for k, v in sorted(keyword_index.items())},
    )
    _write_json(indexes_dir / "alias_index.json", dict(sorted(alias_index.items())))
    _write_json(indexes_dir / "page_index.json", dict(sorted(page_index.items())))
    _write_json(indexes_dir / "glossary_index.json", dict(sorted(glossary_index.items())))
    _write_json(indexes_dir / "procedure_index.json", dict(sorted(procedure_index.items())))
    _write_json(indexes_dir / "api_index.json", dict(sorted(api_index.items())))

    logger.info(
        "Search indexes built: %d keyword(s), %d alias(es), %d page(s), "
        "%d glossary term(s), %d procedure(s), %d API(s)",
        len(keyword_index),
        len(alias_index),
        len(page_index),
        len(glossary_index),
        len(procedure_index),
        len(api_index),
    )
