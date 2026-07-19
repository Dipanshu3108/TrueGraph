"""Load parsed documents into the normalized page shape."""

import json
import logging
import re
from pathlib import Path

from knowledge_builder.exceptions import KnowledgeBuilderError
from knowledge_builder.types import Page


logger = logging.getLogger(__name__)


class DocumentLoadError(KnowledgeBuilderError):
    """Raised when the input file cannot be parsed."""


_IMAGE_PATH_PATTERN = re.compile(r"^.+\.(webp|png|jpe?g|gif|bmp)$", re.IGNORECASE)


def _classify_page(content: str) -> str:
    """Return ``"image"`` if the page content is a single image-file path.

    The rule is deliberately strict: the stripped content must be exactly one
    line ending in a known image extension. An image path embedded in prose
    classifies as text.
    """
    stripped = content.strip()
    if stripped and "\n" not in stripped and _IMAGE_PATH_PATTERN.match(stripped):
        return "image"
    return "text"


def _resolve_image_path(image_path: str, file_path: str, image_storage_path: str | None) -> str:
    """Resolve a possibly relative image path to an absolute one.

    Absolute paths (the parser's current output) are returned unchanged.
    Relative paths resolve against ``image_storage_path`` when configured,
    else against the parsed document's directory.
    """
    path = Path(image_path)
    if path.is_absolute():
        return str(path)
    root = Path(image_storage_path) if image_storage_path else Path(file_path).parent
    return str((root / path).resolve())


def _classify_and_resolve_pages(
    pages: list[Page], file_path: str, image_storage_path: str | None
) -> list[Page]:
    """Tag each page's ``content_type`` and absolutize image paths."""
    for page in pages:
        page.content_type = _classify_page(page.content)
        if page.content_type == "image":
            page.content = _resolve_image_path(page.content.strip(), file_path, image_storage_path)
    image_count = sum(1 for p in pages if p.content_type == "image")
    if image_count:
        logger.info("Classified %d image page(s) in %s", image_count, file_path)
    return pages


def _slugify(value: str) -> str:
    """Return a filesystem/registry-safe slug."""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def _parse_simple_metadata(text: str) -> dict[str, str]:
    """Parse lines like ``- key: value`` or ``- _No metadata_``."""
    metadata: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line == "---":
            continue
        if line.startswith("-"):
            line = line[1:].strip()
        if line.startswith("_") and line.endswith("_"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            metadata[key.strip()] = value.strip()
    return metadata


def _load_markdown(text: str, file_path: str) -> tuple[str, dict[str, str], list[Page]]:
    """Parse the UniversalDocumentParser markdown/text output shape."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("#"):
        raise DocumentLoadError(f"Missing file-name header in {file_path}")

    file_name = lines[0].lstrip("#").strip()
    metadata: dict[str, str] = {}
    pages: list[Page] = []

    i = 1
    # Skip blank lines after the file-name header.
    while i < len(lines) and lines[i].strip() == "":
        i += 1

    # Optional metadata block: starts with '## Metadata'
    if i < len(lines) and lines[i].strip().lower().startswith("## metadata"):
        i += 1
        metadata_lines: list[str] = []
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith("# Page ") or stripped.startswith("---"):
                break
            metadata_lines.append(lines[i])
            i += 1
        metadata = _parse_simple_metadata("\n".join(metadata_lines))
        # Skip optional separator after metadata block.
        if i < len(lines) and lines[i].strip() == "---":
            i += 1

    # Skip any blank lines / separators before the first page.
    while i < len(lines) and lines[i].strip() in {"", "---"}:
        i += 1

    # Now parse '# Page N' sections.
    current_page_number: int | None = None
    current_content_lines: list[str] = []

    def flush_page() -> None:
        nonlocal current_page_number, current_content_lines
        if current_page_number is not None:
            content = "\n".join(current_content_lines).strip()
            pages.append(Page(page_number=current_page_number, content=content))
            current_page_number = None
            current_content_lines = []

    while i < len(lines):
        line = lines[i]
        match = re.match(r"^#\s*Page\s+(\d+)\s*$", line, re.IGNORECASE)
        if match:
            flush_page()
            current_page_number = int(match.group(1))
        elif current_page_number is not None:
            current_content_lines.append(line)
        i += 1

    flush_page()
    return file_name, metadata, pages


def _load_json(text: str, file_path: str) -> tuple[str, dict[str, str], list[Page]]:
    """Parse the normalized JSON page shape."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DocumentLoadError(f"Invalid JSON in {file_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise DocumentLoadError(f"JSON root must be an object in {file_path}")

    file_name = data.get("file_name", Path(file_path).name)
    metadata = data.get("metadata", {})
    pages_data = data.get("pages", [])
    if not isinstance(pages_data, list):
        raise DocumentLoadError(f"'pages' must be a list in {file_path}")

    pages: list[Page] = []
    for entry in pages_data:
        if isinstance(entry, dict):
            pages.append(
                Page(
                    page_number=int(entry["page_number"]),
                    content=str(entry.get("content", "")),
                )
            )
        else:
            raise DocumentLoadError(f"Each page entry must be an object in {file_path}")

    return file_name, metadata, pages


def load_pages(
    file_path: str, image_storage_path: str | None = None
) -> tuple[str, dict[str, str], list[Page]]:
    """Parse ``.md`` / ``.txt`` / ``.json`` into ``(filename, metadata, pages)``.

    Each page is classified as ``content_type="image"`` when its content is a
    single-line image-file path, else ``"text"``. Relative image paths are
    resolved against ``image_storage_path`` (or the document's directory).

    No LLM calls are made here.
    """
    path = Path(file_path)
    if not path.is_file():
        raise DocumentLoadError(f"Input file not found: {file_path}")

    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix == ".json":
        file_name, metadata, pages = _load_json(text, file_path)
    elif suffix in {".md", ".txt"}:
        file_name, metadata, pages = _load_markdown(text, file_path)
    else:
        # Attempt markdown parsing for unknown extensions; it fails cleanly
        # if the shape is wrong.
        file_name, metadata, pages = _load_markdown(text, file_path)

    pages = _classify_and_resolve_pages(pages, file_path, image_storage_path)
    logger.info("Loaded %d page(s) from %s", len(pages), file_path)
    return file_name, metadata, pages
