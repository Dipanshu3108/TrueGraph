"""Stage 3 — Retrieval Planner.

Builds the deterministic retrieval strategy from the query intent. The plan
is a pure function of the intent and the resolved scope; the actual alias
expansion and graph traversal happen in the retrieval stage, which is the
stage that has access to the knowledge store.
"""

import logging

from query_engine.types import QueryIntent, RetrievalPlan

logger = logging.getLogger(__name__)

#: Default graph-expansion depth when the config does not override it.
DEFAULT_RELATIONSHIP_DEPTH = 1


def build_retrieval_plan(intent: QueryIntent, scope: list[str]) -> RetrievalPlan:
    """Assemble the retrieval plan for the resolved scope.

    ``relationship_depth`` defaults to :data:`DEFAULT_RELATIONSHIP_DEPTH`;
    the orchestration layer overwrites it with the config value, keeping this
    signature a pure ``(intent, scope) -> plan`` mapping.
    """
    if not isinstance(intent, QueryIntent):
        raise TypeError("intent must be a QueryIntent")
    if not scope:
        raise ValueError("scope must contain at least one document id")

    # Deduplicate while preserving order — the same term often appears as
    # both a keyword and a concept.
    concepts = list(dict.fromkeys(intent.concepts))
    keywords = list(dict.fromkeys(intent.keywords))

    logger.debug(
        "Building plan: intent=%s, scope=%s, concepts=%d, keywords=%d",
        intent.intent, scope, len(concepts), len(keywords)
    )

    return RetrievalPlan(
        scope=list(scope),
        concepts=concepts,
        keywords=keywords,
        relationship_depth=DEFAULT_RELATIONSHIP_DEPTH,
    )
