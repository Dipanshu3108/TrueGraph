"""MARKDOWN output formatter."""

from typing import Any, Dict


def format_markdown(document: Dict[str, Any]) -> str:
    """Return the document as MARKDOWN matching the design spec."""
    lines = [f"# {document['filename']}", "", "## Metadata", ""]

    metadata = document.get("metadata", [])
    if metadata:
        for item in metadata:
            lines.append(f"- {item}")
    else:
        lines.append("- _No metadata_")

    lines.extend(["", "---", ""])

    for page in document.get("pages", []):
        lines.append(f"# Page {page['page_no']}")
        lines.append("")
        lines.append(page.get("content", ""))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
