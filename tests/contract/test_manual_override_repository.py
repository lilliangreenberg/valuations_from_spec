"""Contract tests for manual status override repository methods."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from src.domains.monitoring.repositories.company_status_repository import (
    CompanyStatusRepository,
)
from src.services.database import Database


@pytest.fixture()
def db(tmp_path: object) -> Database:
    """Create a fresh in-memory database for each test."""
    import pathlib

    db_path = str(pathlib.Path(str(tmp_path)) / "test.db")
    database = Database(db_path=db_path)
    database.init_db()
    # Insert a test company
    database.execute(
        "INSERT INTO companies (id, name, homepage_url, source_sheet, created_at, updated_at)"
        " VALUES (1, 'TestCo', 'https://test.com', 'sheet1', '2026-01-01', '2026-01-01')"
    )
    database.connection.commit()
    return database


@pytest.fixture()
def repo(db: Database) -> CompanyStatusRepository:
    return CompanyStatusRepository(db)


class TestStoreStatusWithManualOverride:
    """Tests for store_status with is_manual_override field."""

    def test_store_manual_override(self, repo: CompanyStatusRepository) -> None:
        record_id = repo.store_status(
            {
                "company_id": 1,
                "status": "likely_closed",
                "confidence": 1.0,
                "indicators": [{"type": "manual", "value": "test", "signal": "neutral"}],
                "last_checked": datetime.now(UTC).isoformat(),
                "is_manual_override": True,
            }
        )
        assert record_id > 0

        latest = repo.get_latest_status(1)
        assert latest is not None
        assert latest["is_manual_override"] == 1

    def test_store_automatic_status_default(self, repo: CompanyStatusRepository) -> None:
        repo.store_status(
            {
                "company_id": 1,
                "status": "operational",
                "confidence": 0.8,
                "indicators": [],
                "last_checked": datetime.now(UTC).isoformat(),
            }
        )
        latest = repo.get_latest_status(1)
        assert latest is not None
        assert latest["is_manual_override"] == 0


class TestHasManualOverride:
    """Tests for has_manual_override()."""

    def test_returns_true_when_manual(self, repo: CompanyStatusRepository) -> None:
        repo.store_status(
            {
                "company_id": 1,
                "status": "likely_closed",
                "confidence": 1.0,
                "indicators": json.dumps([]),
                "last_checked": datetime.now(UTC).isoformat(),
                "is_manual_override": True,
            }
        )
        assert repo.has_manual_override(1) is True

    def test_returns_false_when_automatic(self, repo: CompanyStatusRepository) -> None:
        repo.store_status(
            {
                "company_id": 1,
                "status": "operational",
                "confidence": 0.8,
                "indicators": json.dumps([]),
                "last_checked": datetime.now(UTC).isoformat(),
            }
        )
        assert repo.has_manual_override(1) is False

    def test_returns_false_when_no_status(self, repo: CompanyStatusRepository) -> None:
        assert repo.has_manual_override(1) is False

    def test_returns_false_for_nonexistent_company(self, repo: CompanyStatusRepository) -> None:
        assert repo.has_manual_override(999) is False


class TestClearManualOverride:
    """Tests for clear_manual_override()."""

    def test_clear_inserts_new_row(self, repo: CompanyStatusRepository) -> None:
        repo.store_status(
            {
                "company_id": 1,
                "status": "likely_closed",
                "confidence": 1.0,
                "indicators": json.dumps([]),
                "last_checked": "2026-03-15T00:00:00+00:00",
                "is_manual_override": True,
            }
        )
        assert repo.has_manual_override(1) is True

        new_id = repo.clear_manual_override(1)
        assert new_id > 0
        assert repo.has_manual_override(1) is False

    def test_clear_preserves_status_value(self, repo: CompanyStatusRepository) -> None:
        repo.store_status(
            {
                "company_id": 1,
                "status": "likely_closed",
                "confidence": 1.0,
                "indicators": json.dumps([]),
                "last_checked": "2026-03-15T00:00:00+00:00",
                "is_manual_override": True,
            }
        )
        repo.clear_manual_override(1)

        latest = repo.get_latest_status(1)
        assert latest is not None
        assert latest["status"] == "likely_closed"
        assert latest["is_manual_override"] == 0

    def test_clear_returns_zero_when_no_status(self, repo: CompanyStatusRepository) -> None:
        assert repo.clear_manual_override(1) == 0

    def test_override_clear_cycle(self, repo: CompanyStatusRepository) -> None:
        """Set override, clear it, set again -- all append-only."""
        repo.store_status(
            {
                "company_id": 1,
                "status": "likely_closed",
                "confidence": 1.0,
                "indicators": json.dumps([]),
                "last_checked": "2026-03-15T00:00:00+00:00",
                "is_manual_override": True,
            }
        )
        repo.clear_manual_override(1)
        repo.store_status(
            {
                "company_id": 1,
                "status": "uncertain",
                "confidence": 1.0,
                "indicators": json.dumps([]),
                "last_checked": "2026-03-16T00:00:00+00:00",
                "is_manual_override": True,
            }
        )

        latest = repo.get_latest_status(1)
        assert latest is not None
        assert latest["status"] == "uncertain"
        assert latest["is_manual_override"] == 1
