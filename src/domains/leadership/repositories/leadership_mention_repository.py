"""Leadership mention repository for database CRUD operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.services.database import Database

logger = structlog.get_logger(__name__)


class LeadershipMentionRepository:
    """Repository for leadership name mentions extracted from website content."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def store_mention(self, data: dict[str, Any]) -> int:
        """Store a leadership mention.

        Uses explicit mention_exists() check before INSERT.
        Returns row ID if stored, 0 if duplicate skipped.
        """
        company_id = data["company_id"]
        person_name = data["person_name"]
        title_context = data["title_context"]

        if self.mention_exists(company_id, person_name, title_context):
            logger.debug(
                "duplicate_mention_skipped",
                company_id=company_id,
                person_name=person_name,
                title_context=title_context,
            )
            return 0

        cursor = self.db.execute(
            """INSERT INTO leadership_mentions
               (company_id, person_name, title_context, source, source_url,
                confidence, priority, extracted_at, snapshot_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                company_id,
                person_name,
                title_context,
                data["source"],
                data.get("source_url"),
                data.get("confidence", 0.5),
                data.get("priority", 4),
                data["extracted_at"],
                data.get("snapshot_id"),
            ),
        )
        self.db.connection.commit()
        logger.info(
            "leadership_mention_stored",
            company_id=company_id,
            person_name=person_name,
            title_context=title_context,
        )
        return cursor.lastrowid or 0

    def get_mentions_for_company(self, company_id: int) -> list[dict[str, Any]]:
        """Get all leadership mentions for a company, ordered by priority asc (best first)."""
        rows = self.db.fetchall(
            """SELECT * FROM leadership_mentions
               WHERE company_id = ?
               ORDER BY priority ASC, confidence DESC""",
            (company_id,),
        )
        return [dict(row) for row in rows]

    def get_ceo_mentions(self, company_id: int) -> list[dict[str, Any]]:
        """Get CEO/founder mentions for a company, ordered by priority asc (best first).

        Filters to CEO, Founder, Co-Founder, President title contexts.
        """
        rows = self.db.fetchall(
            """SELECT * FROM leadership_mentions
               WHERE company_id = ?
               AND (
                   LOWER(title_context) LIKE '%ceo%'
                   OR LOWER(title_context) LIKE '%founder%'
                   OR LOWER(title_context) LIKE '%president%'
                   OR LOWER(title_context) LIKE '%chief executive%'
               )
               ORDER BY priority ASC, confidence DESC""",
            (company_id,),
        )
        return [dict(row) for row in rows]

    def mention_exists(self, company_id: int, person_name: str, title_context: str) -> bool:
        """Check if a specific mention already exists."""
        row = self.db.fetchone(
            """SELECT id FROM leadership_mentions
               WHERE company_id = ? AND person_name = ? AND title_context = ?""",
            (company_id, person_name, title_context),
        )
        return row is not None

    def get_latest_mention_date(self, company_id: int) -> str | None:
        """Get the most recent extraction date for a company's mentions.

        Useful for freshness checks to avoid redundant re-extraction.
        """
        row = self.db.fetchone(
            """SELECT MAX(extracted_at) as latest
               FROM leadership_mentions
               WHERE company_id = ?""",
            (company_id,),
        )
        if row and row["latest"]:
            return str(row["latest"])
        return None
