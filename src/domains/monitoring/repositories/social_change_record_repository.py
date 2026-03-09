"""Social media change record repository for database CRUD operations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.services.database import Database

logger = structlog.get_logger(__name__)


class SocialChangeRecordRepository:
    """Repository for social media change record data access."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def store_change_record(self, data: dict[str, Any]) -> int:
        """Store a new social media change record. Returns record ID."""
        cursor = self.db.execute(
            """INSERT INTO social_media_change_records
               (company_id, source_url, source_type,
                snapshot_id_old, snapshot_id_new,
                checksum_old, checksum_new,
                has_changed, change_magnitude, detected_at,
                significance_classification, significance_sentiment,
                significance_confidence, matched_keywords, matched_categories,
                significance_notes, evidence_snippets)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["company_id"],
                data["source_url"],
                data["source_type"],
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
        """Get all social media change records for a company."""
        rows = self.db.fetchall(
            """SELECT * FROM social_media_change_records
               WHERE company_id = ?
               ORDER BY detected_at DESC""",
            (company_id,),
        )
        return [self._deserialize_row(row) for row in rows]

    def get_significant_changes(
        self,
        days: int = 180,
        sentiment: str | None = None,
        min_confidence: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Get significant social media changes, optionally filtered."""
        sql = """SELECT smcr.*, c.name as company_name, c.homepage_url as homepage_url
                 FROM social_media_change_records smcr
                 JOIN companies c ON smcr.company_id = c.id
                 WHERE smcr.significance_classification = 'significant'
                 AND smcr.significance_confidence >= ?
                 AND smcr.detected_at >= datetime('now', ?)"""
        params: list[Any] = [min_confidence, f"-{days} days"]

        if sentiment:
            sql += " AND smcr.significance_sentiment = ?"
            params.append(sentiment)

        sql += " ORDER BY smcr.detected_at DESC"
        rows = self.db.fetchall(sql, tuple(params))
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
