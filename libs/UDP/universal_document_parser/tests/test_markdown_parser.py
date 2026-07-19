"""Tests for MarkdownParser."""

import os
import tempfile
import unittest

from libs.UDP.universal_document_parser.parsers.markdown_parser import MarkdownParser


class TestMarkdownParser(unittest.TestCase):
    def test_parse_markdown(self):
        with tempfile.NamedTemporaryFile(
            suffix=".md", delete=False, mode="w", encoding="utf-8"
        ) as tmp:
            tmp.write("# Heading\n\nParagraph content.\n")
            tmp_path = tmp.name

        try:
            parser = MarkdownParser()
            result = parser.parse(tmp_path)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["page_no"], 1)
            self.assertIn("# Heading", result[0]["content"])
            self.assertIn("Paragraph content.", result[0]["content"])
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
