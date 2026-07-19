"""TEXT output formatter."""

import json
from typing import Any, Dict


def format_text(document: Dict[str, Any]) -> str:
    """Return the document as TEXT matching the design spec."""
    lines = [
        f"FILE_NAME : {document['filename']}",
        f"METADATA : {json.dumps(document.get('metadata', []))}",
        "",
        "---------------------------------------------------",
    ]

    for page in document.get("pages", []):
        lines.append(f"PAGE_NO : {page['page_no']}")
        lines.append("")
        lines.append("CONTENT:")
        lines.append(page.get("content", ""))
        lines.append("---------------------------------------------------")

    return "\n".join(lines)
