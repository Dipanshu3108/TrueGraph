"""Assemble the final self-contained OKF bundle on disk."""

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from knowledge_builder.types import Page, ValidationReport


logger = logging.getLogger(__name__)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def write_bundle(
    bundle_dir: str,
    knowledge_store_path: str,
    document_id: str,
    validation_report: ValidationReport,
    *,
    pages: list[Page] | None = None,
    source_path: str | None = None,
) -> str:
    """Assemble the final bundle on disk.

    Returns the absolute path to the bundle directory.
    """
    store_path = Path(knowledge_store_path)
    store_path.mkdir(parents=True, exist_ok=True)
    bundle_path = store_path / document_id
    bundle_path.mkdir(parents=True, exist_ok=True)

    logger.info("Writing OKF bundle to %s", bundle_path)

    # Required subdirectories.
    (bundle_path / "documents").mkdir(exist_ok=True)
    (bundle_path / "pages").mkdir(exist_ok=True)
    (bundle_path / "assets").mkdir(exist_ok=True)

    # Persist validation report at bundle root.
    report_dict = {
        "total_batches": validation_report.total_batches,
        "valid_batches": validation_report.valid_batches,
        "invalid_batches": validation_report.invalid_batches,
        "dropped_concepts": validation_report.dropped_concepts,
        "dropped_relationships": validation_report.dropped_relationships,
        "dropped_keywords": validation_report.dropped_keywords,
        "dropped_aliases": validation_report.dropped_aliases,
        "errors": validation_report.errors,
    }
    _write_json(bundle_path / "validation_report.json", report_dict)

    # Write per-page JSON under pages/; copy image sources into assets/.
    if pages:
        for page in pages:
            page_path = bundle_path / "pages" / f"{page.page_number}.json"
            _write_json(
                page_path,
                {
                    "page_number": page.page_number,
                    "content": page.content,
                    "content_type": page.content_type,
                },
            )
            if page.content_type == "image":
                src_image = Path(page.content)
                if src_image.is_file():
                    dest_image = (
                        bundle_path / "assets" / f"page_{page.page_number}{src_image.suffix}"
                    )
                    shutil.copy2(src_image, dest_image)
                else:
                    logger.warning(
                        "Image source for page %d missing, not copied to assets/: %s",
                        page.page_number,
                        page.content,
                    )

    # Copy the original parsed source file into documents/ for immutability.
    if source_path:
        src = Path(source_path)
        if src.is_file():
            dest = bundle_path / "documents" / f"{document_id}{src.suffix}"
            shutil.copy2(src, dest)

    return str(bundle_path.resolve())
