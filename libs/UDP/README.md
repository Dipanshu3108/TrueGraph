# Universal Document Parser

A production-grade, CPU-efficient document parser that converts PDF, DOCX, PPTX, PPT, and Markdown files into Markdown, plain text, or structured JSON.

This package is the first stage of the OKF_RAG pipeline. Its output is consumed directly by the [Knowledge Builder](../libs/Knowledge_Builder/README.md).

## Features

- **Multi-format input**: PDF, DOCX, PPTX, PPT, Markdown
- **Multi-format output**: Markdown (default), Text, JSON
- **Cascading PDF extraction**: PyMuPDF → pdfplumber → pdfminer → OCR (when enabled)
- **Page-level fallback**: Only poor-quality pages trigger heavier extractors
- **Cleanup pipeline**: Unicode normalization, whitespace cleanup, header/footer removal, broken-paragraph merging, ligature fixing
- **Image rendering mode**: Render PDF pages to images via `input_format="image"`
- **Configurable**: Parser priorities, quality thresholds, OCR settings, and image output options
- **CLI and Python API**
- **Type hints and structured logging**

## Installation

The package is installed from the `libs/` directory because its `pyproject.toml` lives at `libs/pyproject.toml` (the source tree is under `libs/UDP/universal_document_parser`).

```bash
cd libs
pip install -e .
```

For development:

```bash
pip install -e ".[dev]"
```

### System Dependencies

- **Tesseract OCR** (optional, only needed for scanned PDFs when `enable_ocr=True`)
- **LibreOffice** (optional, only needed for `.ppt` to `.pptx` conversion)

## Python API

```python
from universal_document_parser import UniversalDocumentParser

parser = UniversalDocumentParser()

# Markdown output
markdown = parser.parse("input/document.pdf", output_format="markdown")

# Text output with metadata tags
text = parser.parse(
    "input/document.docx",
    metadata=["finance", "2026"],
    output_format="text"
)

# JSON output
json_result = parser.parse("input/slides.pptx", output_format="json")
```

Supported output formats: `"markdown"`, `"text"`, `"json"`.
Supported input formats: `"default"`, `"image"` (renders PDF pages to images).

## CLI

```bash
# Markdown output to stdout
universal-document-parser parse document.pdf

# Text output with metadata
universal-document-parser parse document.docx --metadata finance 2026 --output-format text

# JSON output to file
universal-document-parser parse slides.pptx --output-format json --output slides.json
```

All internal parsers produce the same intermediate representation:

```python
{
    "filename": "...",
    "metadata": [...],
    "pages": [
        {"page_no": 1, "content": "..."},
        ...
    ]
}
```

## Configuration

```python
config = {
    "min_chars_per_page": 50,
    "min_words_per_page": 10,
    "enable_ocr": False,
    "ocr_dpi": 200,
    "enable_ppt_conversion": True,
    "header_footer_min_occurrences": 3,
    "pdf_use_layout_extraction": True,
    "pdf_use_pdfplumber_primary": True,
    "image_storage_dir": "image_storage",
    "image_format": "webp",
    "image_dpi": 200,
}

parser = UniversalDocumentParser(config=config)
```
## Testing

```bash
cd libs
pytest universal_document_parser/tests
```
## License

MIT
