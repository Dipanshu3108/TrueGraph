"""Tests for output formatters."""

import json
import unittest

from libs.UDP.universal_document_parser.formatters import format_json, format_markdown, format_text


SAMPLE_DOCUMENT = {
    "filename": "example.pdf",
    "metadata": ["finance"],
    "pages": [{"page_no": 1, "content": "Hello world\nSecond line"}],
}


class TestTextFormatter(unittest.TestCase):
    def test_format_text(self):
        output = format_text(SAMPLE_DOCUMENT)
        expected = (
            "FILE_NAME : example.pdf\n"
            'METADATA : ["finance"]\n'
            "\n"
            "---------------------------------------------------\n"
            "PAGE_NO : 1\n"
            "\n"
            "CONTENT:\n"
            "Hello world\n"
            "Second line\n"
            "---------------------------------------------------"
        )
        self.assertEqual(output, expected)


class TestMarkdownFormatter(unittest.TestCase):
    def test_format_markdown(self):
        output = format_markdown(SAMPLE_DOCUMENT)
        expected = (
            "# example.pdf\n"
            "\n"
            "## Metadata\n"
            "\n"
            "- finance\n"
            "\n"
            "---\n"
            "\n"
            "# Page 1\n"
            "\n"
            "Hello world\n"
            "Second line\n"
        )
        self.assertEqual(output, expected)

    def test_format_markdown_empty_metadata(self):
        doc = {**SAMPLE_DOCUMENT, "metadata": []}
        output = format_markdown(doc)
        self.assertIn("- _No metadata_", output)


class TestJsonFormatter(unittest.TestCase):
    def test_format_json(self):
        output = format_json(SAMPLE_DOCUMENT)
        expected = {
            "FileName": "example.pdf",
            "Metadata": ["finance"],
            "FileContent": [{"page_no": 1, "content": "Hello world\nSecond line"}],
        }
        self.assertEqual(output, expected)

    def test_format_json_string(self):
        from libs.UDP.universal_document_parser.formatters.json_formatter import format_json_string

        output = format_json_string(SAMPLE_DOCUMENT)
        parsed = json.loads(output)
        self.assertEqual(parsed["FileName"], "example.pdf")


if __name__ == "__main__":
    unittest.main()
