"""Command-line interface for UniversalDocumentParser."""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .parser import UniversalDocumentParser


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="universal-document-parser",
        description="Parse PDF, DOCX, PPTX, PPT, and Markdown documents.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")

    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_cmd = subparsers.add_parser("parse", help="Parse a document")
    parse_cmd.add_argument("path", help="Path to the document")
    parse_cmd.add_argument(
        "--metadata",
        nargs="*",
        default=[],
        help="Metadata tags",
    )
    parse_cmd.add_argument(
        "--output-format",
        choices=["markdown", "text", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parse_cmd.add_argument(
        "--input-format",
        choices=["default", "image"],
        default="default",
        help="Input processing mode; 'image' renders PDF pages to images (default: default)",
    )
    parse_cmd.add_argument(
        "--output",
        "-o",
        help="Output file path. Defaults to stdout.",
    )
    parse_cmd.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser


def write_output(data: str, output_path: Optional[str]) -> None:
    """Write data to a file or stdout."""
    if output_path:
        Path(output_path).write_text(data, encoding="utf-8")
    else:
        sys.stdout.write(data)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    udp = UniversalDocumentParser(verbose=args.verbose)
    result = udp.parse(
        path=args.path,
        metadata=args.metadata,
        output_format=args.output_format,
        input_format=args.input_format,
    )

    if args.output_format == "json" and not isinstance(result, str):
        output_text = json.dumps(result, indent=2, ensure_ascii=False)
    else:
        output_text = str(result)

    write_output(output_text, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
