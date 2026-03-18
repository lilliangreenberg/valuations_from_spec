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
               (company_id, status, confidence, indicators, last_checked,
                http_last_modified, is_manual_override, status_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["company_id"],
                data["status"],
                data["confidence"],
                json.dumps(data.get("indicators", [])),
                data["last_checked"],
                data.get("http_last_modified"),
                int(data.get("is_manual_override", False)),
                data.get("status_reason"),
            ),
        )
        self.db.connection.commit()
        return cursor.lastrowid or 0

    def get_latest_status(self, company_id: int) -> dict[str, Any] | None:
        """Get the most recent status for a company."""
        row = self.db.fetchone(
            """SELECT * FROM company_statuses
               WHERE company_id = ?
               ORDER BY id DESC
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
               ORDER BY cs.id DESC LIMIT 1""",
            (company_name,),
        )
        if row:
            return self._deserialize_row(row)
        return None

    def has_manual_override(self, company_id: int) -> bool:
        """Check if the latest status for a company is a manual override."""
        row = self.db.fetchone(
            """SELECT is_manual_override FROM company_statuses
               WHERE company_id = ?
               ORDER BY id DESC LIMIT 1""",
            (company_id,),
        )
        return bool(row["is_manual_override"]) if row else False

    def clear_manual_override(self, company_id: int) -> int:
        """Clear manual override by inserting a new non-manual status row.

        Copies the current status values with is_manual_override=0.
        Returns the new record ID, or 0 if no existing status found.
        """
        current = self.get_latest_status(company_id)
        if not current:
            return 0

        from datetime import UTC, datetime

        now_iso = datetime.now(UTC).isoformat()
        return self.store_status(
            {
                "company_id": company_id,
                "status": current["status"],
                "confidence": current["confidence"],
                "indicators": current.get("indicators", []),
                "last_checked": now_iso,
                "http_last_modified": current.get("http_last_modified"),
                "is_manual_override": False,
            }
        )

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
