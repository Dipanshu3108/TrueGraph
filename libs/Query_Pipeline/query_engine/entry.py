"""Public orchestration entry point for the Q&A pipeline.

``ask()`` wires the stages together in the order fixed by the design spec:

    scope -> understanding -> plan -> retrieve -> rank (BM25 + RRF)
    -> evidence (top-N only) -> context (two-tier, budgeted)
    -> generate -> citations -> QueryResult
"""

import json
import logging
from pathlib import Path
from typing import Union

from query_engine.citations import build_citations
from query_engine.context_builder import build_context
from query_engine.evidence import load_evidence
from query_engine.generator import generate_answer
from query_engine.planner import build_retrieval_plan
from query_engine.ranker import rank_candidates
from query_engine.response import build_response
from query_engine.retriever import retrieve_candidates
from query_engine.scope import resolve_scope
from query_engine.types import QueryResult
from query_engine.understanding import understand_query
from query_engine.usage import UsageTracker

logger = logging.getLogger(__name__)

#: Deterministic answer when retrieval finds nothing to ground on.
_NO_RESULTS_ANSWER = (
    "No relevant information was found in the knowledge store for this query. "
    "The deterministic indexes returned no matching concepts, so no grounded "
    "answer can be given."
)

#: Optional directory for saving stage outputs for observation/debugging.
_OBSERVATION_DIR = Path("path/to/observation_dir")  # Replace with your desired path


def _save_stage_output(stage_name: str, data: any) -> None:
    """Save stage output to a text file for observation."""
    if not _OBSERVATION_DIR.exists():
        return
    
    output_file = _OBSERVATION_DIR / f"{stage_name}.txt"
    try:
        if isinstance(data, str):
            content = data
        elif isinstance(data, (list, dict)):
            content = json.dumps(data, indent=2, default=str)
        else:
            content = str(data)
        
        output_file.write_text(content, encoding="utf-8")
        logger.debug("Saved stage output: %s", output_file)
    except Exception as exc:
        logger.warning("Failed to save stage output %s: %s", stage_name, exc)


def ask(query: str, scope: Union[str, list[str]], config: dict) -> QueryResult:
    """Answer a natural language question over the OKF knowledge store.

    Args:
        query: Natural language question.
        scope: ``"all"`` or a list of document names to search.
        config: Pipeline configuration — model keys (``model_name``,
            ``provider``, ``api_key``, ``base_url``, ...) plus retrieval knobs
            ``knowledge_store_path``, ``top_k_concepts``,
            ``top_k_evidence_pages``, ``max_context_tokens`` and
            ``relationship_depth``.

    Returns:
        A :class:`QueryResult` with the grounded answer, page-level
        citations, and the documents/concepts used.
    """
    if not isinstance(config, dict):
        raise TypeError("config must be a dict")
    knowledge_path = str(config.get("knowledge_store_path", "./knowledge"))
    top_k_concepts = int(config.get("top_k_concepts", 25))
    top_k_evidence_pages = int(config.get("top_k_evidence_pages", 5))
    max_context_tokens = int(config.get("max_context_tokens", 6000))
    relationship_depth = int(config.get("relationship_depth", 1))
    usage_document_name = str(config.get("usage_document_name") or query)
    usage_dir = config.get("usage_dir")
    tracker = UsageTracker(document_name=usage_document_name, usage_dir=usage_dir)

    # 1. Scope Resolver.
    resolved_scope = resolve_scope(scope, knowledge_path)
    # _save_stage_output("01_resolved_scope", resolved_scope)

    # 2. Query Understanding (LLM).
    intent = understand_query(query, config, tracker=tracker)
    # _save_stage_output("02_intent", intent)

    # 3. Retrieval Planner.
    plan = build_retrieval_plan(intent, resolved_scope)
    plan.relationship_depth = relationship_depth
    # _save_stage_output("03_plan", plan)

    # 4. Deterministic Retrieval.
    candidates = retrieve_candidates(plan, knowledge_path)
    # _save_stage_output("04_candidates", candidates)

    # 5. Candidate Ranking (BM25 + alias + graph, fused via RRF).
    ranked = rank_candidates(candidates, intent, knowledge_path, plan.relationship_depth)
    ranked = ranked[:top_k_concepts]
    # _save_stage_output("05_ranked", ranked)
    logger.info(
        "Query pipeline: %d candidate(s) retrieved, %d kept after ranking.",
        len(candidates),
        len(ranked),
    )

    if not ranked:
        tracker.write_log()
        return build_response(_NO_RESULTS_ANSWER, [], [])

    # 6. Evidence Loader — raw pages for the top-ranked candidates only,
    #    relevance-scored against the intent and capped to the strongest pages.
    evidence = load_evidence(ranked, knowledge_path, top_k_evidence_pages, intent=intent)
    # _save_stage_output("06_evidence", evidence)

    # 7. Context Builder — two-tier, hard token ceiling.
    context = build_context(ranked, evidence, max_context_tokens)
    # _save_stage_output("07_context", context)

    # 8. Answer Generator (LLM, context-only).
    logger.info("Stage 8: Generating answer (context_size=%d chars)...", len(context))
    answer = generate_answer(query, context, config, tracker=tracker)
    # _save_stage_output("08_answer", answer)
    logger.debug("Generated answer length: %d chars", len(answer))

    # 9. Citation Builder.
    logger.info("Stage 9: Building citations...")
    citations = build_citations(ranked, evidence)
    # _save_stage_output("09_citations", citations)
    logger.info("Built %d citation(s).", len(citations))

    tracker.write_log()
    logger.info("Query pipeline complete. Final result: answer=%d chars, %d docs, %d concepts.",
                len(answer), len(set(c.document_id for c in ranked)), len(ranked))
    return build_response(answer, citations, ranked)
