"""Default configuration for UniversalDocumentParser."""

from typing import Dict, Any

DEFAULT_CONFIG: Dict[str, Any] = {
    # Minimum average characters per page to consider digital text extraction successful.
    "min_chars_per_page": 50,
    # Minimum word count per page to skip OCR fallback.
    "min_words_per_page": 10,
    # Parser priority for PDF (tried in order per page when enabled).
    "pdf_parsers": ["pymupdf", "pdfplumber", "pdfminer"],
    # Whether to attempt OCR on pages with insufficient text.
    "enable_ocr": False,
    # DPI for rendering pages before OCR.
    "ocr_dpi": 200,
    # Whether to attempt LibreOffice conversion for .ppt files.
    "enable_ppt_conversion": True,
    # Repeated line threshold for header/footer removal.
    "header_footer_min_occurrences": 3,
    # Use PyMuPDF dict-mode extraction that preserves layout and superscripts.
    "pdf_use_layout_extraction": True,
    # Use pdfplumber as the primary PDF extractor for superior layout quality.
    "pdf_use_pdfplumber_primary": True,
    # Directory where per-page PDF images are stored when input_format="image".
    "image_storage_dir": "image_storage",
    # Image format used for rendered PDF pages.
    "image_format": "webp",
    # DPI for rendering pages when input_format="image".
    "image_dpi": 200,
}

SUPPORTED_OUTPUT_FORMATS = {"markdown", "text", "json"}
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".ppt", ".md", ".markdown"}
SUPPORTED_INPUT_FORMATS = {"default", "image"}
