"""Stage 2 — Query Understanding.

Uses the LLM (and only here, plus answer generation) to extract intent,
concepts, keywords and filters from the natural language question. Falls back
to a deterministic keyword split if the LLM call or JSON parse fails, so a
provider hiccup can never take the whole pipeline down.
"""

import logging
import re
from typing import Optional

from query_engine.llm import build_provider, run_sync
from query_engine.types import QueryIntent
from query_engine.usage import UsageTracker

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the query-understanding stage of a deterministic knowledge pipeline.

Extract structured retrieval information from the user's question and respond
with a single JSON object of exactly this shape:
{
  "intent": "<one short label, e.g. definition | explanation | comparison | listing | how-to | fact-lookup>",
  "keywords": ["<important content terms from the question, lowercase, including multi-word terms>"],
  "concepts": ["<named entities / domain concepts the question is about>"],
  "filters": {}
}

Rules:
- keywords are used for full-text matching; include synonyms or close variants
  when the question paraphrases likely document vocabulary.
- concepts are used for exact concept and alias lookup; use the canonical
  names a knowledge base would use.
- filters is usually {}; only add a key when the question explicitly
  constrains the search (e.g. {"document": "..."}).
- Respond with JSON only, no prose."""

_WORD_RE = re.compile(r"[a-z0-9]+")


def _fallback_intent(query: str) -> QueryIntent:
    """Deterministic intent used when the LLM call fails."""
    keywords = [w for w in _WORD_RE.findall(query.lower()) if len(w) > 2]
    return QueryIntent(intent="fact-lookup", keywords=keywords, concepts=[], filters={})


def understand_query(
    query: str,
    config: dict,
    tracker: Optional[UsageTracker] = None,
) -> QueryIntent:
    """Extract a :class:`QueryIntent` from the natural language question."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")

    provider = build_provider(config)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]
    try:
        logger.debug("Calling LLM for query understanding...")
        data = run_sync(provider.complete_json(messages))
        if tracker is not None:
            input_tok, output_tok = provider.get_last_usage()
            logger.debug("Query understanding tokens: %d input, %d output", input_tok, output_tok)
            tracker.record(
                model=str(config.get("model_name") or "unknown"),
                provider=config.get("provider"),
                input_tokens=input_tok,
                output_tokens=output_tok,
            )
        return QueryIntent(
            intent=str(data.get("intent") or "fact-lookup"),
            keywords=[str(k) for k in data.get("keywords") or []],
            concepts=[str(c) for c in data.get("concepts") or []],
            filters=dict(data.get("filters") or {}),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Query understanding failed (%s); using keyword fallback.", exc)
        return _fallback_intent(query)
