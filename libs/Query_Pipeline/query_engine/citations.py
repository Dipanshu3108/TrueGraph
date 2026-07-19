"""Stage 9 — Citation Builder.

Produces page-level citations with full provenance: every page referenced by
the final candidate list is cited, mapped back to the concepts that cite it,
and flagged when its raw text was actually loaded into the context.
"""

import logging
from typing import Any

from query_engine.types import Candidate, Evidence

logger = logging.getLogger(__name__)


def build_citations(candidates: list[Candidate], evidence: list[Evidence]) -> list[dict[str, Any]]:
    """Build page-level citations from the ranked candidates and evidence.

    Each citation records the source document, the page number, the concepts
    (in rank order) that point at that page, and whether the page's raw text
    was loaded as Tier 2 evidence. Order follows candidate rank, then page
    number, so the most relevant sources come first.
    """
    logger.debug("Building citations for %d candidates and %d evidence pages.",
                 len(candidates), len(evidence))
    
    loaded = {(item.document_id, item.page_number) for item in evidence}

    citations: list[dict[str, Any]] = []
    index: dict[tuple[str, int], dict[str, Any]] = {}
    for candidate in candidates:
        for page_number in candidate.evidence_pages:
            key = (candidate.document_id, page_number)
            citation = index.get(key)
            if citation is None:
                citation = {
                    "document_id": candidate.document_id,
                    "page_number": page_number,
                    "concepts": [],
                    "evidence_loaded": key in loaded,
                }
                index[key] = citation
                citations.append(citation)
            if candidate.concept_id not in citation["concepts"]:
                citation["concepts"].append(candidate.concept_id)
    
    logger.info("Citations built: %d page(s) cited.", len(citations))
    return citations
