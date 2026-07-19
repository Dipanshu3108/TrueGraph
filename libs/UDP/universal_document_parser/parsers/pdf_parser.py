"""PDF parser with cascading fallback and optional OCR."""

import io
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..cleanup.text_cleanup import cleanup_page, normalize_scientific_notation
from ..config import DEFAULT_CONFIG
from ..exceptions import DependencyError, ParseError
from ..logger import get_logger

logger = get_logger()


def _sanitize_filename(name: str) -> str:
    """Return a filesystem-safe version of a file name."""
    # Replace characters that are illegal on common file systems.
    sanitized = re.sub(r'[\\/:*?"<>|]', "_", name)
    return sanitized.strip(". ") or "document"

# Silence chatty third-party loggers by default.
logging.getLogger("pdfminer").setLevel(logging.WARNING)

try:
    import fitz  # PyMuPDF
except ImportError as exc:  # pragma: no cover
    fitz = None  # type: ignore

try:
    import pdfplumber
except ImportError as exc:  # pragma: no cover
    pdfplumber = None  # type: ignore

try:
    import pytesseract
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    pytesseract = None  # type: ignore
    Image = None  # type: ignore


def _is_superscript_span(span: Dict[str, Any], dominant_size: float, dominant_y: float) -> bool:
    """Determine whether a span is superscript based on flags, size, and baseline."""
    if not span.get("text"):
        return False
    if span["flags"] & 1:
        return True
    if dominant_size > 0 and span["size"] < dominant_size * 0.85:
        if span["origin"][1] < dominant_y - 1:
            return True
    return False


