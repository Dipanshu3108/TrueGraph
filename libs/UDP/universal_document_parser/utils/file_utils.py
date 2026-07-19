"""File-system and path utilities."""

import os
from pathlib import Path
from typing import Tuple


def resolve_path(path: str) -> Path:
    """Resolve a path string to an absolute Path object."""
    return Path(path).expanduser().resolve()


def get_filename_and_extension(path: str) -> Tuple[str, str]:
    """Return (filename, lower-case extension) for a file path."""
    p = resolve_path(path)
    return p.name, p.suffix.lower()


def file_exists(path: str) -> bool:
    """Check whether a file exists and is readable."""
    p = resolve_path(path)
    return p.is_file() and os.access(p, os.R_OK)
