"""Leadership change event log repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.services.database import Database

logger = structlog.get_logger(__name__)


class LeadershipChangeRepository:
    """Append-only event log for leadership transitions.

    Every detected change (departure, new arrival, executive move) is
    recorded here. Rows are never updated or deleted in normal operation --
    this is an immutable history that the StatusAnalyzer and dashboard
    can query for recent critical changes.
    """

    def __init__(self, db: Database, operator: str) -> None:
        self.db = db
        self.operator = operator

    def store_change(self, data: dict[str, Any]) -> int:
        """Insert a single leadership change event. Returns the row ID."""
        cursor = self.db.execute(
            """INSERT INTO leadership_changes
               (company_id, change_type, person_name, title,
                linkedin_profile_url, severity, detected_at, confidence,
                discovery_method, context, performed_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["company_id"],
                data["change_type"],
                data["person_name"],
                data.get("title"),
                data.get("linkedin_profile_url"),
                data["severity"],
                data["detected_at"],
                data.get("confidence", 0.0),
                data.get("discovery_method"),
                data.get("context"),
                self.operator,
            ),
        )
        self.db.connection.commit()
        return cursor.lastrowid or 0

    def store_changes(self, events: list[dict[str, Any]]) -> int:
        """Insert multiple leadership change events in a single transaction.

        Returns the number of rows inserted.
        """
        if not events:
            return 0

        rows = [
            (
                e["company_id"],
                e["change_type"],
                e["person_name"],
                e.get("title"),
                e.get("linkedin_profile_url"),
                e["severity"],
                e["detected_at"],
                e.get("confidence", 0.0),
                e.get("discovery_method"),
                e.get("context"),
                self.operator,
            )
            for e in events
        ]
        self.db.connection.executemany(
            """INSERT INTO leadership_changes
               (company_id, change_type, person_name, title,
                linkedin_profile_url, severity, detected_at, confidence,
                discovery_method, context, performed_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self.db.connection.commit()
        return len(rows)

    def get_changes_for_company(
        self,
        company_id: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return the full change history for a company, newest first."""
        rows = self.db.fetchall(
            """SELECT * FROM leadership_changes
               WHERE company_id = ?
               ORDER BY detected_at DESC
               LIMIT ?""",
            (company_id, limit),
        )
        return [dict(row) for row in rows]

    def get_recent_changes(
        self,
        days: int = 90,
        severity: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return recent changes across all companies, joined with company name.

        Args:
            days: Lookback window in days.
            severity: If provided, filter to that severity only.
            limit: Max rows to return.
        """
        sql = """SELECT lc.*, c.name AS company_name
                 FROM leadership_changes lc
                 JOIN companies c ON lc.company_id = c.id
                 WHERE lc.detected_at >= datetime('now', ?)"""
        params: list[Any] = [f"-{days} days"]

        if severity:
            sql += " AND lc.severity = ?"
            params.append(severity)

        sql += " ORDER BY lc.detected_at DESC LIMIT ?"
        params.append(limit)

        rows = self.db.fetchall(sql, tuple(params))
        return [dict(row) for row in rows]

    def get_recent_changes_by_company(
        self,
        days: int = 90,
    ) -> dict[int, list[dict[str, Any]]]:
        """Return recent changes grouped by company_id.

        Single query used by batch callers (status analyzer) to avoid
        a per-company query round trip.
        """
        rows = self.db.fetchall(
            """SELECT * FROM leadership_changes
               WHERE detected_at >= datetime('now', ?)
               ORDER BY detected_at DESC""",
            (f"-{days} days",),
        )
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            data = dict(row)
            grouped.setdefault(int(data["company_id"]), []).append(data)
        return grouped

    def get_critical_changes_for_company(
        self,
        company_id: int,
        days: int = 90,
    ) -> list[dict[str, Any]]:
        """Return critical-severity changes for a single company in the window.

        This is the query StatusAnalyzer will use to downgrade companies
        with recent CEO/founder departures.
        """
        rows = self.db.fetchall(
            """SELECT * FROM leadership_changes
               WHERE company_id = ?
                 AND severity = 'critical'
                 AND detected_at >= datetime('now', ?)
               ORDER BY detected_at DESC""",
            (company_id, f"-{days} days"),
        )
        return [dict(row) for row in rows]
