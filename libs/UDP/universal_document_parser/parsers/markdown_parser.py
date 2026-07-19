"""Markdown parser."""

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..cleanup.text_cleanup import cleanup_page
from ..exceptions import ParseError


class MarkdownParser:
    """Parse Markdown files as a single-page document."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def parse(self, path: str) -> List[Dict[str, Any]]:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except Exception as exc:
            raise ParseError(f"Failed to read Markdown {path}: {exc}") from exc

        return [{"page_no": 1, "content": cleanup_page(text)}]
