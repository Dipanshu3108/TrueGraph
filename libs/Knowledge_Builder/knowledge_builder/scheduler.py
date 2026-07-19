"""Bounded async scheduler that dispatches batches through a worker pool."""

import asyncio
import logging
from typing import Any

from knowledge_builder.extraction import UsageTracker, extract_batch
from knowledge_builder.exceptions import ExtractionError
from knowledge_builder.types import Batch, ExtractionResult


logger = logging.getLogger(__name__)


async def _worker(
    queue: asyncio.Queue[Batch],
    results: list[ExtractionResult],
    config: dict[str, Any],
    max_retries: int,
    tracker: UsageTracker,
) -> None:
    """Pull batches from a shared queue until exhausted."""
    while True:
        try:
            batch = queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        logger.info(
            "Extracting batch %d (pages %s), using - %s with up to %d retry attempt(s)",
            batch.batch_id,
            batch.page_numbers,
            batch.content_type,
            max_retries,
        )
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                result = await extract_batch(batch, config, tracker)
                results.append(result)
                logger.info(
                    "Batch %d extracted: %d concept(s), %d relationship(s)",
                    batch.batch_id,
                    len(result.concepts),
                    len(result.relationships),
                )
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt == max_retries:
                    raise ExtractionError(
                        f"Batch {batch.batch_id} (pages {batch.page_numbers}) "
                        f"exhausted {max_retries} retries"
                    ) from exc
                await asyncio.sleep(2**attempt)


async def run_batches(batches: list[Batch], config: dict[str, Any]) -> tuple[list[ExtractionResult], str]:
    """Dispatch every batch through a worker pool bounded by ``num_sub_agents``.

    Retries with exponential backoff on failure. Raises if a batch exhausts
    retries — never silently drops a batch's results.

    Concurrency model: queue-pull. All batches go into a shared queue; each of
    the ``num_sub_agents`` workers pulls the next unclaimed batch as soon as it
    is free.
    """
    tracker = UsageTracker(document_name=config.get("document_name", "unknown"))
    num_workers = int(config.get("num_sub_agents", 1))
    if num_workers <= 0:
        raise ValueError("num_sub_agents must be a positive integer")

    max_retries = int(config.get("max_retries", 3))
    logger.info(
        "Dispatching %d batch(es) to %d worker(s) (retries=%d)",
        len(batches),
        num_workers,
        max_retries,
    )
    queue: asyncio.Queue[Batch] = asyncio.Queue()
    for batch in batches:
        queue.put_nowait(batch)

    results: list[ExtractionResult] = []
    workers = [
        asyncio.create_task(_worker(queue, results, config, max_retries, tracker))
        for _ in range(num_workers)
    ]
    await asyncio.gather(*workers)
    log_path = tracker.write_log()
    return results, log_path
