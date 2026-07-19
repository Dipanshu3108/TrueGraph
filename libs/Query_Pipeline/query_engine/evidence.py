"""Stage 6 — Evidence Loader.

Closes the retrieval -> context gap: raw page text lives in each document
bundle's ``pages/`` folder, keyed by ``document_id`` + ``page_number``, and
this is the only stage that reads it. It reads pages **only** for the
top-ranked candidates (bounded by ``top_k_evidence_pages``), deduplicating
shared pages across concepts first — never for the full candidate list.

When a :class:`QueryIntent` is supplied, each unique page is also scored for
relevance with the same BM25 formulation the ranker uses (term overlap against
the intent's keywords/concepts), normalized to [0, 1]. Only the most relevant
pages are kept — a relative floor (``MIN_RELATIVE_SCORE`` x the top score)
drops near-irrelevant pages and a hard cap (``MAX_EVIDENCE_PAGES``) bounds the
total — so a single root concept citing 100+ pages cannot flood the context.
"""

import logging
import math
from pathlib import Path
from typing import Optional

from query_engine.ranker import BM25_B, BM25_K1, _query_terms
from query_engine.retriever import normalize_term, read_json
from query_engine.types import Candidate, Evidence, QueryIntent

logger = logging.getLogger(__name__)

#: Hard cap on the number of evidence pages kept after relevance scoring.
MAX_EVIDENCE_PAGES = 35

#: Pages scoring below this fraction of the top page's score are dropped.
MIN_RELATIVE_SCORE = 0.3


def _tokenize(text: str) -> list[str]:
    """Normalized term list for page content (cheap, split-based)."""
    return [normalize_term(tok) for tok in text.split() if normalize_term(tok)]


def _score_pages(evidence: list[Evidence], intent: QueryIntent) -> None:
    """BM25-score each page against the intent and normalize scores to [0, 1].

    Each page is a BM25 "document"; term frequency is the count of a query
    term in the page, document frequency is the number of pages containing the
    term, and length normalization uses the average page length. Scores are
    written onto ``Evidence.score`` in place, normalized so the best page is
    1.0. Pages with no query-term overlap stay at 0.0.
    """
    terms = _query_terms(intent)
    if not evidence or not terms:
        return

    tokenized = [_tokenize(item.content) for item in evidence]
    total_docs = len(evidence)
    avg_len = sum(len(toks) for toks in tokenized) / total_docs or 1.0

    # Document frequency per query term across the loaded pages.
    doc_freq: dict[str, int] = {term: 0 for term in terms}
    for toks in tokenized:
        present = set(toks)
        for term in terms:
            if term in present:
                doc_freq[term] += 1

    raw_scores: list[float] = []
    for toks in tokenized:
        doc_len = len(toks)
        counts: dict[str, int] = {}
        for tok in toks:
            counts[tok] = counts.get(tok, 0) + 1
        total = 0.0
        for term in terms:
            tf = counts.get(term, 0)
            if tf == 0:
                continue
            df = doc_freq.get(term, 0)
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            total += idf * (tf * (BM25_K1 + 1)) / (
                tf + BM25_K1 * (1 - BM25_B + BM25_B * doc_len / avg_len)
            )
        raw_scores.append(total)

    top = max(raw_scores) if raw_scores else 0.0
    for item, raw in zip(evidence, raw_scores):
        item.score = (raw / top) if top > 0.0 else 0.0


def load_evidence(
    candidates: list[Candidate],
    knowledge_path: str,
    top_k_evidence_pages: int,
    intent: Optional[QueryIntent] = None,
) -> list[Evidence]:
    """Read raw page text for the top ``top_k_evidence_pages`` candidates.

    Candidates are expected in fused-rank order. ``(document_id,
    page_number)`` pairs are deduplicated before any read, so a page cited by
    multiple concepts is loaded exactly once. Missing page files are skipped
    rather than failing the query.

    When ``intent`` is provided, the loaded pages are relevance-scored,
    filtered to the strongest ``MAX_EVIDENCE_PAGES`` pages above the
    ``MIN_RELATIVE_SCORE`` floor, and returned sorted by descending score.
    When ``intent`` is ``None``, pages are returned unscored in candidate
    order (legacy behaviour).
    """
    if top_k_evidence_pages < 0:
        raise ValueError("top_k_evidence_pages must be >= 0")

    logger.debug("Loading evidence: top_k=%d, candidates=%d", top_k_evidence_pages, len(candidates))

    store = Path(knowledge_path)
    seen: set[tuple[str, int]] = set()
    evidence: list[Evidence] = []

    for candidate in candidates[:top_k_evidence_pages]:
        for page_number in sorted(candidate.evidence_pages):
            key = (candidate.document_id, page_number)
            if key in seen:
                continue
            seen.add(key)
            page_file = store / candidate.document_id / "pages" / f"{page_number}.json"
            if not page_file.is_file():
                logger.debug("Page not found: %s", page_file)
                continue
            page = read_json(page_file)
            evidence.append(
                Evidence(
                    document_id=candidate.document_id,
                    page_number=page_number,
                    content=str(page.get("content") or ""),
                )
            )

    if intent is not None and evidence:
        _score_pages(evidence, intent)
        top_score = max(item.score for item in evidence)
        floor = MIN_RELATIVE_SCORE * top_score
        evidence = [item for item in evidence if item.score >= floor and item.score > 0.0]
        evidence.sort(
            key=lambda item: (-item.score, item.document_id, item.page_number)
        )
        evidence = evidence[:MAX_EVIDENCE_PAGES]
        logger.info(
            "Evidence relevance filter: kept %d page(s) (top score %.3f, floor %.3f).",
            len(evidence), top_score, floor,
        )

    logger.info("Evidence loading complete: %d page(s) loaded.", len(evidence))
    return evidence
