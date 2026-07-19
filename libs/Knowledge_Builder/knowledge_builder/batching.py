"""Page filtering and batch assembly for the extraction stage."""

import logging
from pathlib import Path

from knowledge_builder.types import Batch, Page


logger = logging.getLogger(__name__)


def filter_empty_pages(pages: list[Page]) -> tuple[list[Page], list[int]]:
    """Drop pages with no usable content.

    Text pages follow the v1 rule: dropped when nothing remains after a
    whitespace strip. Image pages are dropped only when the referenced file is
    missing or not a file — a valid path alone is never treated as proof of
    content, and blank-detection heuristics are intentionally out of scope.

    Returns ``(kept_pages, dropped_page_numbers)`` — dropped numbers are
    recorded for provenance and never sent anywhere.
    """
    kept: list[Page] = []
    dropped: list[int] = []
    for page in pages:
        if page.content_type == "image":
            if page.content and Path(page.content).is_file():
                kept.append(page)
            else:
                dropped.append(page.page_number)
        elif page.content and page.content.strip():
            kept.append(page)
        else:
            dropped.append(page.page_number)
    logger.info("Filtered empty pages: %d kept, %d dropped", len(kept), len(dropped))
    return kept, dropped


def _build_batch(batch_id: int, chunk: list[Page]) -> Batch:
    """Assemble one homogeneous batch from a run of same-type pages."""
    page_numbers = [p.page_number for p in chunk]
    content_type = chunk[0].content_type
    if content_type == "image":
        content: "str | list[tuple[int, str]]" = [
            (p.page_number, p.content) for p in chunk
        ]
    else:
        content = "\n\n".join(f"### Page {p.page_number}\n{p.content}" for p in chunk)
    return Batch(
        batch_id=batch_id,
        page_numbers=page_numbers,
        content=content,
        content_type=content_type,
    )


def make_batches(
    pages: list[Page], page_batch: int, image_page_batch: int | None = None
) -> list[Batch]:
    """Group ALL remaining pages into homogeneous batches, in document order.

    A batch never mixes text and image pages: whenever ``content_type``
    changes, the current batch is closed (even if under its size limit) and a
    new one of the other type begins. Text runs are chunked by ``page_batch``,
    image runs by ``image_page_batch`` (defaults to ``page_batch``). Every
    page passed in is covered by exactly one batch.
    """
    if page_batch <= 0:
        raise ValueError("page_batch must be a positive integer")
    if image_page_batch is None:
        image_page_batch = page_batch
    if image_page_batch <= 0:
        raise ValueError("image_page_batch must be a positive integer")

    batches: list[Batch] = []
    run: list[Page] = []

    def flush_run() -> None:
        nonlocal run
        limit = page_batch if run[0].content_type == "text" else image_page_batch
        for i in range(0, len(run), limit):
            batches.append(_build_batch(len(batches) + 1, run[i : i + limit]))
        run = []

    for page in pages:
        if run and page.content_type != run[0].content_type:
            flush_run()
        run.append(page)
    if run:
        flush_run()

    logger.info(
        "Created %d batch(es) from %d page(s) (text batch size=%d, image batch size=%d)",
        len(batches),
        len(pages),
        page_batch,
        image_page_batch,
    )
    return batches
