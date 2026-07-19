"""Tests for PDFParser."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from libs.UDP.universal_document_parser.parsers.pdf_parser import PDFParser


class TestPDFParser(unittest.TestCase):
    @patch("libs.UDP.universal_document_parser.parsers.pdf_parser.fitz")
    def test_parse_with_good_text(self, mock_fitz):
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_page = MagicMock()
        mock_doc.load_page.return_value = mock_page
        mock_fitz.open.return_value = mock_doc

        parser = PDFParser(config={"pdf_use_pdfplumber_primary": False})
        with patch.object(
            parser, "_extract_with_layout", return_value="Hello world, this is page one."
        ):
            result = parser.parse("dummy.pdf")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["page_no"], 1)
        self.assertIn("Hello world", result[0]["content"])
        mock_doc.close.assert_called_once()

    @patch("libs.UDP.universal_document_parser.parsers.pdf_parser.fitz")
    def test_parse_with_poor_text_triggers_ocr(self, mock_fitz):
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_page = MagicMock()
        mock_doc.load_page.return_value = mock_page
        mock_fitz.open.return_value = mock_doc

        parser = PDFParser(config={"pdf_use_pdfplumber_primary": False, "enable_ocr": True})
        with patch.object(parser, "_extract_with_layout", return_value=""):
            with patch.object(
                parser,
                "_ocr_page",
                return_value="OCR fallback text here with more than fifty characters to satisfy the threshold.",
            ):
                result = parser.parse("dummy.pdf")

        self.assertIn("OCR fallback text here", result[0]["content"])

    def test_extract_with_layout_preserves_blocks(self):
        """Layout extraction should keep distinct blocks on separate lines."""
        try:
            import fitz
        except ImportError:  # pragma: no cover
            self.skipTest("PyMuPDF not installed")

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "First block")
        page.insert_text((72, 200), "Second block")
        text = PDFParser._extract_with_layout(page)
        doc.close()
        self.assertIn("First block", text)
        self.assertIn("Second block", text)
        self.assertIn("\n\n", text)

    def test_insert_superscript_carets(self):
        text = "10\u201243 and 10\u201235"
        superscripts = [("\u201243", 100.0), ("\u201235", 200.0)]
        result = PDFParser._insert_superscript_carets(text, superscripts)
        self.assertIn("10^-43", result)
        self.assertIn("10^-35", result)

    def test_insert_superscript_carets_right_to_left(self):
        """Multiple identical superscripts should each get a caret."""
        text = "10\u201235 and 10\u201235"
        superscripts = [("\u201235", 200.0), ("\u201235", 100.0)]
        result = PDFParser._insert_superscript_carets(text, superscripts)
        self.assertEqual(result.count("10^-35"), 2)

    @patch("libs.UDP.universal_document_parser.parsers.pdf_parser.fitz")
    @patch("libs.UDP.universal_document_parser.parsers.pdf_parser.Image")
    def test_convert_to_images_renders_pages_and_returns_paths(self, mock_Image, mock_fitz):
        """Image mode should render each page and return webp paths as content."""
        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"fake-png-bytes"
        mock_page = MagicMock()
        mock_page.get_pixmap.return_value = mock_pix
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=2)
        mock_doc.load_page.side_effect = [mock_page, mock_page]
        mock_fitz.open.return_value = mock_doc

        mock_img = MagicMock()
        mock_Image.open.return_value = mock_img

        with tempfile.TemporaryDirectory() as tmpdir:
            parser = PDFParser(config={"image_dpi": 150, "image_format": "webp"})
            result = parser.convert_to_images("/docs/my:report!.pdf", tmpdir)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["page_no"], 1)
        self.assertEqual(result[1]["page_no"], 2)
        self.assertTrue(result[0]["content"].endswith('my_report!_page_1.webp"'))
        self.assertTrue(result[1]["content"].endswith('my_report!_page_2.webp"'))
        image_path = result[0]["content"].split('"')[1]
        self.assertTrue(Path(image_path).is_absolute())

        storage_dir = Path(image_path).parent
        self.assertEqual(storage_dir.name, "my_report!")
        mock_page.get_pixmap.assert_called_with(dpi=150)
        self.assertEqual(mock_img.save.call_count, 2)
        mock_doc.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
