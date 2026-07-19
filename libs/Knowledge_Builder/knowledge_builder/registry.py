"""Update the global deterministic knowledge registry atomically."""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

REGISTRY_FILES = [
    "documents.json",
    "concepts.json",
    "aliases.json",
    "keywords.json",
    "relationships.json",
    "tags.json",
    "statistics.json",
    "global_graph.json",
]


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically using a temp file and os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _load_json(path: Path) -> Any:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def update_registry(bundle_path: str, knowledge_store_path: str) -> None:
    """Merge a bundle into the registry atomically and update statistics."""
    bundle = Path(bundle_path)
    registry_dir = Path(knowledge_store_path) / "registry"
    logger.info("Updating global registry at %s", registry_dir)

    document_json = _load_json(bundle / "document.json")
    document_id = document_json["id"]
    title = document_json.get("title", document_id)
    pages_total = document_json.get("pages_total", 0)
    append_metadata = document_json.get("append_metadata", {})

    concepts_dir = bundle / "concepts"
    concepts: list[dict[str, Any]] = []
    if concepts_dir.is_dir():
        for concept_file in sorted(concepts_dir.glob("*.json")):
            concepts.append(_load_json(concept_file))

    indexes_dir = bundle / "indexes"
    keyword_index: dict[str, list[str]] = (
        _load_json(indexes_dir / "keyword_index.json") if indexes_dir.is_dir() else {}
    )
    alias_index: dict[str, str] = (
        _load_json(indexes_dir / "alias_index.json") if indexes_dir.is_dir() else {}
    )
    page_index: dict[str, list[str]] = (
        _load_json(indexes_dir / "page_index.json") if indexes_dir.is_dir() else {}
    )

    # Load existing registry files.
    documents_registry = _load_json(registry_dir / "documents.json")
    concepts_registry = _load_json(registry_dir / "concepts.json")
    aliases_registry = _load_json(registry_dir / "aliases.json")
    keywords_registry = _load_json(registry_dir / "keywords.json")
    relationships_registry = _load_json(registry_dir / "relationships.json")
    tags_registry = _load_json(registry_dir / "tags.json")
    statistics_registry = _load_json(registry_dir / "statistics.json")
    global_graph = _load_json(registry_dir / "global_graph.json")

    # Update documents.json.
    current_version = documents_registry.get(document_id, {}).get("version", 0)
    documents_registry[document_id] = {
        "title": title,
        "pages": pages_total,
        "version": current_version + 1,
        "append_metadata": append_metadata,
    }

    # Update concepts.json.
    for concept in concepts:
        cid = concept["id"]
        docs = set(concepts_registry.get(cid, []))
        docs.add(document_id)
        concepts_registry[cid] = sorted(docs)

    # Update aliases.json.
    for alias, cid in alias_index.items():
        aliases_registry.setdefault(alias, cid)

    # Update keywords.json.
    for keyword, concept_ids in keyword_index.items():
        docs = set(keywords_registry.get(keyword, []))
        docs.add(document_id)
        keywords_registry[keyword] = sorted(docs)

    # Update relationships.json with cross-document edges.
    # Drop any previous edges for this document so re-processing does not leave
    # stale entries behind.
    existing_edges = [
        e
        for e in relationships_registry.get("edges", [])
        if isinstance(e, dict) and e.get("document") != document_id
    ]
    relationship_graph = _load_json(bundle / "relationship_graph.json")
    bundle_edges = []
    for edge in relationship_graph.get("edges", []):
        bundle_edges.append(
            {
                "source": edge["source"],
                "target": edge["target"],
                "type": edge.get("type", "relates_to"),
                "page_numbers": edge.get("page_numbers", []),
                "document": document_id,
            }
        )

    # Rebuild global graph nodes and edges.
    all_nodes = set(concepts_registry.keys())
    edges = existing_edges + bundle_edges
    edges = [
        dict(t)
        for t in {
            (
                e.get("document"),
                e.get("source"),
                e.get("target"),
                e.get("type"),
                tuple(e.get("page_numbers", [])),
            ): e
            for e in edges
        }.values()
    ]

    global_graph = {"nodes": sorted(all_nodes), "edges": edges}

    # Update tags.json from append_metadata categories.
    category = append_metadata.get("category")
    if category:
        tag_docs = set(tags_registry.get(category, []))
        tag_docs.add(document_id)
        tags_registry[category] = sorted(tag_docs)

    # Update statistics.json.
    total_pages = sum(d.get("pages", 0) for d in documents_registry.values())
    statistics_registry = {
        "documents": len(documents_registry),
        "concepts": len(concepts_registry),
        "relationships": len(edges),
        "pages": total_pages,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_version": statistics_registry.get("pipeline_version", "0.1.0"),
    }

    logger.info(
        "Registry updated: %d document(s), %d concept(s), %d relationship(s), %d page(s)",
        statistics_registry["documents"],
        statistics_registry["concepts"],
        statistics_registry["relationships"],
        statistics_registry["pages"],
    )

    # Persist all registry files atomically.
    _atomic_write_json(registry_dir / "documents.json", dict(sorted(documents_registry.items())))
    _atomic_write_json(registry_dir / "concepts.json", dict(sorted(concepts_registry.items())))
    _atomic_write_json(registry_dir / "aliases.json", dict(sorted(aliases_registry.items())))
    _atomic_write_json(registry_dir / "keywords.json", dict(sorted(keywords_registry.items())))
    _atomic_write_json(registry_dir / "relationships.json", {"edges": edges})
    _atomic_write_json(registry_dir / "tags.json", dict(sorted(tags_registry.items())))
    _atomic_write_json(registry_dir / "statistics.json", statistics_registry)
    _atomic_write_json(registry_dir / "global_graph.json", global_graph)
