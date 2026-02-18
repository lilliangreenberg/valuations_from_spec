"""Company status repository for database CRUD operations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.services.database import Database

logger = structlog.get_logger(__name__)


class CompanyStatusRepository:
    """Repository for company status data access."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def store_status(self, data: dict[str, Any]) -> int:
        """Store a new company status record. Returns record ID."""
        cursor = self.db.execute(
            """INSERT INTO company_statuses
               (company_id, status, confidence, indicators, last_checked, http_last_modified)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                data["company_id"],
                data["status"],
                data["confidence"],
                json.dumps(data.get("indicators", [])),
                data["last_checked"],
                data.get("http_last_modified"),
            ),
        )
        self.db.connection.commit()
        return cursor.lastrowid or 0

    def get_latest_status(self, company_id: int) -> dict[str, Any] | None:
        """Get the most recent status for a company."""
        row = self.db.fetchone(
            """SELECT * FROM company_statuses
               WHERE company_id = ?
               ORDER BY last_checked DESC
               LIMIT 1""",
            (company_id,),
        )
        if row:
            return self._deserialize_row(row)
        return None

    def get_status_by_company_name(self, company_name: str) -> dict[str, Any] | None:
        """Get status by company name."""
        row = self.db.fetchone(
            """SELECT cs.* FROM company_statuses cs
               JOIN companies c ON cs.company_id = c.id
               WHERE LOWER(c.name) = LOWER(?)
               ORDER BY cs.last_checked DESC LIMIT 1""",
            (company_name,),
        )
        if row:
            return self._deserialize_row(row)
        return None

    def _deserialize_row(self, row: Any) -> dict[str, Any]:
        """Deserialize JSON fields."""
        data = dict(row)
        if data.get("indicators"):
            try:
                data["indicators"] = json.loads(data["indicators"])
            except (json.JSONDecodeError, TypeError):
                data["indicators"] = []
        else:
            data["indicators"] = []
        return data
