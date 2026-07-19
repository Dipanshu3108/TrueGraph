"""Query Engine: deterministic, explainable Q&A over OKF knowledge bundles.

No embeddings, no vector databases — answers are grounded in concepts,
relationships, deterministic indexes, and page-level evidence. The only
public entry point is :func:`ask`.
"""

from query_engine.entry import ask
from query_engine.types import QueryResult

__all__ = ["ask", "QueryResult"]
