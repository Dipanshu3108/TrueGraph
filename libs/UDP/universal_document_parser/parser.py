"""UniversalDocumentParser main class."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .cleanup.text_cleanup import cleanup_document
from .config import (
    DEFAULT_CONFIG,
    SUPPORTED_EXTENSIONS,
    SUPPORTED_INPUT_FORMATS,
    SUPPORTED_OUTPUT_FORMATS,
)
from .exceptions import UnsupportedFormatError
from .formatters import format_json, format_markdown, format_text
from .logger import configure_logging, get_logger
from .parsers import DOCXParser, MarkdownParser, PDFParser, PPTXParser
from .utils.file_utils import file_exists, get_filename_and_extension

logger = get_logger()


class UniversalDocumentParser:
    """Production-grade document parser supporting PDF, DOCX, PPTX, PPT, and Markdown."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, verbose: bool = False):
        """Initialize the parser.

        Args:
            config: Optional configuration overrides.
            verbose: Enable debug logging.
        """
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        if verbose:
            configure_logging(level=10)  # logging.DEBUG

        self._parsers = {
            ".pdf": PDFParser(self.config),
            ".docx": DOCXParser(self.config),
            ".pptx": PPTXParser(self.config),
            ".ppt": PPTXParser(self.config),
            ".md": MarkdownParser(self.config),
            ".markdown": MarkdownParser(self.config),
        }

    def parse(
        self,
        path: str,
        metadata: Optional[List[str]] = None,
        output_format: str = "markdown",
        input_format: str = "default",
    ) -> Union[str, Dict[str, Any]]:
        """Parse a document and return it in the requested format.

        Args:
            path: Path to the document file.
            metadata: Optional list of metadata tags.
            output_format: One of "markdown", "text", or "json".
            input_format: One of "default" or "image". When "image", PDF pages
                are rendered to images instead of being parsed.

        Returns:
            str for markdown/text output, dict for json output.

        Raises:
            UnsupportedFormatError: If the file or input format is not supported.
            ParseError: If the document cannot be parsed.
            DependencyError: If a required dependency is missing.
        """
        output_format = output_format.lower()
        input_format = input_format.lower()
        if output_format not in SUPPORTED_OUTPUT_FORMATS:
            raise UnsupportedFormatError(
                f"Unsupported output format: {output_format}. "
                f"Supported: {sorted(SUPPORTED_OUTPUT_FORMATS)}"
            )
        if input_format not in SUPPORTED_INPUT_FORMATS:
            raise UnsupportedFormatError(
                f"Unsupported input format: {input_format}. "
                f"Supported: {sorted(SUPPORTED_INPUT_FORMATS)}"
            )

        if not file_exists(path):
            raise FileNotFoundError(f"File not found or not readable: {path}")

        filename, ext = get_filename_and_extension(path)
        if ext not in SUPPORTED_EXTENSIONS:
            raise UnsupportedFormatError(
                f"Unsupported file extension: {ext}. Supported: {sorted(SUPPORTED_EXTENSIONS)}"
            )

        logger.info("Parsing %s as %s (input_format=%s)", filename, ext, input_format)
        parser = self._parsers[ext]

        if input_format == "image":
            if ext != ".pdf":
                raise UnsupportedFormatError(
                    f"input_format='image' is only supported for PDF files, got {ext}."
                )
            image_storage_dir = self.config.get("image_storage_dir", "image_storage")
            pages = parser.convert_to_images(path, image_storage_dir)
        elif ext == ".ppt":
            # PPT needs conversion before parsing.
            pptx_path = parser.convert_ppt_to_pptx(path)
            try:
                pages = parser.parse(pptx_path)
            finally:
                Path(pptx_path).unlink(missing_ok=True)
        else:
            pages = parser.parse(path)

        document: Dict[str, Any] = {
            "filename": filename,
            "metadata": list(metadata or []),
            "pages": pages,
        }

        document = cleanup_document(
            document, min_occurrences=self.config.get("header_footer_min_occurrences", 3)
        )

        if output_format == "text":
            return format_text(document)
        if output_format == "json":
            return format_json(document)
        return format_markdown(document)

    @property
    def supported_formats(self) -> List[str]:
        """Return the list of supported output formats."""
        return sorted(SUPPORTED_OUTPUT_FORMATS)
