"""Snapshot repository for database CRUD operations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.services.database import Database

logger = structlog.get_logger(__name__)


class SnapshotRepository:
    """Repository for snapshot data access."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def store_snapshot(self, data: dict[str, Any]) -> int:
        """Store a new snapshot. Returns snapshot ID."""
        cursor = self.db.execute(
            """INSERT INTO snapshots
               (company_id, url, content_markdown, content_html, status_code,
                captured_at, has_paywall, has_auth_required, error_message,
                content_checksum, http_last_modified, capture_metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["company_id"],
                data["url"],
                data.get("content_markdown"),
                data.get("content_html"),
                data.get("status_code"),
                data["captured_at"],
                1 if data.get("has_paywall") else 0,
                1 if data.get("has_auth_required") else 0,
                data.get("error_message"),
                data.get("content_checksum"),
                data.get("http_last_modified"),
                data.get("capture_metadata"),
            ),
        )
        self.db.connection.commit()
        return cursor.lastrowid or 0

    def get_latest_snapshots(self, company_id: int, limit: int = 2) -> list[dict[str, Any]]:
        """Get the most recent snapshots for a company."""
        rows = self.db.fetchall(
            """SELECT * FROM snapshots
               WHERE company_id = ?
               ORDER BY captured_at DESC
               LIMIT ?""",
            (company_id, limit),
        )
        return [dict(row) for row in rows]

    def get_snapshot_by_id(self, snapshot_id: int) -> dict[str, Any] | None:
        """Get a snapshot by ID."""
        row = self.db.fetchone("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,))
        return dict(row) if row else None

    def get_snapshots_for_company(self, company_id: int) -> list[dict[str, Any]]:
        """Get all snapshots for a company ordered by date."""
        rows = self.db.fetchall(
            "SELECT * FROM snapshots WHERE company_id = ? ORDER BY captured_at",
            (company_id,),
        )
        return [dict(row) for row in rows]

    def get_companies_with_multiple_snapshots(self) -> list[int]:
        """Get company IDs that have 2 or more snapshots."""
        rows = self.db.fetchall(
            """SELECT company_id FROM snapshots
               GROUP BY company_id
               HAVING COUNT(*) >= 2"""
        )
        return [row["company_id"] for row in rows]

    def get_oldest_snapshot_date(self, company_id: int) -> str | None:
        """Get the oldest snapshot date for a company."""
        row = self.db.fetchone(
            "SELECT MIN(captured_at) as oldest FROM snapshots WHERE company_id = ?",
            (company_id,),
        )
        return row["oldest"] if row else None

    def count_snapshots_for_company(self, company_id: int) -> int:
        """Count total snapshots for a company."""
        row = self.db.fetchone(
            "SELECT COUNT(*) as cnt FROM snapshots WHERE company_id = ?",
            (company_id,),
        )
        return row["cnt"] if row else 0

    def update_baseline(self, snapshot_id: int, data: dict[str, Any]) -> None:
        """Store baseline signal analysis results on a snapshot."""
        self.db.execute(
            """UPDATE snapshots SET
               baseline_classification = ?,
               baseline_sentiment = ?,
               baseline_confidence = ?,
               baseline_keywords = ?,
               baseline_categories = ?,
               baseline_notes = ?
               WHERE id = ?""",
            (
                data.get("baseline_classification"),
                data.get("baseline_sentiment"),
                data.get("baseline_confidence"),
                json.dumps(data.get("baseline_keywords", [])),
                json.dumps(data.get("baseline_categories", [])),
                data.get("baseline_notes"),
                snapshot_id,
            ),
        )
        self.db.connection.commit()

    def has_baseline_for_company(self, company_id: int) -> bool:
        """Check if any snapshot for this company has baseline analysis."""
        row = self.db.fetchone(
            """SELECT COUNT(*) as cnt FROM snapshots
               WHERE company_id = ? AND baseline_classification IS NOT NULL""",
            (company_id,),
        )
        return (row["cnt"] if row else 0) > 0

    def get_snapshots_without_baseline(self, company_id: int | None = None) -> list[dict[str, Any]]:
        """Get snapshots that need baseline analysis.

        Returns only the earliest snapshot per company (baseline is once per company).
        If company_id is provided, filters to that company.
        """
        if company_id is not None:
            rows = self.db.fetchall(
                """SELECT s.* FROM snapshots s
                   WHERE s.company_id = ?
                   AND s.baseline_classification IS NULL
                   AND s.content_markdown IS NOT NULL
                   ORDER BY s.captured_at ASC
                   LIMIT 1""",
                (company_id,),
            )
        else:
            # One snapshot per company: the earliest one without baseline
            rows = self.db.fetchall(
                """SELECT s.* FROM snapshots s
                   INNER JOIN (
                       SELECT company_id, MIN(captured_at) as min_date
                       FROM snapshots
                       WHERE baseline_classification IS NULL
                       AND content_markdown IS NOT NULL
                       GROUP BY company_id
                   ) earliest ON s.company_id = earliest.company_id
                       AND s.captured_at = earliest.min_date
                   WHERE s.baseline_classification IS NULL
                   AND s.content_markdown IS NOT NULL"""
            )
        return [dict(row) for row in rows]
