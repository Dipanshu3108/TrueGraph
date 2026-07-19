"""Tests for UniversalDocumentParser dispatch and integration."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from libs.UDP.universal_document_parser.parser import UniversalDocumentParser


class TestUniversalDocumentParser(unittest.TestCase):
    def test_supported_formats(self):
        parser = UniversalDocumentParser()
        self.assertEqual(sorted(parser.supported_formats), ["json", "markdown", "text"])

    def test_unsupported_output_format(self):
        parser = UniversalDocumentParser()
        with self.assertRaises(Exception):
            parser.parse("dummy.pdf", output_format="xml")

    def test_file_not_found(self):
        parser = UniversalDocumentParser()
        with self.assertRaises(FileNotFoundError):
            parser.parse("/nonexistent/file.pdf")

    def test_unsupported_extension(self):
        parser = UniversalDocumentParser()
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as tmp:
            tmp.write(b"data")
            tmp_path = tmp.name
        try:
            with self.assertRaises(Exception):
                parser.parse(tmp_path)
        finally:
            os.unlink(tmp_path)

    def test_markdown_parsing(self):
        parser = UniversalDocumentParser()
        with tempfile.NamedTemporaryFile(
            suffix=".md", delete=False, mode="w", encoding="utf-8"
        ) as tmp:
            tmp.write("# Title\n\nSome content.\n")
            tmp_path = tmp.name
        try:
            result = parser.parse(tmp_path, metadata=["tag"], output_format="json")
            self.assertEqual(result["FileName"], Path(tmp_path).name)
            self.assertEqual(result["Metadata"], ["tag"])
            self.assertIn("Some content.", result["FileContent"][0]["content"])
        finally:
            os.unlink(tmp_path)

    @patch("libs.UDP.universal_document_parser.parser.PDFParser")
    def test_pdf_dispatch(self, mock_pdf_parser):
        parser = UniversalDocumentParser()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(b"%PDF-1.4 fake")
            tmp_path = tmp.name
        try:
            instance = mock_pdf_parser.return_value
            instance.parse.return_value = [{"page_no": 1, "content": "PDF content"}]
            result = parser.parse(tmp_path, output_format="text")
            self.assertIn("PDF content", result)
            instance.parse.assert_called_once()
        finally:
            os.unlink(tmp_path)

    @patch("libs.UDP.universal_document_parser.parser.PDFParser")
    def test_pdf_image_input_format(self, mock_pdf_parser):
        parser = UniversalDocumentParser(config={"image_storage_dir": "test_image_storage"})
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(b"%PDF-1.4 fake")
            tmp_path = tmp.name
        try:
            instance = mock_pdf_parser.return_value
            instance.convert_to_images.return_value = [
                {"page_no": 1, "content": 'Content: "test_image_storage/file/file_page_1.webp"'},
                {"page_no": 2, "content": 'Content: "test_image_storage/file/file_page_2.webp"'},
            ]
            result = parser.parse(
                tmp_path, output_format="markdown", input_format="image"
            )
            self.assertIn("# Page 1", result)
            self.assertIn("test_image_storage/file/file_page_1.webp", result)
            self.assertIn("# Page 2", result)
            self.assertIn("test_image_storage/file/file_page_2.webp", result)
            instance.convert_to_images.assert_called_once_with(
                tmp_path, "test_image_storage"
            )
            instance.parse.assert_not_called()
        finally:
            os.unlink(tmp_path)

    def test_image_input_format_unsupported_for_non_pdf(self):
        parser = UniversalDocumentParser()
        with tempfile.NamedTemporaryFile(
            suffix=".md", delete=False, mode="w", encoding="utf-8"
        ) as tmp:
            tmp.write("# Title\n")
            tmp_path = tmp.name
        try:
            with self.assertRaises(Exception):
                parser.parse(tmp_path, input_format="image")
        finally:
            os.unlink(tmp_path)

    def test_unsupported_input_format(self):
        parser = UniversalDocumentParser()
        with tempfile.NamedTemporaryFile(
            suffix=".md", delete=False, mode="w", encoding="utf-8"
        ) as tmp:
            tmp.write("# Title\n")
            tmp_path = tmp.name
        try:
            with self.assertRaises(Exception):
                parser.parse(tmp_path, input_format="ocr")
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
