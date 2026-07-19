"""UniversalDocumentParser package."""

from .parser import UniversalDocumentParser
from .exceptions import (
    UniversalDocumentParserError,
    UnsupportedFormatError,
    DependencyError,
    ParseError,
)

__version__ = "0.1.0"
__all__ = [
    "UniversalDocumentParser",
    "UniversalDocumentParserError",
    "UnsupportedFormatError",
    "DependencyError",
    "ParseError",
]
