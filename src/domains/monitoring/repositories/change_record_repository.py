"""Change record repository for database CRUD operations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.services.database import Database

logger = structlog.get_logger(__name__)


class ChangeRecordRepository:
    """Repository for change record data access."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def store_change_record(self, data: dict[str, Any]) -> int:
        """Store a new change record. Returns record ID."""
        cursor = self.db.execute(
            """INSERT INTO change_records
               (company_id, snapshot_id_old, snapshot_id_new, checksum_old, checksum_new,
                has_changed, change_magnitude, detected_at,
                significance_classification, significance_sentiment,
                significance_confidence, matched_keywords, matched_categories,
                significance_notes, evidence_snippets)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["company_id"],
                data["snapshot_id_old"],
                data["snapshot_id_new"],
                data["checksum_old"],
                data["checksum_new"],
                1 if data["has_changed"] else 0,
                data["change_magnitude"],
                data["detected_at"],
                data.get("significance_classification"),
                data.get("significance_sentiment"),
                data.get("significance_confidence"),
                json.dumps(data.get("matched_keywords", [])),
                json.dumps(data.get("matched_categories", [])),
                data.get("significance_notes"),
                json.dumps(data.get("evidence_snippets", [])),
            ),
        )
        self.db.connection.commit()
        return cursor.lastrowid or 0

    def get_changes_for_company(self, company_id: int) -> list[dict[str, Any]]:
        """Get all change records for a company."""
        rows = self.db.fetchall(
            "SELECT * FROM change_records WHERE company_id = ? ORDER BY detected_at DESC",
            (company_id,),
        )
        return [self._deserialize_row(row) for row in rows]

    def get_records_without_significance(self) -> list[dict[str, Any]]:
        """Get change records that haven't been analyzed for significance."""
        rows = self.db.fetchall(
            """SELECT * FROM change_records
               WHERE significance_classification IS NULL
               AND has_changed = 1
               ORDER BY detected_at"""
        )
        return [self._deserialize_row(row) for row in rows]

    def update_significance(self, record_id: int, data: dict[str, Any]) -> None:
        """Update significance fields on a change record."""
        self.db.execute(
            """UPDATE change_records SET
               significance_classification = ?,
               significance_sentiment = ?,
               significance_confidence = ?,
               matched_keywords = ?,
               matched_categories = ?,
               significance_notes = ?,
               evidence_snippets = ?
               WHERE id = ?""",
            (
                data.get("significance_classification"),
                data.get("significance_sentiment"),
                data.get("significance_confidence"),
                json.dumps(data.get("matched_keywords", [])),
                json.dumps(data.get("matched_categories", [])),
                data.get("significance_notes"),
                json.dumps(data.get("evidence_snippets", [])),
                record_id,
            ),
        )
        self.db.connection.commit()

    def get_significant_changes(
        self,
        days: int = 180,
        sentiment: str | None = None,
        min_confidence: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Get significant changes, optionally filtered."""
        sql = """SELECT cr.*, c.name as company_name
                 FROM change_records cr
                 JOIN companies c ON cr.company_id = c.id
                 WHERE cr.significance_classification = 'significant'
                 AND cr.significance_confidence >= ?
                 AND cr.detected_at >= datetime('now', ?)"""
        params: list[Any] = [min_confidence, f"-{days} days"]

        if sentiment:
            sql += " AND cr.significance_sentiment = ?"
            params.append(sentiment)

        sql += " ORDER BY cr.detected_at DESC"
        rows = self.db.fetchall(sql, tuple(params))
        return [self._deserialize_row(row) for row in rows]

    def get_uncertain_changes(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get changes classified as UNCERTAIN."""
        rows = self.db.fetchall(
            """SELECT cr.*, c.name as company_name
               FROM change_records cr
               JOIN companies c ON cr.company_id = c.id
               WHERE cr.significance_classification = 'uncertain'
               ORDER BY cr.detected_at DESC
               LIMIT ?""",
            (limit,),
        )
        return [self._deserialize_row(row) for row in rows]

    def _deserialize_row(self, row: Any) -> dict[str, Any]:
        """Deserialize JSON fields from a database row."""
        data = dict(row)
        for field in ("matched_keywords", "matched_categories", "evidence_snippets"):
            if data.get(field):
                try:
                    data[field] = json.loads(data[field])
                except (json.JSONDecodeError, TypeError):
                    data[field] = []
            else:
                data[field] = []
        return data
