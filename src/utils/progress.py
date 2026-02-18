"""Progress tracking utilities for batch operations."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ProgressTracker:
    """Track progress of batch operations."""

    total: int
    processed: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.monotonic)

    def record_success(self) -> None:
        """Record a successful operation."""
        self.processed += 1
        self.successful += 1

    def record_failure(self, error: str) -> None:
        """Record a failed operation."""
        self.processed += 1
        self.failed += 1
        self.errors.append(error)

    def record_skip(self) -> None:
        """Record a skipped operation."""
        self.processed += 1
        self.skipped += 1

    @property
    def elapsed_seconds(self) -> float:
        """Time elapsed since start."""
        return time.monotonic() - self.start_time

    @property
    def progress_percentage(self) -> float:
        """Percentage of total items processed."""
        if self.total == 0:
            return 100.0
        return (self.processed / self.total) * 100.0

    def log_progress(self, every_n: int = 10) -> None:
        """Log progress every N items."""
        if self.processed % every_n == 0 or self.processed == self.total:
            logger.info(
                "batch_progress",
                processed=self.processed,
                total=self.total,
                successful=self.successful,
                failed=self.failed,
                skipped=self.skipped,
                percentage=f"{self.progress_percentage:.1f}%",
                elapsed=f"{self.elapsed_seconds:.1f}s",
            )

    def summary(self) -> dict[str, int | float | list[str]]:
        """Return summary statistics."""
        return {
            "processed": self.processed,
            "successful": self.successful,
            "failed": self.failed,
            "skipped": self.skipped,
            "duration_seconds": round(self.elapsed_seconds, 2),
            "errors": self.errors,
        }
