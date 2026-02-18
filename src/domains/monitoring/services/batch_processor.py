"""Batch snapshot processing service."""

from __future__ import annotations

# Re-export from the shared service for backwards compatibility
from src.services.batch_snapshot_manager import BatchSnapshotManager

__all__ = ["BatchSnapshotManager"]
