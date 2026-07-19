"""JSON output formatter."""

import json
from typing import Any, Dict


def format_json(document: Dict[str, Any]) -> Dict[str, Any]:
    """Return the document as the JSON structure from the design spec."""
    return {
        "FileName": document["filename"],
        "Metadata": document.get("metadata", []),
        "FileContent": [
            {"page_no": p["page_no"], "content": p.get("content", "")}
            for p in document.get("pages", [])
        ],
    }


def format_json_string(document: Dict[str, Any], **kwargs: Any) -> str:
    """Return the JSON representation as a formatted string."""
    kwargs.setdefault("indent", 2)
    kwargs.setdefault("ensure_ascii", False)
    return json.dumps(format_json(document), **kwargs)
