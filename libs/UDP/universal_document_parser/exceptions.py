"""Custom exceptions for UniversalDocumentParser."""


class UniversalDocumentParserError(Exception):
    """Base exception for the parser."""


class UnsupportedFormatError(UniversalDocumentParserError):
    """Raised when the file format is not supported."""


class DependencyError(UniversalDocumentParserError):
    """Raised when a required system or Python dependency is missing."""


class ParseError(UniversalDocumentParserError):
    """Raised when parsing fails for a specific document."""
