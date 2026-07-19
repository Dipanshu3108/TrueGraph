"""Logging utilities for UniversalDocumentParser."""

import logging
from typing import Optional


def get_logger(name: str = "universal_document_parser") -> logging.Logger:
    """Return the package logger."""
    return logging.getLogger(name)


def configure_logging(
    level: int = logging.INFO,
    handler: Optional[logging.Handler] = None,
    fmt: Optional[str] = None,
) -> None:
    """Configure the package logger.

    Args:
        level: Logging level.
        handler: Optional handler to use. Defaults to StreamHandler.
        fmt: Optional format string.
    """
    logger = get_logger()
    logger.setLevel(level)
    logger.handlers.clear()

    if handler is None:
        handler = logging.StreamHandler()

    if fmt is None:
        fmt = "%(name)s - %(levelname)s - %(message)s"

    handler.setFormatter(logging.Formatter(fmt))
    logger.addHandler(handler)
