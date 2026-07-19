"""Text cleanup pipeline for extracted document content."""

import re
import unicodedata
from typing import List, Dict, Any


LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "ft",
    "ﬆ": "st",
}

# Dashes that can act as minus signs in numeric contexts.
DASH_CHARS = "\u2012\u2013\u2014\u2212"  # figure dash, en dash, em dash, minus sign


def normalize_unicode(text: str) -> str:
    """Apply NFKC Unicode normalization."""
    return unicodedata.normalize("NFKC", text)


def fix_ligatures(text: str) -> str:
    """Replace common typographic ligatures with ASCII equivalents."""
    for lig, repl in LIGATURES.items():
        text = text.replace(lig, repl)
    return text


def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces/tabs, trim lines, and remove trailing whitespace."""
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        line = line.strip()
        # collapse internal whitespace
        line = re.sub(r"[ \t]+", " ", line)
        cleaned.append(line)
    return "\n".join(cleaned)


def normalize_dashes(text: str) -> str:
    """Replace typographic dashes with ASCII hyphen-minus in numeric/scientific contexts."""
    # Replace dashes between digits or after a caret (exponent notation).
    pattern = re.compile(rf"(?<=\d|[\^eE])([{DASH_CHARS}])(?=\d)")
    return pattern.sub("-", text)


def normalize_scientific_notation(text: str) -> str:
    """Normalize superscript/exponent markers into caret notation.

    Converts patterns such as '10^‒43' -> '10^-43' and cleans repeated carets.
    """
    text = normalize_dashes(text)
    # Collapse repeated carets and remove caret before a plain ASCII minus.
    text = re.sub(r"\^\^+", "^", text)
    text = re.sub(r"\^\+-", "^-", text)
    return text


def remove_duplicate_blank_lines(text: str) -> str:
    """Collapse three or more consecutive blank lines into two."""
    return re.sub(r"\n{3,}", "\n\n", text)


def merge_broken_paragraphs(text: str) -> str:
    """Merge lines that look like a single broken paragraph.

    Preserves list markers, code blocks, and short lines ending with punctuation.
    """
    lines = text.splitlines()
    if not lines:
        return text

    list_marker = re.compile(r"^(\s*)([-*+]|\d+[.\)])\s+")
    code_fence = re.compile(r"^\s*```")
    heading = re.compile(r"^\s*#{1,6}\s+")

    merged: List[str] = []
    in_code_block = False

    for line in lines:
        if code_fence.match(line):
            in_code_block = not in_code_block
            merged.append(line)
            continue

        if in_code_block or not line.strip():
            merged.append(line)
            continue

        if list_marker.match(line) or heading.match(line):
            merged.append(line)
            continue

        if merged:
            prev = merged[-1]
            if (
                prev
                and not prev.endswith(".")
                and not prev.endswith(":")
                and not prev.endswith("?")
                and not prev.endswith("!")
                and not list_marker.match(prev)
                and not heading.match(prev)
                and len(line) < 120
            ):
                merged[-1] = prev + " " + line
                continue
        merged.append(line)

    return "\n".join(merged)


def _find_repeated_lines(pages: List[Dict[str, Any]], min_occurrences: int) -> set:
    """Find lines that appear repeatedly at the top or bottom of most pages."""
    occurrences: Dict[str, int] = {}
    positions: Dict[str, List[float]] = {}

    for page in pages:
        content = page.get("content", "")
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        if not lines:
            continue

        for idx, line in enumerate(lines):
            occurrences[line] = occurrences.get(line, 0) + 1
            # Normalized position: 0 = top, 1 = bottom
            pos = idx / max(len(lines) - 1, 1)
            positions.setdefault(line, []).append(pos)

    repeated = set()
    total = len(pages)
    for line, count in occurrences.items():
        if count < min_occurrences or count < total * 0.5:
            continue
        avg_pos = sum(positions[line]) / len(positions[line])
        # Keep only lines that consistently appear near top or bottom.
        if avg_pos < 0.15 or avg_pos > 0.85:
            repeated.add(line)
    return repeated


def remove_headers_footers(
    pages: List[Dict[str, Any]], min_occurrences: int = 3
) -> List[Dict[str, Any]]:
    """Remove repeated header/footer lines from each page."""
    if len(pages) < min_occurrences:
        return pages

    repeated = _find_repeated_lines(pages, min_occurrences)
    if not repeated:
        return pages

    cleaned_pages = []
    for page in pages:
        lines = page.get("content", "").splitlines()
        new_lines = [ln for ln in lines if ln.strip() not in repeated]
        cleaned_pages.append({"page_no": page["page_no"], "content": "\n".join(new_lines)})
    return cleaned_pages


def cleanup_page(text: str) -> str:
    """Run the full cleanup pipeline on a single page string."""
    text = normalize_unicode(text)
    text = fix_ligatures(text)
    text = normalize_whitespace(text)
    text = merge_broken_paragraphs(text)
    text = remove_duplicate_blank_lines(text)
    text = normalize_scientific_notation(text)
    return text.strip()


def cleanup_document(document: Dict[str, Any], min_occurrences: int = 3) -> Dict[str, Any]:
    """Apply cleanup to every page and remove repeated headers/footers."""
    pages = document.get("pages", [])
    cleaned_pages = [
        {"page_no": p["page_no"], "content": cleanup_page(p.get("content", ""))}
        for p in pages
    ]
    cleaned_pages = remove_headers_footers(cleaned_pages, min_occurrences)
    return {
        "filename": document["filename"],
        "metadata": document.get("metadata", []),
        "pages": cleaned_pages,
    }
