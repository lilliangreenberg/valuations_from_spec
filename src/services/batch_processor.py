"""Generic batch processor for parallel operations."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

import structlog

from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)


def process_batch(
    items: list[Any],
    process_fn: Callable[[Any], Any],
    max_workers: int = 5,
    batch_size: int = 10,
) -> dict[str, Any]:
    """Process items in parallel using ThreadPoolExecutor.

    Returns summary stats dict with an additional 'results' key
    containing the list of successful return values.
    """
    tracker = ProgressTracker(total=len(items))
    results: list[Any] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_fn, item): item for item in items}

        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result()
                results.append(result)
                tracker.record_success()
            except Exception as exc:
                logger.error(
                    "batch_item_failed",
                    item=str(item)[:100],
                    error=str(exc),
                )
                tracker.record_failure(str(exc))

            tracker.log_progress(every_n=10)

    summary = tracker.summary()
    summary["results"] = results
    return summary
