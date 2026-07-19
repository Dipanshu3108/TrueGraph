"""Write the OKF concept tree and document-level metadata."""

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from knowledge_builder.types import MergedConcepts, RelationshipGraph


logger = logging.getLogger(__name__)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def write_concepts(
    merged: MergedConcepts,
    graph: RelationshipGraph,
    bundle_dir: str,
) -> None:
    """Write ``concepts/``, ``document.json``, and ``metadata.json`` under ``bundle_dir``."""
    bundle_path = Path(bundle_dir)
    concepts_dir = bundle_path / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Writing %d concept file(s) to %s", len(merged.concepts), concepts_dir)
    for concept in merged.concepts:
        concept_path = concepts_dir / f"{concept.id}.json"
        _write_json(
            concept_path,
            {
                "id": concept.id,
                "name": concept.name,
                "description": concept.description,
                "page_numbers": concept.page_numbers,
                "aliases": concept.aliases,
                "keywords": concept.keywords,
            },
        )

    document_json = {
        "id": merged.document_id,
        "title": merged.metadata.get("title") or merged.file_name,
        "file_name": merged.file_name,
        "pages_total": merged.pages_total,
        "pages_extracted": merged.pages_extracted,
        "dropped_pages": sorted(merged.dropped_pages),
        "concepts_count": len(merged.concepts),
        "relationships_count": len(graph.edges),
        "append_metadata": merged.append_metadata,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(bundle_path / "document.json", document_json)

    relationship_graph = {
        "nodes": graph.nodes,
        "edges": [
            {
                "source": e.source,
                "target": e.target,
                "type": e.type,
                "page_numbers": e.page_numbers,
            }
            for e in graph.edges
        ],
    }
    _write_json(bundle_path / "relationship_graph.json", relationship_graph)

    metadata_json = {
        "file_name": merged.file_name,
        "parser_metadata": merged.metadata,
        "append_metadata": merged.append_metadata,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(bundle_path / "metadata.json", metadata_json)
