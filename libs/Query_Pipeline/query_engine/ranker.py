"""Stage 5 — Candidate Ranking (BM25 + Reciprocal Rank Fusion).

Three independently computable signals, fused with RRF (k = 60):

1. BM25 over the document-local inverted keyword indexes — handles
   partial/fuzzy term overlap far better than exact match.
2. Alias-expanded exact match — candidates whose concept id or alias exactly
   matches a query term.
3. Graph proximity — candidates ranked by relationship distance from the
   query's seed concepts, closer = better rank.

"""

import logging
import math
from pathlib import Path

from query_engine.retriever import (
    build_adjacency,
    load_registry,
    read_json,
    resolve_seeds,
    graph_distances,
    normalize_term,
    slugify,
)
from query_engine.types import Candidate, QueryIntent
logger = logging.getLogger(__name__)

#: RRF fusion constant — 60 is the standard default.
RRF_K = 60

#: Standard BM25 tuning constants.
BM25_K1 = 1.5
BM25_B = 0.75


def _query_terms(intent: QueryIntent) -> list[str]:
    """Normalized, deduplicated query terms from the intent."""
    terms = [normalize_term(t) for t in list(intent.keywords) + list(intent.concepts)]
    return [t for t in dict.fromkeys(terms) if t]


def bm25_ranking(candidates: list[Candidate], intent: QueryIntent, knowledge_path: str) -> list[Candidate]:
    """Rank candidates with BM25 over the inverted keyword index.

    Each concept is a BM25 "document" whose terms are its keywords in the
    document-local ``keyword_index.json``. Term frequency is binary (the
    inverted index records membership, not counts); document frequency and
    length normalization come from the full keyword indexes of the documents
    the candidates belong to.
    """
    if not candidates:
        return []

    store = Path(knowledge_path)
    document_ids = sorted({c.document_id for c in candidates})

    # Invert each document's keyword index: concept -> set of keywords.
    concept_keywords: dict[tuple[str, str], set[str]] = {}
    postings: dict[str, set[tuple[str, str]]] = {}
    for document_id in document_ids:
        keyword_file = store / document_id / "indexes" / "keyword_index.json"
        if not keyword_file.is_file():
            continue
        for keyword, concept_ids in read_json(keyword_file).items():
            term = normalize_term(keyword)
            for concept_id in concept_ids:
                key = (concept_id, document_id)
                concept_keywords.setdefault(key, set()).add(term)
                postings.setdefault(term, set()).add(key)

    total_docs = len(concept_keywords)
    if total_docs == 0:
        return []
    avg_len = sum(len(kws) for kws in concept_keywords.values()) / total_docs

    def score(candidate: Candidate) -> float:
        key = (candidate.concept_id, candidate.document_id)
        keywords = concept_keywords.get(key, set())
        if not keywords:
            return 0.0
        doc_len = len(keywords)
        total = 0.0
        for term in _query_terms(intent):
            if term not in keywords:
                continue
            df = len(postings.get(term, ()))
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            tf = 1.0  # inverted index membership is binary
            total += idf * (tf * (BM25_K1 + 1)) / (tf + BM25_K1 * (1 - BM25_B + BM25_B * doc_len / avg_len))
        return total

    scored = [(score(c), c) for c in candidates]
    scored = [item for item in scored if item[0] > 0.0]
    scored.sort(key=lambda item: (-item[0], item[1].concept_id, item[1].document_id))
    return [c for _, c in scored]


def alias_ranking(candidates: list[Candidate], intent: QueryIntent, knowledge_path: str) -> list[Candidate]:
    """Rank candidates whose concept id or alias exactly matches a query term."""
    if not candidates:
        return []

    store = Path(knowledge_path)
    terms = _query_terms(intent)
    slugs = {slugify(t) for t in terms}

    alias_indexes: dict[str, dict] = {}
    for document_id in sorted({c.document_id for c in candidates}):
        alias_file = store / document_id / "indexes" / "alias_index.json"
        alias_indexes[document_id] = read_json(alias_file) if alias_file.is_file() else {}

    def match_count(candidate: Candidate) -> int:
        count = 0
        aliases = alias_indexes.get(candidate.document_id, {})
        for term in terms:
            if aliases.get(term) == candidate.concept_id:
                count += 1
            elif slugify(term) == candidate.concept_id:
                count += 1
        return count

    matched = [(match_count(c), c) for c in candidates]
    matched = [item for item in matched if item[0] > 0]
    matched.sort(key=lambda item: (-item[0], item[1].concept_id, item[1].document_id))
    return [c for _, c in matched]


def graph_ranking(
    candidates: list[Candidate],
    intent: QueryIntent,
    knowledge_path: str,
    relationship_depth: int,
) -> list[Candidate]:
    """Rank candidates by relationship distance from the seed concepts."""
    if not candidates or relationship_depth < 0:
        return []

    registry_aliases, _, graph = load_registry(knowledge_path)
    local_aliases = {
        document_id: (
            read_json(Path(knowledge_path) / document_id / "indexes" / "alias_index.json")
            if (Path(knowledge_path) / document_id / "indexes" / "alias_index.json").is_file()
            else {}
        )
        for document_id in sorted({c.document_id for c in candidates})
    }
    seeds = resolve_seeds(intent.concepts, registry_aliases, local_aliases)
    distances = graph_distances(sorted(seeds), build_adjacency(graph), relationship_depth)

    ranked = [
        (distances[c.concept_id], c)
        for c in candidates
        if c.concept_id in distances
    ]
    ranked.sort(key=lambda item: (item[0], item[1].concept_id, item[1].document_id))
    return [c for _, c in ranked]


def rank_candidates(
    candidates: list[Candidate],
    intent: QueryIntent,
    knowledge_path: str,
    relationship_depth: int = 1,
) -> list[Candidate]:
    """Fuse the BM25, alias, and graph rankings with Reciprocal Rank Fusion.

    ``RRF_score(candidate) = sum over signals of 1 / (k + rank_i)`` where
    ``rank_i`` is the candidate's 1-indexed position in signal ``i``'s list;
    candidates absent from a list contribute nothing for it. The fused score
    and 1-indexed final rank are written back onto each candidate.
    """
    if not isinstance(candidates, list):
        raise TypeError("candidates must be a list of Candidate")
    if not isinstance(intent, QueryIntent):
        raise TypeError("intent must be a QueryIntent")
    if not candidates:
        logger.debug("No candidates to rank.")
        return []

    logger.debug("Computing ranking signals for %d candidates...", len(candidates))
    signal_lists = [
        bm25_ranking(candidates, intent, knowledge_path),
        alias_ranking(candidates, intent, knowledge_path),
        graph_ranking(candidates, intent, knowledge_path, relationship_depth),
    ]

    rrf_scores: dict[tuple[str, str], float] = {}
    for ranked in signal_lists:
        for position, candidate in enumerate(ranked, start=1):
            key = (candidate.concept_id, candidate.document_id)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (RRF_K + position)

    logger.debug("RRF fusion: %d candidates scored.", len(rrf_scores))

    ordered = sorted(
        candidates,
        key=lambda c: (
            -rrf_scores.get((c.concept_id, c.document_id), 0.0),
            c.concept_id,
            c.document_id,
        ),
    )
    for position, candidate in enumerate(ordered, start=1):
        candidate.score = rrf_scores.get((candidate.concept_id, candidate.document_id), 0.0)
        candidate.rank = position
    return ordered
