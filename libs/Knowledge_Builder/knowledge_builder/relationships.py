"""Build the document-local relationship graph."""

import logging

from knowledge_builder.types import MergedConcepts, Relationship, RelationshipGraph


logger = logging.getLogger(__name__)

_VALID_REL_TYPES = {
    "part_of",
    "references",
    "depends_on",
    "causes",
    "relates_to",
    "example_of",
    "is_a",
    "has_a",
    "uses",
}


def build_relationships(merged: MergedConcepts) -> RelationshipGraph:
    """Resolve and type edges between the document's own concepts."""
    logger.info(
        "Building relationship graph from %d concept(s) and %d relationship(s)...",
        len(merged.concepts),
        len(merged.relationships),
    )
    concept_ids = {c.id for c in merged.concepts}
    nodes = sorted(concept_ids)
    edges: list[Relationship] = []

    for rel in merged.relationships:
        source = rel.source
        target = rel.target
        if source not in concept_ids or target not in concept_ids:
            continue
        if source == target:
            continue
        rel_type = rel.type if rel.type in _VALID_REL_TYPES else "relates_to"
        edges.append(
            Relationship(
                source=source,
                target=target,
                type=rel_type,
                page_numbers=sorted(set(rel.page_numbers)),
            )
        )

    graph = RelationshipGraph(nodes=nodes, edges=edges)
    logger.info("Relationship graph: %d node(s), %d edge(s)", len(graph.nodes), len(graph.edges))
    return graph
