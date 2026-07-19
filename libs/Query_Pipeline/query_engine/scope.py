"""Stage 1 — Scope Resolver.

Determines whether to search the global registry or only selected document
bundles. The scope is always returned as an explicit list of document ids so
downstream stages never re-interpret the user's intent.
"""

import json
from pathlib import Path
from typing import Union


def _load_document_ids(knowledge_path: str) -> list[str]:
    """Return all document ids registered in the global registry."""
    documents_file = Path(knowledge_path) / "registry" / "documents.json"
    if not documents_file.is_file():
        raise FileNotFoundError(
            f"Registry not found at {documents_file}. "
            "Run the Knowledge Builder first to populate the knowledge store."
        )
    with documents_file.open(encoding="utf-8") as fh:
        documents = json.load(fh)
    return sorted(documents.keys())


def resolve_scope(scope: Union[str, list[str]], knowledge_path: str) -> list[str]:
    """Resolve ``scope`` into a concrete list of document ids.

    ``"all"`` searches every document in the registry; a list of document
    names restricts the search to those bundles. Unknown document names are
    rejected loudly rather than silently dropped.
    """
    known = set(_load_document_ids(knowledge_path))

    if isinstance(scope, str):
        if scope == "all":
            return sorted(known)
        requested = [scope]
    elif isinstance(scope, (list, tuple)):
        requested = list(scope)
    else:
        raise TypeError("scope must be 'all' or a list of document names")

    if not requested:
        raise ValueError("scope must name at least one document")

    unknown = [name for name in requested if name not in known]
    if unknown:
        raise ValueError(
            f"Unknown document(s) in scope: {unknown}. "
            f"Available documents: {sorted(known)}"
        )
    return sorted(set(requested))
