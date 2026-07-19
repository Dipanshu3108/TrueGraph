"""Tests for text cleanup pipeline."""

import unittest

from libs.UDP.universal_document_parser.cleanup.text_cleanup import (
    cleanup_document,
    cleanup_page,
    fix_ligatures,
    merge_broken_paragraphs,
    normalize_unicode,
    normalize_whitespace,
    remove_duplicate_blank_lines,
    remove_headers_footers,
)


class TestCleanup(unittest.TestCase):
    def test_normalize_unicode(self):
        self.assertEqual(normalize_unicode("caf\u00e9"), "caf\u00e9")

    def test_fix_ligatures(self):
        self.assertEqual(fix_ligatures("ﬁle"), "file")
        self.assertEqual(fix_ligatures("ﬂower"), "flower")

    def test_normalize_whitespace(self):
        self.assertEqual(normalize_whitespace("  hello   world  "), "hello world")

    def test_remove_duplicate_blank_lines(self):
        text = "a\n\n\n\n\nb"
        self.assertEqual(remove_duplicate_blank_lines(text), "a\n\nb")

    def test_merge_broken_paragraphs(self):
        text = "This is a long\nsentence that was broken."
        result = merge_broken_paragraphs(text)
        self.assertIn("This is a long sentence that was broken.", result)

    def test_cleanup_page(self):
        text = "  hello   world  \n\n\n\nsecond"
        result = cleanup_page(text)
        self.assertEqual(result, "hello world\n\nsecond")

    def test_remove_headers_footers(self):
        pages = [
            {"page_no": 1, "content": "Header\nBody one\nFooter"},
            {"page_no": 2, "content": "Header\nBody two\nFooter"},
            {"page_no": 3, "content": "Header\nBody three\nFooter"},
        ]
        result = remove_headers_footers(pages, min_occurrences=3)
        self.assertNotIn("Header", result[0]["content"])
        self.assertNotIn("Footer", result[0]["content"])
        self.assertIn("Body one", result[0]["content"])

    def test_cleanup_document(self):
        doc = {
            "filename": "x.pdf",
            "metadata": [],
            "pages": [{"page_no": 1, "content": "  hello   world  "}],
        }
        result = cleanup_document(doc)
        self.assertEqual(result["pages"][0]["content"], "hello world")

    def test_normalize_scientific_notation(self):
        from libs.UDP.universal_document_parser.cleanup.text_cleanup import normalize_scientific_notation

        # With caret from superscript detection -> exponent notation.
        self.assertEqual(normalize_scientific_notation("10^\u201243"), "10^-43")
        self.assertEqual(normalize_scientific_notation("10^\u201235"), "10^-35")
        # Without caret, dash is simply normalized to hyphen-minus.
        self.assertEqual(normalize_scientific_notation("10\u201243"), "10-43")
        # Dashes between digits are normalized to hyphen-minus.
        self.assertEqual(normalize_scientific_notation("2022\u20132023"), "2022-2023")


if __name__ == "__main__":
    unittest.main()
