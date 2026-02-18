"""Batch result model for batch operation statistics."""

from __future__ import annotations

from pydantic import BaseModel


class BatchResult(BaseModel):
    """Statistics from a batch processing operation."""

    processed: int
    successful: int
    failed: int
    skipped: int
    duration_seconds: float
    errors: list[str] = []
