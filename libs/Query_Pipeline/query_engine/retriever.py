"""Stage 4 — Deterministic Retrieval.

Reads registry indexes and document-local indexes to gather raw candidates.
No vector search, no scoring, no ranking — every concept that matches an
alias, a keyword, or a graph neighbourhood becomes exactly one
:class:`Candidate` keyed by ``(concept_id, document_id)``.
"""

import json
import logging
import re
from pathlib import Path

from query_engine.types import Candidate, RetrievalPlan

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[^a-z0-9]+")


def normalize_term(term: str) -> str:
    """Lowercase and collapse whitespace — the form index keys are stored in."""
    return " ".join(str(term).lower().split())


def slugify(term: str) -> str:
    """Return the concept-id slug for a human-readable term."""
    return _WORD_RE.sub("-", normalize_term(term)).strip("-")


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_registry(knowledge_path: str) -> tuple[dict, dict, dict]:
    """Load the registry aliases, concept->documents map, and global graph."""
    registry = Path(knowledge_path) / "registry"
    aliases = read_json(registry / "aliases.json")
    concepts = read_json(registry / "concepts.json")
    graph = read_json(registry / "global_graph.json")
    return aliases, concepts, graph


def build_adjacency(graph: dict) -> dict[str, set[str]]:
    """Build an undirected adjacency map from graph edges.

    Proximity is direction-agnostic: a ``part_of`` edge relates two concepts
    regardless of which one is the source.
    """
    adjacency: dict[str, set[str]] = {}
    for edge in graph.get("edges", []):
        source, target = edge.get("source"), edge.get("target")
        if not source or not target:
            continue
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)
    return adjacency


def graph_distances(
    seeds: list[str], adjacency: dict[str, set[str]], max_depth: int
) -> dict[str, int]:
    """Breadth-first distances from the seed concepts, bounded by depth."""
    distances: dict[str, int] = {}
    frontier = []
    for seed in seeds:
        if seed in adjacency and seed not in distances:
            distances[seed] = 0
            frontier.append(seed)
    depth = 0
    while frontier and depth < max_depth:
        depth += 1
        next_frontier = []
        for node in frontier:
            for neighbour in adjacency.get(node, ()):
                if neighbour not in distances:
                    distances[neighbour] = depth
                    next_frontier.append(neighbour)
        frontier = next_frontier
    return distances


def resolve_seeds(
    terms: list[str], registry_aliases: dict, local_aliases: dict[str, dict]
) -> set[str]:
    """Resolve human-readable concept terms to concept ids via aliases."""
    seeds: set[str] = set()
    for term in terms:
        normalized = normalize_term(term)
        slug = slugify(term)
        if normalized in registry_aliases:
            seeds.add(registry_aliases[normalized])
        for alias_index in local_aliases.values():
            if normalized in alias_index:
                seeds.add(alias_index[normalized])
        if slug:
            seeds.add(slug)
    return seeds


def retrieve_candidates(plan: RetrievalPlan, knowledge_path: str) -> list[Candidate]:
    """Gather unranked, unscored candidates for the retrieval plan.

    Sources, all deterministic:
    - alias match (registry ``aliases.json`` + document ``alias_index.json``)
    - direct concept-id match (registry ``concepts.json``)
    - keyword match (document ``keyword_index.json``)
    - graph expansion (registry ``global_graph.json``, up to
      ``plan.relationship_depth`` hops from the query's seed concepts)
    """
    if not isinstance(plan, RetrievalPlan):
        raise TypeError("plan must be a RetrievalPlan")

    logger.debug(
        "Retrieving candidates: scope=%s, concepts=%s, keywords=%s",
        plan.scope, plan.concepts, plan.keywords
    )

    store = Path(knowledge_path)
    registry_aliases, registry_concepts, graph = load_registry(knowledge_path)
    scope_set = set(plan.scope)

    def in_scope(concept_id: str) -> list[str]:
        """Document ids for a concept, restricted to the plan scope."""
        return sorted(scope_set.intersection(registry_concepts.get(concept_id, [])))

    # Document-local indexes.
    local_aliases: dict[str, dict] = {}
    local_keywords: dict[str, dict] = {}
    for document_id in plan.scope:
        indexes = store / document_id / "indexes"
        alias_file = indexes / "alias_index.json"
        keyword_file = indexes / "keyword_index.json"
        local_aliases[document_id] = read_json(alias_file) if alias_file.is_file() else {}
        local_keywords[document_id] = read_json(keyword_file) if keyword_file.is_file() else {}

    found: dict[tuple[str, str], None] = {}  # ordered set of (concept_id, document_id)

    def add(concept_id: str, document_ids: list[str]) -> None:
        for document_id in document_ids:
            found.setdefault((concept_id, document_id))

    terms = list(plan.concepts) + list(plan.keywords)

    # 1. Alias-expanded exact match + direct concept-id match.
    for term in terms:
        normalized = normalize_term(term)
        slug = slugify(term)
        if normalized in registry_aliases:
            add(registry_aliases[normalized], in_scope(registry_aliases[normalized]))
        if slug in registry_concepts:
            add(slug, in_scope(slug))
        for document_id in plan.scope:
            alias_hit = local_aliases[document_id].get(normalized)
            if alias_hit:
                add(alias_hit, [document_id])

    # 2. Keyword match against the document-local inverted indexes.
    for term in terms:
        normalized = normalize_term(term)
        for document_id in plan.scope:
            for concept_id in local_keywords[document_id].get(normalized, []):
                add(concept_id, [document_id])

    # 3. Graph expansion from the query's seed concepts.
    if plan.relationship_depth > 0:
        seeds = resolve_seeds(plan.concepts, registry_aliases, local_aliases)
        adjacency = build_adjacency(graph)
        for concept_id in graph_distances(sorted(seeds), adjacency, plan.relationship_depth):
            add(concept_id, in_scope(concept_id))

    # Hydrate candidates from the concept files (description + evidence pages).
    candidates: list[Candidate] = []
    for concept_id, document_id in sorted(found):
        concept_file = store / document_id / "concepts" / f"{concept_id}.json"
        if not concept_file.is_file():
            continue
        concept = read_json(concept_file)
        candidates.append(
            Candidate(
                concept_id=concept_id,
                document_id=document_id,
                score=0.0,
                rank=0,
                evidence_pages=sorted({int(p) for p in concept.get("page_numbers", [])}),
                description=str(concept.get("description") or ""),
            )
        )
    return candidates
