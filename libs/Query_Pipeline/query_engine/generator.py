"""Stage 8 — Answer Generator.

Synthesizes the final answer from the retrieved context only. The model is
instructed to make no unsupported claims and to say so when the context is
insufficient — the LLM is used for synthesis, never as a knowledge source.
"""

import logging
from typing import Optional

from query_engine.llm import build_provider, run_sync
from query_engine.usage import UsageTracker

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the answer-generation stage of a deterministic knowledge pipeline.

Answer the user's question using ONLY the provided knowledge context. Rules:
- Every claim must be supported by the context; make no unsupported claims.
- When you use a concept or page, cite it inline as [concept-id, document, p.N].
- If the context is insufficient to answer, say so explicitly and state what
  is missing — do not fill gaps with outside knowledge.
- Be concise and direct."""


def generate_answer(
    question: str,
    context: str,
    config: dict,
    tracker: Optional[UsageTracker] = None,
) -> str:
    """Generate an answer grounded exclusively in the retrieved context."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")

    provider = build_provider(config)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Knowledge context:\n\n{context}\n\n"
                f"---\nQuestion: {question}"
            ),
        },
    ]
    answer = run_sync(provider.complete(messages))
    if tracker is not None:
        input_tok, output_tok = provider.get_last_usage()
        logger.debug("Answer generation tokens: %d input, %d output", input_tok, output_tok)
        tracker.record(
            model=str(config.get("model_name") or "unknown"),
            provider=config.get("provider"),
            input_tokens=input_tok,
            output_tokens=output_tok,
        )
    return answer