class PDFParser:
    """Parse PDF files using a cascading extraction strategy."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self._pdfplumber_doc: Optional[Any] = None
        self._fitz_doc: Optional[Any] = None

    def parse(self, path: str) -> List[Dict[str, Any]]:
        """Return a list of page dicts for the given PDF."""
        if fitz is None:
            raise DependencyError(
                "PyMuPDF (fitz) is required for PDF parsing. Install it with: pip install pymupdf"
            )

        pages: List[Dict[str, Any]] = []
        try:
            doc = fitz.open(path)
        except Exception as exc:
            raise ParseError(f"Failed to open PDF {path}: {exc}") from exc

        min_chars = self.config.get("min_chars_per_page", 50)
        min_words = self.config.get("min_words_per_page", 10)
        enable_ocr = self.config.get("enable_ocr", True)
        ocr_dpi = self.config.get("ocr_dpi", 200)
        use_pdfplumber = self.config.get("pdf_use_pdfplumber_primary", True) and pdfplumber is not None

        try:
            for page_number in range(len(doc)):
                fitz_page = doc.load_page(page_number)

                if use_pdfplumber:
                    text = self._extract_with_pdfplumber(path, page_number)
                    superscripts = self._detect_superscripts(fitz_page)
                    text = self._insert_superscript_carets(text, superscripts)
                else:
                    text = self._extract_with_layout(fitz_page)

                text = cleanup_page(text)

                if self._is_poor(text, min_chars, min_words):
                    logger.debug(
                        "Page %s: extraction result poor, attempting OCR", page_number + 1
                    )
                    if enable_ocr:
                        ocr_text = self._ocr_page(fitz_page, ocr_dpi)
                        ocr_text = cleanup_page(ocr_text)
                        if self._is_better(ocr_text, text, min_chars, min_words):
                            text = ocr_text

                pages.append({"page_no": page_number + 1, "content": text})
        finally:
            doc.close()
            self._close_pdfplumber()

        return pages

    def convert_to_images(self, path: str, output_dir: str) -> List[Dict[str, Any]]:
        """Render each PDF page to an image and return page dicts with image paths.

        Args:
            path: Path to the PDF file.
            output_dir: Directory under which a per-file subfolder will be created.

        Returns:
            List of page dicts where ``content`` is the saved image path.
        """
        if fitz is None:
            raise DependencyError(
                "PyMuPDF (fitz) is required for PDF image conversion. "
                "Install it with: pip install pymupdf"
            )
        if Image is None:
            raise DependencyError(
                "Pillow is required for PDF image conversion. "
                "Install it with: pip install Pillow"
            )

        try:
            doc = fitz.open(path)
        except Exception as exc:
            raise ParseError(f"Failed to open PDF {path}: {exc}") from exc

        dpi = self.config.get("image_dpi", 200)
        fmt = self.config.get("image_format", "webp").lower()
        base_name = Path(path).stem
        safe_name = _sanitize_filename(base_name)
        storage_dir = Path(output_dir) / safe_name
        storage_dir.mkdir(parents=True, exist_ok=True)

        pages: List[Dict[str, Any]] = []
        try:
            for page_number in range(len(doc)):
                fitz_page = doc.load_page(page_number)
                page_label = page_number + 1
                image_filename = f"{safe_name}_page_{page_label}.{fmt}"
                image_path = storage_dir / image_filename

                pix = fitz_page.get_pixmap(dpi=dpi)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                img.save(str(image_path), format=fmt.upper())

                pages.append({"page_no": page_label, "content": f'Content: "{image_path.resolve()}"'})
        finally:
            doc.close()

        return pages

    def _extract_with_pdfplumber(self, path: str, page_number: int) -> str:
        """Extract text using pdfplumber for best layout preservation."""
        if pdfplumber is None:
            return ""
        try:
            if self._pdfplumber_doc is None:
                self._pdfplumber_doc = pdfplumber.open(path)
            if page_number >= len(self._pdfplumber_doc.pages):
                return ""
            return self._pdfplumber_doc.pages[page_number].extract_text() or ""
        except Exception as exc:  # pragma: no cover
            logger.warning("pdfplumber extraction failed for page %s: %s", page_number + 1, exc)
            return ""

    @staticmethod
    def _detect_superscripts(page: Any) -> List[Tuple[str, float]]:
        """Detect superscript spans and return (text, x_position) pairs in reading order."""
        raw = page.get_text("dict")
        results: List[Tuple[str, float]] = []
        for block in raw.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block["lines"]:
                spans = sorted(line["spans"], key=lambda s: s["bbox"][0])
                sizes = [s["size"] for s in spans if s["size"] > 0]
                dominant_size = max(set(sizes), key=sizes.count) if sizes else 0.0
                dominant_y = (
                    sum(s["origin"][1] for s in spans) / len(spans) if spans else 0.0
                )
                for span in spans:
                    if _is_superscript_span(span, dominant_size, dominant_y):
                        results.append((span["text"], span["bbox"][0]))
        # Reading order: top-to-bottom, left-to-right.
        results.sort(key=lambda item: (round(item[1] / 50), item[1]))
        return results

    @staticmethod
    def _insert_superscript_carets(text: str, superscripts: List[Tuple[str, float]]) -> str:
        """Insert carets before detected superscript text in the extracted text."""
        if not superscripts or not text:
            return text

        # Process from right to left so earlier replacements don't shift later ones.
        superscripts.sort(key=lambda item: item[1], reverse=True)
        for sup_text, _ in superscripts:
            if not sup_text:
                continue
            # Find the rightmost occurrence that is not already preceded by a caret.
            search_end = len(text)
            while True:
                idx = text.rfind(sup_text, 0, search_end)
                if idx == -1:
                    break
                if idx > 0 and text[idx - 1] == "^":
                    search_end = idx
                    continue
                text = text[:idx] + "^" + text[idx:]
                break
        return normalize_scientific_notation(text)

    @staticmethod
    def _extract_with_layout(page: Any) -> str:
        """Fallback layout-aware extraction using PyMuPDF dict mode."""
        raw = page.get_text("dict")
        blocks = [b for b in raw.get("blocks", []) if "lines" in b]
        blocks.sort(key=lambda b: (round(b["bbox"][1], 1), b["bbox"][0]))

        block_texts: List[str] = []
        for block in blocks:
            line_texts: List[str] = []
            for line in block["lines"]:
                line_text = PDFParser._reconstruct_line(line)
                if line_text:
                    line_texts.append(line_text)
            if line_texts:
                block_texts.append("\n".join(line_texts))

        text = "\n\n".join(block_texts)
        return normalize_scientific_notation(text)

    @staticmethod
    def _reconstruct_line(line: Dict[str, Any]) -> str:
        """Reconstruct a single line from its spans, preserving reading order."""
        spans = sorted(line["spans"], key=lambda s: s["bbox"][0])
        if not spans:
            return ""

        sizes = [s["size"] for s in spans if s["size"] > 0]
        dominant_size = max(set(sizes), key=sizes.count) if sizes else 0.0
        dominant_y = sum(s["origin"][1] for s in spans) / len(spans)

        parts: List[str] = []
        for span in spans:
            text = span["text"]
            if not text:
                continue
            if _is_superscript_span(span, dominant_size, dominant_y):
                text = "^" + text
            parts.append(text)

        return "".join(parts)

    @staticmethod
    def _word_count(text: str) -> int:
        return len(re.findall(r"\b\w+\b", text))

    def _is_poor(self, text: str, min_chars: int, min_words: int) -> bool:
        return len(text.strip()) < min_chars or self._word_count(text) < min_words

    def _is_better(self, candidate: str, current: str, min_chars: int, min_words: int) -> bool:
        if self._is_poor(candidate, min_chars, min_words):
            return False
        return len(candidate) > len(current) or self._word_count(candidate) > self._word_count(
            current
        )

    def _close_pdfplumber(self) -> None:
        if self._pdfplumber_doc is not None:
            try:
                self._pdfplumber_doc.close()
            except Exception as exc:  # pragma: no cover
                logger.debug("Error closing pdfplumber document: %s", exc)
            self._pdfplumber_doc = None

    def _ocr_page(self, page: Any, dpi: int) -> str:
        if pytesseract is None or Image is None:
            logger.debug("OCR requested but pytesseract/Pillow is not installed.")
            return ""
        try:
            pix = page.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            return pytesseract.image_to_string(img)
        except Exception as exc:  # pragma: no cover
            logger.warning("OCR failed for page: %s", exc)
            return ""
