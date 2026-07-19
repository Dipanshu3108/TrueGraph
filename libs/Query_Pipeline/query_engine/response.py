"""Final stage — assemble the public :class:`QueryResult`.

Preserves provenance: ``documents_used`` and ``concepts_used`` are derived
from the exact candidates that fed the context builder, in fused-rank order.
"""

from query_engine.types import Candidate, QueryResult


def build_response(answer: str, citations: list[dict], candidates: list[Candidate]) -> QueryResult:
    """Assemble the :class:`QueryResult` returned by ``ask()``."""
    documents_used = sorted({c.document_id for c in candidates})
    concepts_used = [c.concept_id for c in candidates]
    return QueryResult(
        answer=answer,
        citations=list(citations),
        documents_used=documents_used,
        concepts_used=concepts_used,
    )
