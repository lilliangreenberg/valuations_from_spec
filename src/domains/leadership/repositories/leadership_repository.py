"""Leadership repository for database CRUD operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.services.database import Database

logger = structlog.get_logger(__name__)


class LeadershipRepository:
    """Repository for company leadership data access."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def store_leadership(self, data: dict[str, Any]) -> int:
        """Store a leadership record. Handles UNIQUE constraint via skip-on-duplicate."""
        try:
            cursor = self.db.execute(
                """INSERT INTO company_leadership
                   (company_id, person_name, title, linkedin_profile_url,
                    discovery_method, confidence, is_current, discovered_at,
                    last_verified_at, source_company_linkedin_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["company_id"],
                    data["person_name"],
                    data["title"],
                    data["linkedin_profile_url"],
                    data["discovery_method"],
                    data.get("confidence", 0.0),
                    1 if data.get("is_current", True) else 0,
                    data["discovered_at"],
                    data.get("last_verified_at"),
                    data.get("source_company_linkedin_url"),
                ),
            )
            self.db.connection.commit()
            return cursor.lastrowid or 0
        except Exception as exc:
            if "UNIQUE constraint" in str(exc):
                logger.debug(
                    "duplicate_leadership_skipped",
                    url=data.get("linkedin_profile_url"),
                )
                return 0
            raise

    def get_leadership_for_company(self, company_id: int) -> list[dict[str, Any]]:
        """Get all leadership records for a company (current and past)."""
        rows = self.db.fetchall(
            "SELECT * FROM company_leadership WHERE company_id = ? ORDER BY title",
            (company_id,),
        )
        return [dict(row) for row in rows]

    def get_current_leadership(self, company_id: int) -> list[dict[str, Any]]:
        """Get only current leadership records for a company."""
        rows = self.db.fetchall(
            """SELECT * FROM company_leadership
               WHERE company_id = ? AND is_current = 1
               ORDER BY title""",
            (company_id,),
        )
        return [dict(row) for row in rows]

    def leadership_exists(self, company_id: int, linkedin_profile_url: str) -> bool:
        """Check if a leadership record already exists."""
        row = self.db.fetchone(
            """SELECT id FROM company_leadership
               WHERE company_id = ? AND linkedin_profile_url = ?""",
            (company_id, linkedin_profile_url),
        )
        return row is not None

    def mark_not_current(self, company_id: int, linkedin_profile_url: str) -> None:
        """Mark a leadership record as no longer current (departed)."""
        self.db.execute(
            """UPDATE company_leadership
               SET is_current = 0
               WHERE company_id = ? AND linkedin_profile_url = ?""",
            (company_id, linkedin_profile_url),
        )
        self.db.connection.commit()
        logger.info(
            "leadership_marked_not_current",
            company_id=company_id,
            url=linkedin_profile_url,
        )

    def get_all_leadership(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get all leadership records across companies, joined with company name."""
        rows = self.db.fetchall(
            """SELECT cl.*, c.name as company_name
               FROM company_leadership cl
               JOIN companies c ON cl.company_id = c.id
               ORDER BY c.name, cl.title
               LIMIT ?""",
            (limit,),
        )
        return [dict(row) for row in rows]
