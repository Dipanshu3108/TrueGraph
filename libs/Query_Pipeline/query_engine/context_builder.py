"""Stage 7 — Context Builder (two-tier, token-budgeted).

Tier 1 — concept descriptions (cheap): every ranked candidate contributes its
stored ``description`` for breadth across all ``top_k_concepts``.

Tier 2 — raw evidence pages (expensive): only the pages already loaded by the
evidence stage (top ``top_k_evidence_pages`` candidates) contribute verbatim
text for grounding.

``max_context_tokens`` is a hard ceiling enforced here regardless of how many
candidates or pages were passed in — upstream limits alone are never assumed
to be sufficient. Tokens are estimated deterministically as ``ceil(chars / 4)``,
a standard conservative heuristic that keeps this stage free of tokenizer
dependencies.
"""

import logging
import math

from query_engine.types import Candidate, Evidence

logger = logging.getLogger(__name__)

#: Characters per token used by the deterministic estimator.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Deterministic token estimate: ``ceil(len(text) / CHARS_PER_TOKEN)``."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


def build_context(
    candidates: list[Candidate],
    evidence: list[Evidence],
    max_context_tokens: int,
) -> str:
    """Assemble the two-tier context, truncated against the hard ceiling.

    Tier 1 is emitted first (breadth across all candidates), then Tier 2
    evidence pages in rank order. Each block is included whole while it fits;
    the first block that would exceed the budget is truncated to the
    remaining allowance and assembly stops.
    """
    if max_context_tokens <= 0:
        raise ValueError("max_context_tokens must be > 0")

    blocks: list[str] = []
    used = 0
    exhausted = False

    def append_block(text: str) -> None:
        """Append a block within budget; truncate the final one and stop."""
        nonlocal used, exhausted
        if exhausted:
            return
        remaining = max_context_tokens - used
        if remaining <= 0:
            exhausted = True
            return
        cost = estimate_tokens(text)
        if cost <= remaining:
            blocks.append(text)
            used += cost
            return
        # Truncate the final block, reserving room for the suffix itself so
        # the ceiling is never exceeded.
        suffix = "\n[... truncated to fit max_context_tokens]"
        allowance = remaining * CHARS_PER_TOKEN - len(suffix)
        truncated = text[: max(0, allowance)].rstrip()
        if truncated:
            blocks.append(truncated + suffix)
        used = max_context_tokens
        exhausted = True

    append_block("# Knowledge Context")

    # Tier 1 — concept descriptions for every ranked candidate. Page-number
    # lists are intentionally not rendered: they are citation metadata, cost
    # tokens (a root concept can cite 100+ pages), and carry no knowledge for
    # the LLM. Provenance stays available via Candidate.evidence_pages.
    append_block("\n## Tier 1: Concept Descriptions")
    for position, candidate in enumerate(candidates, start=1):
        if exhausted:
            break
        append_block(
            f"\n{position}. Concept `{candidate.concept_id}` "
            f"(document: {candidate.document_id})\n"
            f"   {candidate.description}"
        )

    # Tier 2 — raw evidence pages, already relevance-scored and sorted by the
    # evidence stage (strongest page first), so the budget goes to the most
    # relevant pages rather than whichever pages sorted first numerically.
    if not exhausted:
        append_block("\n## Tier 2: Evidence Pages")
        for item in evidence:
            if exhausted:
                break
            append_block(
                f"\n### {item.document_id} — page {item.page_number}\n"
                f"{item.content}"
            )

    result = "\n".join(blocks)
    # Final mechanical guarantee: join separators and rounding must never
    # push the estimate past the hard ceiling.
    if estimate_tokens(result) > max_context_tokens:
        result = result[: max_context_tokens * CHARS_PER_TOKEN]
    return result
