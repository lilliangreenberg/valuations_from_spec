"""Repository for LinkedIn snapshot data access."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.services.database import Database

logger = structlog.get_logger(__name__)


class LinkedInSnapshotRepository:
    """Repository for LinkedIn page snapshot storage and retrieval."""

    def __init__(self, db: Database, operator: str) -> None:
        self.db = db
        self.operator = operator

    def store_snapshot(self, data: dict[str, Any]) -> int:
        """Store a LinkedIn snapshot record.

        Args:
            data: Dict with keys: company_id, linkedin_url, url_type,
                  person_name (optional), content_html, content_json,
                  vision_data_json, screenshot_path, captured_at

        Returns:
            Row ID of the stored snapshot.
        """
        content_html = data.get("content_html", "")
        content_checksum = _compute_checksum(content_html) if content_html else None

        cursor = self.db.execute(
            """INSERT INTO linkedin_snapshots
               (company_id, linkedin_url, url_type, person_name,
                content_html, content_json, vision_data_json,
                screenshot_path, content_checksum, captured_at, performed_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["company_id"],
                data["linkedin_url"],
                data["url_type"],
                data.get("person_name"),
                content_html,
                data.get("content_json"),
                data.get("vision_data_json"),
                data.get("screenshot_path"),
                content_checksum,
                data["captured_at"],
                self.operator,
            ),
        )

        row_id = cursor.lastrowid or 0
        logger.info(
            "linkedin_snapshot_stored",
            id=row_id,
            company_id=data["company_id"],
            url_type=data["url_type"],
            linkedin_url=data["linkedin_url"],
        )
        return row_id

    def get_latest_snapshot(
        self,
        company_id: int,
        linkedin_url: str,
    ) -> dict[str, Any] | None:
        """Get the most recent snapshot for a company/URL combination.

        Returns:
            Snapshot dict or None if no snapshots exist.
        """
        rows = self.db.fetchall(
            """SELECT * FROM linkedin_snapshots
               WHERE company_id = ? AND linkedin_url = ?
               ORDER BY captured_at DESC LIMIT 1""",
            (company_id, linkedin_url),
        )
        if rows:
            return dict(rows[0])
        return None

    def get_snapshots_for_company(self, company_id: int) -> list[dict[str, Any]]:
        """Get all LinkedIn snapshots for a company, newest first."""
        rows = self.db.fetchall(
            """SELECT * FROM linkedin_snapshots
               WHERE company_id = ?
               ORDER BY captured_at DESC""",
            (company_id,),
        )
        return [dict(r) for r in rows]

    def get_person_snapshots(
        self,
        company_id: int,
        person_name: str,
    ) -> list[dict[str, Any]]:
        """Get all snapshots for a specific person at a company."""
        rows = self.db.fetchall(
            """SELECT * FROM linkedin_snapshots
               WHERE company_id = ? AND person_name = ?
               ORDER BY captured_at DESC""",
            (company_id, person_name),
        )
        return [dict(r) for r in rows]

    def get_latest_company_snapshot(self, company_id: int) -> dict[str, Any] | None:
        """Get the most recent company-type snapshot for a company."""
        rows = self.db.fetchall(
            """SELECT * FROM linkedin_snapshots
               WHERE company_id = ? AND url_type = 'company'
               ORDER BY captured_at DESC LIMIT 1""",
            (company_id,),
        )
        if rows:
            return dict(rows[0])
        return None

    def get_latest_person_snapshot(
        self,
        company_id: int,
        linkedin_url: str,
    ) -> dict[str, Any] | None:
        """Get the most recent person-type snapshot for a specific profile URL."""
        rows = self.db.fetchall(
            """SELECT * FROM linkedin_snapshots
               WHERE company_id = ? AND linkedin_url = ? AND url_type = 'person'
               ORDER BY captured_at DESC LIMIT 1""",
            (company_id, linkedin_url),
        )
        if rows:
            return dict(rows[0])
        return None


def _compute_checksum(content: str) -> str:
    """Compute MD5 checksum of content (lowercase hex, 32 chars)."""
    return hashlib.md5(content.encode("utf-8")).hexdigest()
