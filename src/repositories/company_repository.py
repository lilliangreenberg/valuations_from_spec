"""Company repository for database CRUD operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.services.database import Database

logger = structlog.get_logger(__name__)


class CompanyRepository:
    """Repository for company data access."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_company(
        self,
        name: str,
        homepage_url: str | None,
        source_sheet: str,
    ) -> int:
        """Insert or update a company. Returns company ID.

        Uses INSERT OR REPLACE on the UNIQUE(name, homepage_url) constraint.
        """
        now = datetime.now(UTC).isoformat()

        # Check if company exists
        existing = self.get_company_by_name_and_url(name, homepage_url)
        if existing:
            self.db.execute(
                "UPDATE companies SET source_sheet = ?, updated_at = ? WHERE id = ?",
                (source_sheet, now, existing["id"]),
            )
            self.db.connection.commit()
            return existing["id"]

        cursor = self.db.execute(
            """INSERT INTO companies
               (name, homepage_url, source_sheet, flagged_for_review,
                flag_reason, created_at, updated_at)
               VALUES (?, ?, ?, 0, NULL, ?, ?)""",
            (name, homepage_url, source_sheet, now, now),
        )
        self.db.connection.commit()
        return cursor.lastrowid or 0

    def get_company_by_id(self, company_id: int) -> dict[str, Any] | None:
        """Get a company by ID."""
        row = self.db.fetchone("SELECT * FROM companies WHERE id = ?", (company_id,))
        return dict(row) if row else None

    def get_company_by_name(self, name: str) -> dict[str, Any] | None:
        """Get a company by name (case-insensitive)."""
        row = self.db.fetchone("SELECT * FROM companies WHERE LOWER(name) = LOWER(?)", (name,))
        return dict(row) if row else None

    def get_company_by_name_and_url(
        self, name: str, homepage_url: str | None
    ) -> dict[str, Any] | None:
        """Get company by unique constraint (name + homepage_url)."""
        if homepage_url is None:
            row = self.db.fetchone(
                "SELECT * FROM companies WHERE name = ? AND homepage_url IS NULL",
                (name,),
            )
        else:
            row = self.db.fetchone(
                "SELECT * FROM companies WHERE name = ? AND homepage_url = ?",
                (name, homepage_url),
            )
        return dict(row) if row else None

    def get_all_companies(self) -> list[dict[str, Any]]:
        """Get all companies."""
        rows = self.db.fetchall("SELECT * FROM companies ORDER BY name")
        return [dict(row) for row in rows]

    def get_companies_with_homepage(self) -> list[dict[str, Any]]:
        """Get all companies that have a homepage URL."""
        rows = self.db.fetchall(
            "SELECT * FROM companies WHERE homepage_url IS NOT NULL ORDER BY name"
        )
        return [dict(row) for row in rows]

    def get_company_count(self) -> int:
        """Get total number of companies."""
        row = self.db.fetchone("SELECT COUNT(*) as count FROM companies")
        return row["count"] if row else 0

    def flag_company(self, company_id: int, reason: str) -> None:
        """Flag a company for manual review."""
        now = datetime.now(UTC).isoformat()
        self.db.execute(
            """UPDATE companies SET flagged_for_review = 1,
               flag_reason = ?, updated_at = ? WHERE id = ?""",
            (reason, now, company_id),
        )
        self.db.connection.commit()

    def store_processing_error(
        self,
        entity_type: str,
        entity_id: int | None,
        error_type: str,
        error_message: str,
        retry_count: int = 0,
    ) -> None:
        """Store a processing error for debugging."""
        now = datetime.now(UTC).isoformat()
        self.db.execute(
            """INSERT INTO processing_errors
               (entity_type, entity_id, error_type, error_message,
                retry_count, occurred_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (entity_type, entity_id, error_type, error_message, retry_count, now),
        )
        self.db.connection.commit()
