"""Contract tests for status override dashboard routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.domains.dashboard.app import create_app
from src.services.database import Database


@pytest.fixture()
def db(tmp_path: object) -> Database:
    """Create a fresh database for each test."""
    import pathlib

    db_path = str(pathlib.Path(str(tmp_path)) / "test.db")
    database = Database(db_path=db_path, check_same_thread=False)
    database.init_db()
    # Insert a test company
    database.execute(
        "INSERT INTO companies (id, name, homepage_url, source_sheet, created_at, updated_at)"
        " VALUES (1, 'TestCo', 'https://test.com', 'sheet1', '2026-01-01', '2026-01-01')"
    )
    database.connection.commit()
    return database


@pytest.fixture()
def client(db: Database) -> TestClient:
    app = create_app(database=db)
    return TestClient(app)


class TestSetStatusOverride:
    """Tests for POST /companies/{id}/status-override."""

    def test_set_override_returns_200(self, client: TestClient) -> None:
        resp = client.post(
            "/companies/1/status-override",
            data={"status": "likely_closed"},
        )
        assert resp.status_code == 200

    def test_set_override_contains_manual_label(self, client: TestClient) -> None:
        resp = client.post(
            "/companies/1/status-override",
            data={"status": "likely_closed"},
        )
        assert "MANUAL" in resp.text

    def test_set_override_contains_status_badge(self, client: TestClient) -> None:
        resp = client.post(
            "/companies/1/status-override",
            data={"status": "operational"},
        )
        assert "operational" in resp.text

    def test_set_override_persists_in_db(self, client: TestClient, db: Database) -> None:
        client.post(
            "/companies/1/status-override",
            data={"status": "likely_closed"},
        )
        row = db.fetchone(
            "SELECT status, is_manual_override FROM company_statuses"
            " WHERE company_id = 1 ORDER BY id DESC LIMIT 1"
        )
        assert row is not None
        assert row["status"] == "likely_closed"
        assert row["is_manual_override"] == 1


class TestClearStatusOverride:
    """Tests for POST /companies/{id}/status-override/clear."""

    def test_clear_returns_200(self, client: TestClient) -> None:
        # First set an override
        client.post(
            "/companies/1/status-override",
            data={"status": "likely_closed"},
        )
        # Then clear it
        resp = client.post("/companies/1/status-override/clear")
        assert resp.status_code == 200

    def test_clear_removes_manual_label(self, client: TestClient) -> None:
        client.post(
            "/companies/1/status-override",
            data={"status": "likely_closed"},
        )
        resp = client.post("/companies/1/status-override/clear")
        # The partial should not show MANUAL after clearing
        # (status is still likely_closed but not manual)
        assert "Clear Override" not in resp.text

    def test_clear_preserves_status_in_db(self, client: TestClient, db: Database) -> None:
        client.post(
            "/companies/1/status-override",
            data={"status": "uncertain"},
        )
        client.post("/companies/1/status-override/clear")
        row = db.fetchone(
            "SELECT status, is_manual_override FROM company_statuses"
            " WHERE company_id = 1 ORDER BY id DESC LIMIT 1"
        )
        assert row is not None
        assert row["status"] == "uncertain"
        assert row["is_manual_override"] == 0
