"""Social media snapshot repository for database CRUD operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.services.database import Database

logger = structlog.get_logger(__name__)


class SocialSnapshotRepository:
    """Repository for social media snapshot data access."""

    def __init__(self, db: Database, operator: str) -> None:
        self.db = db
        self.operator = operator

    def store_snapshot(self, data: dict[str, Any]) -> int:
        """Store a new social media snapshot. Returns snapshot ID."""
        cursor = self.db.execute(
            """INSERT INTO social_media_snapshots
               (company_id, source_url, source_type, content_markdown, content_html,
                status_code, captured_at, error_message, content_checksum,
                latest_post_date, performed_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["company_id"],
                data["source_url"],
                data["source_type"],
                data.get("content_markdown"),
                data.get("content_html"),
                data.get("status_code"),
                data["captured_at"],
                data.get("error_message"),
                data.get("content_checksum"),
                data.get("latest_post_date"),
                self.operator,
            ),
        )
        self.db.connection.commit()
        return cursor.lastrowid or 0

    def get_latest_snapshots(
        self, company_id: int, source_url: str, limit: int = 2
    ) -> list[dict[str, Any]]:
        """Get the most recent snapshots for a company + source URL pair."""
        rows = self.db.fetchall(
            """SELECT * FROM social_media_snapshots
               WHERE company_id = ? AND source_url = ?
               ORDER BY captured_at DESC
               LIMIT ?""",
            (company_id, source_url, limit),
        )
        return [dict(row) for row in rows]

    def get_all_sources_for_company(self, company_id: int) -> list[dict[str, Any]]:
        """Get the latest snapshot for each source URL for a company.

        Returns one row per distinct source_url, ordered by source_type.
        """
        rows = self.db.fetchall(
            """SELECT s.* FROM social_media_snapshots s
               INNER JOIN (
                   SELECT source_url, MAX(captured_at) as max_date
                   FROM social_media_snapshots
                   WHERE company_id = ?
                   GROUP BY source_url
               ) latest ON s.source_url = latest.source_url
                   AND s.captured_at = latest.max_date
               WHERE s.company_id = ?
               ORDER BY s.source_type, s.source_url""",
            (company_id, company_id),
        )
        return [dict(row) for row in rows]

    def get_companies_with_multiple_snapshots(self) -> list[tuple[int, str]]:
        """Get (company_id, source_url) pairs that have 2+ snapshots."""
        rows = self.db.fetchall(
            """SELECT company_id, source_url FROM social_media_snapshots
               GROUP BY company_id, source_url
               HAVING COUNT(*) >= 2"""
        )
        return [(row["company_id"], row["source_url"]) for row in rows]
