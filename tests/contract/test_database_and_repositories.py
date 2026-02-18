"""Contract tests for Database service and all repositories.

Uses a REAL temporary SQLite database (no mocking the DB), but does not call
external APIs. Each test sets up its own data using the shared fixtures.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.domains.discovery.repositories.social_media_link_repository import (
    SocialMediaLinkRepository,
)
from src.domains.monitoring.repositories.change_record_repository import (
    ChangeRecordRepository,
)
from src.domains.monitoring.repositories.company_status_repository import (
    CompanyStatusRepository,
)
from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
from src.domains.news.repositories.news_article_repository import (
    NewsArticleRepository,
)
from src.repositories.company_repository import CompanyRepository
from src.services.database import Database

# Type alias to keep method signatures under 100 chars
DbWithCompany = tuple[Database, int]

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _past_iso(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _insert_company(
    db: Database,
    name: str = "Helper Corp",
    url: str = "https://helper.com",
) -> int:
    """Insert a company directly and return its ID."""
    now = _now_iso()
    cursor = db.execute(
        """INSERT INTO companies
           (name, homepage_url, source_sheet,
            flagged_for_review, created_at, updated_at)
           VALUES (?, ?, 'Test Sheet', 0, ?, ?)""",
        (name, url, now, now),
    )
    db.connection.commit()
    return cursor.lastrowid or 0


def _insert_snapshot(
    db: Database,
    company_id: int,
    captured_at: str | None = None,
    content: str | None = None,
) -> int:
    """Insert a minimal snapshot and return its ID."""
    captured = captured_at or _now_iso()
    markdown = content or "# Hello"
    cursor = db.execute(
        """INSERT INTO snapshots
           (company_id, url, content_markdown, content_html, status_code,
            captured_at, has_paywall, has_auth_required, content_checksum)
           VALUES (?, 'https://example.com', ?,
            '<h1>Hello</h1>', 200, ?, 0, 0, 'abc123')""",
        (company_id, markdown, captured),
    )
    db.connection.commit()
    return cursor.lastrowid or 0


# ===========================================================================
# Section 1: Database service tests
# ===========================================================================


class TestDatabaseInitialization:
    """Verify init_db creates all expected tables and indexes."""

    EXPECTED_TABLES = [
        "companies",
        "snapshots",
        "change_records",
        "company_statuses",
        "social_media_links",
        "blog_links",
        "news_articles",
        "processing_errors",
        "company_logos",
        "company_leadership",
    ]

    EXPECTED_INDEXES = [
        "idx_companies_name",
        "idx_snapshots_company_id",
        "idx_snapshots_captured_at",
        "idx_change_records_company_id",
        "idx_social_media_links_company_id",
        "idx_social_media_links_platform",
        "idx_news_articles_company_id",
        "idx_news_articles_published_at",
        "idx_news_articles_significance",
        "idx_company_logos_company_id",
        "idx_company_logos_perceptual_hash",
        "idx_company_leadership_company_id",
        "idx_company_leadership_title",
    ]

    def test_all_tables_created(self, db: Database) -> None:
        rows = db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        table_names = {row["name"] for row in rows}
        for expected in self.EXPECTED_TABLES:
            assert expected in table_names, f"Table '{expected}' missing from schema"

    def test_exactly_ten_tables(self, db: Database) -> None:
        rows = db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        assert len(rows) == 10

    def test_all_indexes_created(self, db: Database) -> None:
        rows = db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        )
        index_names = {row["name"] for row in rows}
        for expected in self.EXPECTED_INDEXES:
            assert expected in index_names, f"Index '{expected}' missing from schema"

    def test_wal_mode_enabled(self, db: Database) -> None:
        row = db.fetchone("PRAGMA journal_mode")
        assert row is not None
        assert row[0] == "wal"

    def test_foreign_keys_enabled(self, db: Database) -> None:
        row = db.fetchone("PRAGMA foreign_keys")
        assert row is not None
        assert row[0] == 1

    def test_row_factory_returns_sqlite_row(self, db: Database) -> None:
        """Connection should use sqlite3.Row so columns are accessible by name."""
        assert db.connection.row_factory is sqlite3.Row

    def test_idempotent_init(self, tmp_db_path: str) -> None:
        """Calling init_db twice should not raise."""
        database = Database(db_path=tmp_db_path)
        database.init_db()
        database.init_db()
        rows = database.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        assert len(rows) == 10


class TestDatabaseTransaction:
    """Verify the transaction context manager commits and rolls back correctly."""

    def test_transaction_commits_on_success(self, db: Database) -> None:
        company_id = _insert_company(db)
        with db.transaction() as cursor:
            cursor.execute(
                "UPDATE companies SET flag_reason = 'test' WHERE id = ?",
                (company_id,),
            )
        row = db.fetchone("SELECT flag_reason FROM companies WHERE id = ?", (company_id,))
        assert row is not None
        assert row["flag_reason"] == "test"

    def test_transaction_rolls_back_on_exception(self, db: Database) -> None:
        company_id = _insert_company(db)
        with pytest.raises(ValueError, match="deliberate"), db.transaction() as cursor:
            cursor.execute(
                "UPDATE companies SET flag_reason = 'should_not_persist' WHERE id = ?",
                (company_id,),
            )
            raise ValueError("deliberate error")
        row = db.fetchone("SELECT flag_reason FROM companies WHERE id = ?", (company_id,))
        assert row is not None
        assert row["flag_reason"] is None


class TestDatabaseExecuteMethods:
    """Verify execute, fetchone, fetchall work correctly."""

    def test_execute_returns_cursor(self, db: Database) -> None:
        cursor = db.execute("SELECT 1 AS val")
        assert isinstance(cursor, sqlite3.Cursor)

    def test_fetchone_returns_row(self, db: Database) -> None:
        row = db.fetchone("SELECT 42 AS answer")
        assert row is not None
        assert row["answer"] == 42

    def test_fetchone_returns_none_for_no_match(self, db: Database) -> None:
        row = db.fetchone("SELECT * FROM companies WHERE id = -1")
        assert row is None

    def test_fetchall_returns_list(self, db: Database) -> None:
        _insert_company(db, name="A Corp", url="https://a.com")
        _insert_company(db, name="B Corp", url="https://b.com")
        rows = db.fetchall("SELECT * FROM companies")
        assert isinstance(rows, list)
        assert len(rows) >= 2


class TestDatabaseUniqueConstraints:
    """Verify UNIQUE constraints raise IntegrityError on duplicates."""

    def test_companies_unique_name_url(self, db: Database) -> None:
        _insert_company(db, name="Dupe Corp", url="https://dupe.com")
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            _insert_company(db, name="Dupe Corp", url="https://dupe.com")

    def test_social_media_links_unique_company_profile(
        self, db_with_company: DbWithCompany
    ) -> None:
        db, company_id = db_with_company
        now = _now_iso()
        sql = """INSERT INTO social_media_links
            (company_id, platform, profile_url,
             discovery_method, verification_status,
             discovered_at)
            VALUES (?, 'linkedin',
             'https://linkedin.com/company/test',
             'html', 'unverified', ?)"""
        db.execute(sql, (company_id, now))
        db.connection.commit()
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            db.execute(sql, (company_id, now))

    def test_news_articles_unique_content_url(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        now = _now_iso()
        url = "https://news.example.com/article1"
        db.execute(
            """INSERT INTO news_articles
               (company_id, title, content_url, source,
                published_at, discovered_at, match_confidence)
               VALUES (?, 'Title', ?, 'kagi', ?, ?, 0.8)""",
            (company_id, url, now, now),
        )
        db.connection.commit()
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            db.execute(
                """INSERT INTO news_articles
                   (company_id, title, content_url, source,
                    published_at, discovered_at,
                    match_confidence)
                   VALUES (?, 'Other', ?, 'kagi', ?, ?, 0.9)""",
                (company_id, url, now, now),
            )

    def test_blog_links_unique_company_blog_url(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        now = _now_iso()
        db.execute(
            """INSERT INTO blog_links
               (company_id, blog_type, blog_url, discovery_method, is_active, discovered_at)
               VALUES (?, 'company', 'https://blog.test.com', 'html', 1, ?)""",
            (company_id, now),
        )
        db.connection.commit()
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            db.execute(
                """INSERT INTO blog_links
                   (company_id, blog_type, blog_url, discovery_method, is_active, discovered_at)
                   VALUES (?, 'company', 'https://blog.test.com', 'html', 1, ?)""",
                (company_id, now),
            )

    def test_company_logos_unique_company_hash(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        now = _now_iso()
        db.execute(
            """INSERT INTO company_logos
               (company_id, image_data, image_format,
                perceptual_hash, source_url,
                extraction_location, extracted_at)
               VALUES (?, X'89504E47', 'png', 'abcd1234',
                'https://img.com/logo.png', 'header', ?)""",
            (company_id, now),
        )
        db.connection.commit()
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            db.execute(
                """INSERT INTO company_logos
                   (company_id, image_data, image_format,
                    perceptual_hash, source_url,
                    extraction_location, extracted_at)
                   VALUES (?, X'89504E47', 'png', 'abcd1234',
                    'https://img.com/logo2.png',
                    'footer', ?)""",
                (company_id, now),
            )


class TestDatabaseForeignKeyCascade:
    """Verify ON DELETE CASCADE cleans up child rows when a company is deleted."""

    def test_cascade_deletes_snapshots(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        _insert_snapshot(db, company_id)
        _insert_snapshot(db, company_id)
        rows_before = db.fetchall("SELECT * FROM snapshots WHERE company_id = ?", (company_id,))
        assert len(rows_before) == 2

        db.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        db.connection.commit()
        rows_after = db.fetchall("SELECT * FROM snapshots WHERE company_id = ?", (company_id,))
        assert len(rows_after) == 0

    def test_cascade_deletes_social_media_links(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        now = _now_iso()
        db.execute(
            """INSERT INTO social_media_links
               (company_id, platform, profile_url,
                discovery_method, verification_status,
                discovered_at)
               VALUES (?, 'twitter',
                'https://twitter.com/test',
                'html', 'unverified', ?)""",
            (company_id, now),
        )
        db.connection.commit()
        row = db.fetchone(
            "SELECT id FROM social_media_links WHERE company_id = ?",
            (company_id,),
        )
        assert row is not None

        db.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        db.connection.commit()
        row = db.fetchone(
            "SELECT id FROM social_media_links WHERE company_id = ?",
            (company_id,),
        )
        assert row is None

    def test_cascade_deletes_change_records(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        snap_old = _insert_snapshot(db, company_id, captured_at=_past_iso(10))
        snap_new = _insert_snapshot(db, company_id)
        now = _now_iso()
        db.execute(
            """INSERT INTO change_records
               (company_id, snapshot_id_old, snapshot_id_new, checksum_old, checksum_new,
                has_changed, change_magnitude, detected_at)
               VALUES (?, ?, ?, 'aaa', 'bbb', 1, 'MODERATE', ?)""",
            (company_id, snap_old, snap_new, now),
        )
        db.connection.commit()

        db.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        db.connection.commit()
        rows = db.fetchall("SELECT * FROM change_records WHERE company_id = ?", (company_id,))
        assert len(rows) == 0

    def test_cascade_deletes_company_statuses(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        now = _now_iso()
        db.execute(
            """INSERT INTO company_statuses
               (company_id, status, confidence,
                indicators, last_checked)
               VALUES (?, 'operational', 0.9, '[]', ?)""",
            (company_id, now),
        )
        db.connection.commit()

        db.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        db.connection.commit()
        row = db.fetchone(
            "SELECT id FROM company_statuses WHERE company_id = ?",
            (company_id,),
        )
        assert row is None

    def test_cascade_deletes_news_articles(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        now = _now_iso()
        db.execute(
            """INSERT INTO news_articles
               (company_id, title, content_url, source,
                published_at, discovered_at,
                match_confidence)
               VALUES (?, 'News', 'https://news.com/1',
                'kagi', ?, ?, 0.85)""",
            (company_id, now, now),
        )
        db.connection.commit()

        db.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        db.connection.commit()
        row = db.fetchone(
            "SELECT id FROM news_articles WHERE company_id = ?",
            (company_id,),
        )
        assert row is None

    def test_cascade_deletes_blog_links(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        now = _now_iso()
        db.execute(
            """INSERT INTO blog_links
               (company_id, blog_type, blog_url,
                discovery_method, is_active, discovered_at)
               VALUES (?, 'company',
                'https://blog.test.com', 'html', 1, ?)""",
            (company_id, now),
        )
        db.connection.commit()

        db.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        db.connection.commit()
        row = db.fetchone(
            "SELECT id FROM blog_links WHERE company_id = ?",
            (company_id,),
        )
        assert row is None

    def test_cascade_deletes_company_logos(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        now = _now_iso()
        db.execute(
            """INSERT INTO company_logos
               (company_id, image_data, image_format,
                perceptual_hash, source_url,
                extraction_location, extracted_at)
               VALUES (?, X'89504E47', 'png', 'hash123',
                'https://img.com/logo.png', 'header', ?)""",
            (company_id, now),
        )
        db.connection.commit()

        db.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        db.connection.commit()
        row = db.fetchone(
            "SELECT id FROM company_logos WHERE company_id = ?",
            (company_id,),
        )
        assert row is None


# ===========================================================================
# Section 2: CompanyRepository tests
# ===========================================================================


class TestCompanyRepositoryUpsert:
    """Test upsert_company insert and update behavior."""

    def test_upsert_creates_new_company(self, db: Database) -> None:
        repo = CompanyRepository(db)
        company_id = repo.upsert_company("New Corp", "https://new.com", "Sheet1")
        assert company_id > 0

        company = repo.get_company_by_id(company_id)
        assert company is not None
        assert company["name"] == "New Corp"
        assert company["homepage_url"] == "https://new.com"
        assert company["source_sheet"] == "Sheet1"

    def test_upsert_updates_existing_company(self, db: Database) -> None:
        repo = CompanyRepository(db)
        first_id = repo.upsert_company("Existing Corp", "https://existing.com", "Sheet1")
        second_id = repo.upsert_company("Existing Corp", "https://existing.com", "Sheet2")
        assert first_id == second_id

        company = repo.get_company_by_id(first_id)
        assert company is not None
        assert company["source_sheet"] == "Sheet2"

    def test_upsert_different_url_creates_new(self, db: Database) -> None:
        repo = CompanyRepository(db)
        id_a = repo.upsert_company("Corp", "https://a.com", "Sheet1")
        id_b = repo.upsert_company("Corp", "https://b.com", "Sheet1")
        assert id_a != id_b

    def test_upsert_with_null_homepage(self, db: Database) -> None:
        repo = CompanyRepository(db)
        company_id = repo.upsert_company("No URL Corp", None, "Sheet1")
        assert company_id > 0

        company = repo.get_company_by_id(company_id)
        assert company is not None
        assert company["homepage_url"] is None

    def test_upsert_null_url_then_update(self, db: Database) -> None:
        repo = CompanyRepository(db)
        first_id = repo.upsert_company("Null URL Corp", None, "Sheet1")
        second_id = repo.upsert_company("Null URL Corp", None, "Sheet2")
        assert first_id == second_id

        company = repo.get_company_by_id(first_id)
        assert company is not None
        assert company["source_sheet"] == "Sheet2"


class TestCompanyRepositoryGet:
    """Test retrieval methods."""

    def test_get_company_by_id(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = CompanyRepository(db)
        company = repo.get_company_by_id(company_id)
        assert company is not None
        assert company["id"] == company_id
        assert company["name"] == "Test Corp"

    def test_get_company_by_id_nonexistent(self, db: Database) -> None:
        repo = CompanyRepository(db)
        assert repo.get_company_by_id(9999) is None

    def test_get_company_by_name_case_insensitive(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = CompanyRepository(db)

        result_lower = repo.get_company_by_name("test corp")
        assert result_lower is not None
        assert result_lower["id"] == company_id

        result_upper = repo.get_company_by_name("TEST CORP")
        assert result_upper is not None
        assert result_upper["id"] == company_id

        result_mixed = repo.get_company_by_name("Test Corp")
        assert result_mixed is not None
        assert result_mixed["id"] == company_id

    def test_get_company_by_name_nonexistent(self, db: Database) -> None:
        repo = CompanyRepository(db)
        assert repo.get_company_by_name("Ghost Corp") is None

    def test_get_company_by_name_and_url(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = CompanyRepository(db)
        result = repo.get_company_by_name_and_url("Test Corp", "https://testcorp.com")
        assert result is not None
        assert result["id"] == company_id

    def test_get_company_by_name_and_url_wrong_url(self, db_with_company: DbWithCompany) -> None:
        db, _ = db_with_company
        repo = CompanyRepository(db)
        result = repo.get_company_by_name_and_url("Test Corp", "https://wrong.com")
        assert result is None

    def test_get_company_by_name_and_url_null_url(self, db: Database) -> None:
        repo = CompanyRepository(db)
        repo.upsert_company("NullURL Corp", None, "Sheet1")
        result = repo.get_company_by_name_and_url("NullURL Corp", None)
        assert result is not None
        assert result["name"] == "NullURL Corp"


class TestCompanyRepositoryList:
    """Test listing methods."""

    def test_get_all_companies_ordered_by_name(self, db: Database) -> None:
        repo = CompanyRepository(db)
        repo.upsert_company("Zebra Corp", "https://z.com", "Sheet1")
        repo.upsert_company("Alpha Corp", "https://a.com", "Sheet1")
        repo.upsert_company("Middle Corp", "https://m.com", "Sheet1")

        companies = repo.get_all_companies()
        names = [c["name"] for c in companies]
        assert names == sorted(names)

    def test_get_all_companies_empty(self, db: Database) -> None:
        repo = CompanyRepository(db)
        assert repo.get_all_companies() == []

    def test_get_companies_with_homepage_excludes_null(self, db: Database) -> None:
        repo = CompanyRepository(db)
        repo.upsert_company("With URL", "https://has.com", "Sheet1")
        repo.upsert_company("No URL", None, "Sheet1")

        with_homepage = repo.get_companies_with_homepage()
        names = [c["name"] for c in with_homepage]
        assert "With URL" in names
        assert "No URL" not in names

    def test_get_company_count(self, db: Database) -> None:
        repo = CompanyRepository(db)
        assert repo.get_company_count() == 0
        repo.upsert_company("A", "https://a.com", "S")
        repo.upsert_company("B", "https://b.com", "S")
        assert repo.get_company_count() == 2


class TestCompanyRepositoryFlagAndError:
    """Test flagging and error recording."""

    def test_flag_company(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = CompanyRepository(db)
        repo.flag_company(company_id, "Suspicious activity")

        company = repo.get_company_by_id(company_id)
        assert company is not None
        assert company["flagged_for_review"] == 1
        assert company["flag_reason"] == "Suspicious activity"

    def test_store_processing_error(self, db: Database) -> None:
        repo = CompanyRepository(db)
        repo.store_processing_error(
            "company",
            42,
            "ConnectionError",
            "Timeout after 30s",
            retry_count=2,
        )

        row = db.fetchone("SELECT * FROM processing_errors WHERE entity_id = 42")
        assert row is not None
        assert row["entity_type"] == "company"
        assert row["error_type"] == "ConnectionError"
        assert row["error_message"] == "Timeout after 30s"
        assert row["retry_count"] == 2

    def test_store_processing_error_null_entity_id(self, db: Database) -> None:
        repo = CompanyRepository(db)
        repo.store_processing_error("batch", None, "BatchError", "General failure")

        row = db.fetchone("SELECT * FROM processing_errors WHERE entity_type = 'batch'")
        assert row is not None
        assert row["entity_id"] is None


# ===========================================================================
# Section 3: SnapshotRepository tests
# ===========================================================================


class TestSnapshotRepositoryStore:
    """Test snapshot storage and retrieval."""

    def _make_snapshot_data(self, company_id: int, **overrides: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "company_id": company_id,
            "url": "https://testcorp.com",
            "content_markdown": "# Test Corp\n\nWelcome.",
            "content_html": "<h1>Test Corp</h1><p>Welcome.</p>",
            "status_code": 200,
            "captured_at": _now_iso(),
            "has_paywall": False,
            "has_auth_required": False,
            "error_message": None,
            "content_checksum": "d41d8cd98f00b204e9800998ecf8427e",
            "http_last_modified": None,
            "capture_metadata": None,
        }
        data.update(overrides)
        return data

    def test_store_and_retrieve_by_id(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SnapshotRepository(db)
        data = self._make_snapshot_data(company_id)
        snapshot_id = repo.store_snapshot(data)
        assert snapshot_id > 0

        snapshot = repo.get_snapshot_by_id(snapshot_id)
        assert snapshot is not None
        assert snapshot["id"] == snapshot_id
        assert snapshot["company_id"] == company_id
        assert snapshot["content_markdown"] == "# Test Corp\n\nWelcome."
        assert snapshot["content_html"] == "<h1>Test Corp</h1><p>Welcome.</p>"
        assert snapshot["status_code"] == 200
        assert snapshot["content_checksum"] == "d41d8cd98f00b204e9800998ecf8427e"

    def test_store_with_paywall_and_auth(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SnapshotRepository(db)
        data = self._make_snapshot_data(company_id, has_paywall=True, has_auth_required=True)
        snapshot_id = repo.store_snapshot(data)

        snapshot = repo.get_snapshot_by_id(snapshot_id)
        assert snapshot is not None
        assert snapshot["has_paywall"] == 1
        assert snapshot["has_auth_required"] == 1

    def test_store_with_error_message(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SnapshotRepository(db)
        data = self._make_snapshot_data(
            company_id,
            status_code=500,
            error_message="Internal Server Error",
            content_markdown=None,
            content_html=None,
        )
        snapshot_id = repo.store_snapshot(data)

        snapshot = repo.get_snapshot_by_id(snapshot_id)
        assert snapshot is not None
        assert snapshot["error_message"] == "Internal Server Error"
        assert snapshot["status_code"] == 500

    def test_get_snapshot_by_id_nonexistent(self, db: Database) -> None:
        repo = SnapshotRepository(db)
        assert repo.get_snapshot_by_id(9999) is None


class TestSnapshotRepositoryLatest:
    """Test ordering and limit behavior of get_latest_snapshots."""

    def test_latest_snapshots_ordered_desc(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SnapshotRepository(db)

        oldest_time = _past_iso(10)
        middle_time = _past_iso(5)
        newest_time = _now_iso()

        for captured in [oldest_time, middle_time, newest_time]:
            repo.store_snapshot(
                {
                    "company_id": company_id,
                    "url": "https://testcorp.com",
                    "captured_at": captured,
                    "content_checksum": "abc",
                }
            )

        latest = repo.get_latest_snapshots(company_id, limit=2)
        assert len(latest) == 2
        # Most recent first
        assert latest[0]["captured_at"] >= latest[1]["captured_at"]

    def test_latest_snapshots_respects_limit(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SnapshotRepository(db)

        for i in range(5):
            repo.store_snapshot(
                {
                    "company_id": company_id,
                    "url": "https://testcorp.com",
                    "captured_at": _past_iso(i),
                    "content_checksum": f"check{i}",
                }
            )

        latest = repo.get_latest_snapshots(company_id, limit=3)
        assert len(latest) == 3

    def test_get_snapshots_for_company_ordered_asc(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SnapshotRepository(db)

        times = [_past_iso(10), _past_iso(5), _now_iso()]
        for t in times:
            repo.store_snapshot(
                {
                    "company_id": company_id,
                    "url": "https://testcorp.com",
                    "captured_at": t,
                    "content_checksum": "abc",
                }
            )

        all_snaps = repo.get_snapshots_for_company(company_id)
        assert len(all_snaps) == 3
        # Ordered by captured_at ASC
        for i in range(len(all_snaps) - 1):
            assert all_snaps[i]["captured_at"] <= all_snaps[i + 1]["captured_at"]


class TestSnapshotRepositoryMultiple:
    """Test multi-snapshot detection and oldest date."""

    def test_companies_with_multiple_snapshots(self, db: Database) -> None:
        repo = SnapshotRepository(db)
        cid_a = _insert_company(db, "A", "https://a.com")
        cid_b = _insert_company(db, "B", "https://b.com")
        cid_c = _insert_company(db, "C", "https://c.com")

        # A gets 2 snapshots, B gets 1, C gets 3
        _insert_snapshot(db, cid_a, _past_iso(5))
        _insert_snapshot(db, cid_a, _now_iso())
        _insert_snapshot(db, cid_b, _now_iso())
        _insert_snapshot(db, cid_c, _past_iso(10))
        _insert_snapshot(db, cid_c, _past_iso(5))
        _insert_snapshot(db, cid_c, _now_iso())

        result = repo.get_companies_with_multiple_snapshots()
        assert cid_a in result
        assert cid_b not in result
        assert cid_c in result

    def test_get_oldest_snapshot_date(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SnapshotRepository(db)

        oldest = _past_iso(30)
        _insert_snapshot(db, company_id, oldest)
        _insert_snapshot(db, company_id, _past_iso(5))
        _insert_snapshot(db, company_id, _now_iso())

        result = repo.get_oldest_snapshot_date(company_id)
        assert result == oldest

    def test_get_oldest_snapshot_date_no_snapshots(self, db: Database) -> None:
        repo = SnapshotRepository(db)
        cid = _insert_company(db)
        result = repo.get_oldest_snapshot_date(cid)
        assert result is None


class TestSnapshotRepositoryBaseline:
    """Test baseline signal CRUD methods."""

    def test_count_snapshots_for_company(self, db: Database) -> None:
        repo = SnapshotRepository(db)
        cid = _insert_company(db, "Count Co", "https://count.com")
        assert repo.count_snapshots_for_company(cid) == 0

        _insert_snapshot(db, cid, _now_iso())
        assert repo.count_snapshots_for_company(cid) == 1

        _insert_snapshot(db, cid, _past_iso(5))
        assert repo.count_snapshots_for_company(cid) == 2

    def test_update_baseline(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SnapshotRepository(db)
        snap_id = _insert_snapshot(db, company_id, _now_iso())

        repo.update_baseline(
            snap_id,
            {
                "baseline_classification": "significant",
                "baseline_sentiment": "negative",
                "baseline_confidence": 0.85,
                "baseline_keywords": ["shut down", "ceased operations"],
                "baseline_categories": ["closure"],
                "baseline_notes": "Pre-existing closure signals",
            },
        )

        row = db.fetchone("SELECT * FROM snapshots WHERE id = ?", (snap_id,))
        assert row is not None
        assert row["baseline_classification"] == "significant"
        assert row["baseline_sentiment"] == "negative"
        assert row["baseline_confidence"] == 0.85

    def test_has_baseline_for_company(self, db: Database) -> None:
        repo = SnapshotRepository(db)
        cid = _insert_company(db, "Baseline Co", "https://baseline.com")
        snap_id = _insert_snapshot(db, cid, _now_iso())

        assert repo.has_baseline_for_company(cid) is False

        repo.update_baseline(
            snap_id,
            {
                "baseline_classification": "insignificant",
                "baseline_sentiment": "neutral",
                "baseline_confidence": 0.75,
                "baseline_keywords": [],
                "baseline_categories": [],
                "baseline_notes": None,
            },
        )

        assert repo.has_baseline_for_company(cid) is True

    def test_get_snapshots_without_baseline(self, db: Database) -> None:
        repo = SnapshotRepository(db)
        cid1 = _insert_company(db, "No Baseline", "https://nobaseline.com")
        cid2 = _insert_company(db, "Has Baseline", "https://hasbaseline.com")

        _insert_snapshot(db, cid1, _now_iso(), content="Some content")
        snap2 = _insert_snapshot(db, cid2, _now_iso(), content="Other content")

        # Give cid2 a baseline
        repo.update_baseline(
            snap2,
            {
                "baseline_classification": "insignificant",
                "baseline_sentiment": "neutral",
                "baseline_confidence": 0.75,
                "baseline_keywords": [],
                "baseline_categories": [],
                "baseline_notes": None,
            },
        )

        results = repo.get_snapshots_without_baseline()
        company_ids = [r["company_id"] for r in results]
        assert cid1 in company_ids
        assert cid2 not in company_ids

    def test_get_snapshots_without_baseline_for_company(self, db: Database) -> None:
        repo = SnapshotRepository(db)
        cid = _insert_company(db, "Filter Co", "https://filter.com")
        _insert_snapshot(db, cid, _past_iso(5), content="Old content")
        _insert_snapshot(db, cid, _now_iso(), content="New content")

        results = repo.get_snapshots_without_baseline(company_id=cid)
        # Should return only 1 (the earliest)
        assert len(results) == 1


# ===========================================================================
# Section 4: ChangeRecordRepository tests
# ===========================================================================


class TestChangeRecordRepositoryStore:
    """Test change record storage."""

    def _setup_snapshots(self, db: Database, company_id: int) -> tuple[int, int]:
        """Create two snapshots and return (old_id, new_id)."""
        old_id = _insert_snapshot(db, company_id, _past_iso(10))
        new_id = _insert_snapshot(db, company_id, _now_iso())
        return old_id, new_id

    def test_store_basic_change_record(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = ChangeRecordRepository(db)
        snap_old, snap_new = self._setup_snapshots(db, company_id)

        record_id = repo.store_change_record(
            {
                "company_id": company_id,
                "snapshot_id_old": snap_old,
                "snapshot_id_new": snap_new,
                "checksum_old": "aaa111",
                "checksum_new": "bbb222",
                "has_changed": True,
                "change_magnitude": "MODERATE",
                "detected_at": _now_iso(),
            }
        )
        assert record_id > 0

        changes = repo.get_changes_for_company(company_id)
        assert len(changes) == 1
        assert changes[0]["id"] == record_id
        assert changes[0]["has_changed"] == 1
        assert changes[0]["change_magnitude"] == "MODERATE"

    def test_store_with_significance_data(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = ChangeRecordRepository(db)
        snap_old, snap_new = self._setup_snapshots(db, company_id)

        keywords = ["funding", "series_b"]
        categories = ["positive_funding"]
        snippets = ["Company raised $50M in Series B"]

        repo.store_change_record(
            {
                "company_id": company_id,
                "snapshot_id_old": snap_old,
                "snapshot_id_new": snap_new,
                "checksum_old": "ccc",
                "checksum_new": "ddd",
                "has_changed": True,
                "change_magnitude": "MAJOR",
                "detected_at": _now_iso(),
                "significance_classification": "significant",
                "significance_sentiment": "positive",
                "significance_confidence": 0.92,
                "matched_keywords": keywords,
                "matched_categories": categories,
                "significance_notes": "Funding round detected",
                "evidence_snippets": snippets,
            }
        )

        changes = repo.get_changes_for_company(company_id)
        record = changes[0]
        assert record["significance_classification"] == "significant"
        assert record["significance_sentiment"] == "positive"
        assert record["significance_confidence"] == pytest.approx(0.92)
        assert record["matched_keywords"] == keywords
        assert record["matched_categories"] == categories
        assert record["evidence_snippets"] == snippets
        assert record["significance_notes"] == "Funding round detected"

    def test_store_without_significance_has_empty_lists(
        self, db_with_company: DbWithCompany
    ) -> None:
        db, company_id = db_with_company
        repo = ChangeRecordRepository(db)
        snap_old, snap_new = self._setup_snapshots(db, company_id)

        repo.store_change_record(
            {
                "company_id": company_id,
                "snapshot_id_old": snap_old,
                "snapshot_id_new": snap_new,
                "checksum_old": "eee",
                "checksum_new": "fff",
                "has_changed": True,
                "change_magnitude": "MINOR",
                "detected_at": _now_iso(),
            }
        )

        changes = repo.get_changes_for_company(company_id)
        record = changes[0]
        assert record["significance_classification"] is None
        assert record["matched_keywords"] == []
        assert record["matched_categories"] == []
        assert record["evidence_snippets"] == []


class TestChangeRecordRepositoryUpdate:
    """Test update_significance and backfill retrieval."""

    def _store_record_without_significance(self, db: Database, company_id: int) -> int:
        snap_old = _insert_snapshot(db, company_id, _past_iso(10))
        snap_new = _insert_snapshot(db, company_id, _now_iso())
        repo = ChangeRecordRepository(db)
        return repo.store_change_record(
            {
                "company_id": company_id,
                "snapshot_id_old": snap_old,
                "snapshot_id_new": snap_new,
                "checksum_old": "old",
                "checksum_new": "new",
                "has_changed": True,
                "change_magnitude": "MODERATE",
                "detected_at": _now_iso(),
            }
        )

    def test_get_records_without_significance(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = ChangeRecordRepository(db)

        # Record without significance (has_changed=True)
        self._store_record_without_significance(db, company_id)

        # Record with significance already set
        snap_old2 = _insert_snapshot(db, company_id, _past_iso(20))
        snap_new2 = _insert_snapshot(db, company_id, _past_iso(15))
        repo.store_change_record(
            {
                "company_id": company_id,
                "snapshot_id_old": snap_old2,
                "snapshot_id_new": snap_new2,
                "checksum_old": "xx",
                "checksum_new": "yy",
                "has_changed": True,
                "change_magnitude": "MINOR",
                "detected_at": _past_iso(15),
                "significance_classification": "insignificant",
            }
        )

        # Record with has_changed=False (should be excluded)
        snap_old3 = _insert_snapshot(db, company_id, _past_iso(25))
        snap_new3 = _insert_snapshot(db, company_id, _past_iso(22))
        repo.store_change_record(
            {
                "company_id": company_id,
                "snapshot_id_old": snap_old3,
                "snapshot_id_new": snap_new3,
                "checksum_old": "same",
                "checksum_new": "same",
                "has_changed": False,
                "change_magnitude": "MINOR",
                "detected_at": _past_iso(22),
            }
        )

        unanalyzed = repo.get_records_without_significance()
        assert len(unanalyzed) == 1
        assert unanalyzed[0]["significance_classification"] is None
        assert unanalyzed[0]["has_changed"] == 1

    def test_update_significance(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = ChangeRecordRepository(db)
        record_id = self._store_record_without_significance(db, company_id)

        keywords = ["layoffs", "restructuring"]
        categories = ["negative_layoffs"]
        snippets = ["The company laid off 30% of workforce"]

        repo.update_significance(
            record_id,
            {
                "significance_classification": "significant",
                "significance_sentiment": "negative",
                "significance_confidence": 0.88,
                "matched_keywords": keywords,
                "matched_categories": categories,
                "significance_notes": "Layoff detected",
                "evidence_snippets": snippets,
            },
        )

        changes = repo.get_changes_for_company(company_id)
        updated = next(c for c in changes if c["id"] == record_id)
        assert updated["significance_classification"] == "significant"
        assert updated["significance_sentiment"] == "negative"
        assert updated["significance_confidence"] == pytest.approx(0.88)
        assert updated["matched_keywords"] == keywords
        assert updated["matched_categories"] == categories
        assert updated["evidence_snippets"] == snippets

    def test_json_roundtrip_empty_lists(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = ChangeRecordRepository(db)
        record_id = self._store_record_without_significance(db, company_id)

        repo.update_significance(
            record_id,
            {
                "significance_classification": "insignificant",
                "significance_sentiment": "neutral",
                "significance_confidence": 0.75,
                "matched_keywords": [],
                "matched_categories": [],
                "evidence_snippets": [],
            },
        )

        changes = repo.get_changes_for_company(company_id)
        updated = next(c for c in changes if c["id"] == record_id)
        assert updated["matched_keywords"] == []
        assert updated["matched_categories"] == []
        assert updated["evidence_snippets"] == []


class TestChangeRecordRepositoryFilters:
    """Test get_significant_changes and get_uncertain_changes with joins."""

    def _insert_change_with_significance(
        self,
        db: Database,
        company_id: int,
        classification: str,
        sentiment: str,
        confidence: float,
        detected_at: str | None = None,
    ) -> int:
        snap_old = _insert_snapshot(db, company_id, _past_iso(30))
        snap_new = _insert_snapshot(db, company_id, detected_at or _now_iso())
        repo = ChangeRecordRepository(db)
        return repo.store_change_record(
            {
                "company_id": company_id,
                "snapshot_id_old": snap_old,
                "snapshot_id_new": snap_new,
                "checksum_old": "a",
                "checksum_new": "b",
                "has_changed": True,
                "change_magnitude": "MODERATE",
                "detected_at": detected_at or _now_iso(),
                "significance_classification": classification,
                "significance_sentiment": sentiment,
                "significance_confidence": confidence,
                "matched_keywords": ["test"],
                "matched_categories": ["test_cat"],
                "evidence_snippets": ["some evidence"],
            }
        )

    def test_get_significant_changes(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = ChangeRecordRepository(db)

        self._insert_change_with_significance(db, company_id, "significant", "positive", 0.85)
        self._insert_change_with_significance(db, company_id, "insignificant", "neutral", 0.75)
        self._insert_change_with_significance(db, company_id, "uncertain", "negative", 0.55)

        significant = repo.get_significant_changes(days=365)
        assert len(significant) == 1
        assert significant[0]["significance_classification"] == "significant"
        assert significant[0]["company_name"] == "Test Corp"

    def test_get_significant_changes_filter_by_sentiment(
        self, db_with_company: DbWithCompany
    ) -> None:
        db, company_id = db_with_company
        repo = ChangeRecordRepository(db)

        self._insert_change_with_significance(db, company_id, "significant", "positive", 0.85)
        self._insert_change_with_significance(db, company_id, "significant", "negative", 0.90)

        positive = repo.get_significant_changes(days=365, sentiment="positive")
        assert len(positive) == 1
        assert positive[0]["significance_sentiment"] == "positive"

        negative = repo.get_significant_changes(days=365, sentiment="negative")
        assert len(negative) == 1
        assert negative[0]["significance_sentiment"] == "negative"

    def test_get_significant_changes_min_confidence(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = ChangeRecordRepository(db)

        self._insert_change_with_significance(db, company_id, "significant", "positive", 0.45)
        self._insert_change_with_significance(db, company_id, "significant", "positive", 0.85)

        results = repo.get_significant_changes(days=365, min_confidence=0.7)
        assert len(results) == 1
        assert results[0]["significance_confidence"] >= 0.7

    def test_get_uncertain_changes(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = ChangeRecordRepository(db)

        self._insert_change_with_significance(db, company_id, "uncertain", "neutral", 0.50)
        self._insert_change_with_significance(db, company_id, "significant", "positive", 0.90)
        self._insert_change_with_significance(db, company_id, "uncertain", "negative", 0.55)

        uncertain = repo.get_uncertain_changes()
        assert len(uncertain) == 2
        assert all(c["significance_classification"] == "uncertain" for c in uncertain)
        assert all("company_name" in c for c in uncertain)

    def test_get_uncertain_changes_respects_limit(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = ChangeRecordRepository(db)

        for _ in range(5):
            self._insert_change_with_significance(db, company_id, "uncertain", "neutral", 0.50)

        uncertain = repo.get_uncertain_changes(limit=3)
        assert len(uncertain) == 3

    def test_get_changes_for_company_ordered_desc(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = ChangeRecordRepository(db)

        for days_ago in [20, 10, 5]:
            self._insert_change_with_significance(
                db,
                company_id,
                "significant",
                "positive",
                0.80,
                detected_at=_past_iso(days_ago),
            )

        changes = repo.get_changes_for_company(company_id)
        for i in range(len(changes) - 1):
            assert changes[i]["detected_at"] >= changes[i + 1]["detected_at"]


# ===========================================================================
# Section 5: CompanyStatusRepository tests
# ===========================================================================


class TestCompanyStatusRepositoryStore:
    """Test status storage and retrieval."""

    def test_store_and_get_latest_status(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = CompanyStatusRepository(db)

        indicators = ["website_active", "content_updated_recently", "ssl_valid"]
        status_id = repo.store_status(
            {
                "company_id": company_id,
                "status": "operational",
                "confidence": 0.95,
                "indicators": indicators,
                "last_checked": _now_iso(),
                "http_last_modified": "Wed, 15 Jan 2026 10:00:00 GMT",
            }
        )
        assert status_id > 0

        latest = repo.get_latest_status(company_id)
        assert latest is not None
        assert latest["status"] == "operational"
        assert latest["confidence"] == pytest.approx(0.95)
        assert latest["indicators"] == indicators
        assert latest["http_last_modified"] == "Wed, 15 Jan 2026 10:00:00 GMT"

    def test_get_latest_status_returns_most_recent(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = CompanyStatusRepository(db)

        repo.store_status(
            {
                "company_id": company_id,
                "status": "operational",
                "confidence": 0.90,
                "indicators": ["old_check"],
                "last_checked": _past_iso(10),
            }
        )
        repo.store_status(
            {
                "company_id": company_id,
                "status": "likely_closed",
                "confidence": 0.80,
                "indicators": ["website_down", "no_content"],
                "last_checked": _now_iso(),
            }
        )

        latest = repo.get_latest_status(company_id)
        assert latest is not None
        assert latest["status"] == "likely_closed"
        assert latest["indicators"] == ["website_down", "no_content"]

    def test_get_latest_status_nonexistent(self, db: Database) -> None:
        repo = CompanyStatusRepository(db)
        cid = _insert_company(db)
        assert repo.get_latest_status(cid) is None


class TestCompanyStatusRepositoryByName:
    """Test status retrieval by company name."""

    def test_get_status_by_company_name(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = CompanyStatusRepository(db)

        repo.store_status(
            {
                "company_id": company_id,
                "status": "uncertain",
                "confidence": 0.60,
                "indicators": ["mixed_signals"],
                "last_checked": _now_iso(),
            }
        )

        result = repo.get_status_by_company_name("Test Corp")
        assert result is not None
        assert result["status"] == "uncertain"

    def test_get_status_by_company_name_case_insensitive(
        self, db_with_company: DbWithCompany
    ) -> None:
        db, company_id = db_with_company
        repo = CompanyStatusRepository(db)

        repo.store_status(
            {
                "company_id": company_id,
                "status": "operational",
                "confidence": 0.90,
                "indicators": [],
                "last_checked": _now_iso(),
            }
        )

        result = repo.get_status_by_company_name("test corp")
        assert result is not None
        assert result["status"] == "operational"

    def test_get_status_by_company_name_nonexistent(self, db: Database) -> None:
        repo = CompanyStatusRepository(db)
        assert repo.get_status_by_company_name("Ghost Corp") is None


class TestCompanyStatusJsonRoundtrip:
    """Test JSON serialization of indicators field."""

    def test_empty_indicators_list(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = CompanyStatusRepository(db)

        repo.store_status(
            {
                "company_id": company_id,
                "status": "operational",
                "confidence": 0.5,
                "indicators": [],
                "last_checked": _now_iso(),
            }
        )

        latest = repo.get_latest_status(company_id)
        assert latest is not None
        assert latest["indicators"] == []

    def test_complex_indicators(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = CompanyStatusRepository(db)

        indicators = [
            "ssl_expired",
            "domain_for_sale",
            "no_content_updates_365_days",
            "parking_page_detected",
        ]
        repo.store_status(
            {
                "company_id": company_id,
                "status": "likely_closed",
                "confidence": 0.85,
                "indicators": indicators,
                "last_checked": _now_iso(),
            }
        )

        latest = repo.get_latest_status(company_id)
        assert latest is not None
        assert latest["indicators"] == indicators


# ===========================================================================
# Section 6: SocialMediaLinkRepository tests
# ===========================================================================


class TestSocialMediaLinkStore:
    """Test social media link storage."""

    def _make_link_data(self, company_id: int, **overrides: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "company_id": company_id,
            "platform": "linkedin",
            "profile_url": "https://linkedin.com/company/testcorp",
            "discovery_method": "html_anchor",
            "verification_status": "unverified",
            "similarity_score": None,
            "discovered_at": _now_iso(),
            "last_verified_at": None,
            "html_location": "footer",
            "account_type": "company",
            "account_confidence": 0.80,
            "rejection_reason": None,
        }
        data.update(overrides)
        return data

    def test_store_and_retrieve_link(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SocialMediaLinkRepository(db)
        data = self._make_link_data(company_id)
        link_id = repo.store_social_link(data)
        assert link_id > 0

        links = repo.get_links_for_company(company_id)
        assert len(links) == 1
        assert links[0]["platform"] == "linkedin"
        assert links[0]["profile_url"] == "https://linkedin.com/company/testcorp"
        assert links[0]["html_location"] == "footer"
        assert links[0]["account_type"] == "company"

    def test_unique_constraint_returns_zero_not_exception(
        self, db_with_company: DbWithCompany
    ) -> None:
        db, company_id = db_with_company
        repo = SocialMediaLinkRepository(db)
        data = self._make_link_data(company_id)

        first_id = repo.store_social_link(data)
        assert first_id > 0

        # Duplicate insert should return 0, not raise
        duplicate_id = repo.store_social_link(data)
        assert duplicate_id == 0

    def test_same_url_different_company_allowed(self, db: Database) -> None:
        repo = SocialMediaLinkRepository(db)
        cid_a = _insert_company(db, "A", "https://a.com")
        cid_b = _insert_company(db, "B", "https://b.com")

        url = "https://linkedin.com/company/shared"
        id_a = repo.store_social_link(self._make_link_data(cid_a, profile_url=url))
        id_b = repo.store_social_link(self._make_link_data(cid_b, profile_url=url))

        assert id_a > 0
        assert id_b > 0
        assert id_a != id_b


class TestSocialMediaLinkRetrieval:
    """Test link retrieval methods."""

    def test_get_links_for_company_ordered_by_platform(
        self, db_with_company: DbWithCompany
    ) -> None:
        db, company_id = db_with_company
        repo = SocialMediaLinkRepository(db)

        platforms = ["twitter", "github", "linkedin", "youtube"]
        for platform in platforms:
            repo.store_social_link(
                {
                    "company_id": company_id,
                    "platform": platform,
                    "profile_url": f"https://{platform}.com/testcorp",
                    "discovery_method": "html_anchor",
                    "verification_status": "unverified",
                    "discovered_at": _now_iso(),
                }
            )

        links = repo.get_links_for_company(company_id)
        assert len(links) == 4
        link_platforms = [link["platform"] for link in links]
        assert link_platforms == sorted(link_platforms)

    def test_get_links_by_platform(self, db: Database) -> None:
        repo = SocialMediaLinkRepository(db)
        cid_a = _insert_company(db, "A", "https://a.com")
        cid_b = _insert_company(db, "B", "https://b.com")

        now = _now_iso()
        repo.store_social_link(
            {
                "company_id": cid_a,
                "platform": "twitter",
                "profile_url": "https://twitter.com/a",
                "discovery_method": "html_anchor",
                "verification_status": "unverified",
                "discovered_at": now,
            }
        )
        repo.store_social_link(
            {
                "company_id": cid_b,
                "platform": "twitter",
                "profile_url": "https://twitter.com/b",
                "discovery_method": "html_anchor",
                "verification_status": "unverified",
                "discovered_at": now,
            }
        )
        repo.store_social_link(
            {
                "company_id": cid_a,
                "platform": "linkedin",
                "profile_url": "https://linkedin.com/company/a",
                "discovery_method": "html_anchor",
                "verification_status": "unverified",
                "discovered_at": now,
            }
        )

        twitter_links = repo.get_links_by_platform("twitter")
        assert len(twitter_links) == 2

        linkedin_links = repo.get_links_by_platform("linkedin")
        assert len(linkedin_links) == 1

    def test_link_exists(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SocialMediaLinkRepository(db)
        url = "https://twitter.com/testcorp"

        assert repo.link_exists(company_id, url) is False

        repo.store_social_link(
            {
                "company_id": company_id,
                "platform": "twitter",
                "profile_url": url,
                "discovery_method": "html_anchor",
                "verification_status": "unverified",
                "discovered_at": _now_iso(),
            }
        )

        assert repo.link_exists(company_id, url) is True

    def test_link_exists_different_company(self, db: Database) -> None:
        repo = SocialMediaLinkRepository(db)
        cid_a = _insert_company(db, "A", "https://a.com")
        cid_b = _insert_company(db, "B", "https://b.com")

        url = "https://twitter.com/shared"
        repo.store_social_link(
            {
                "company_id": cid_a,
                "platform": "twitter",
                "profile_url": url,
                "discovery_method": "html_anchor",
                "verification_status": "unverified",
                "discovered_at": _now_iso(),
            }
        )

        assert repo.link_exists(cid_a, url) is True
        assert repo.link_exists(cid_b, url) is False


class TestSocialMediaLinkBlogAndLogo:
    """Test blog link and company logo storage."""

    def test_store_blog_link(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SocialMediaLinkRepository(db)

        blog_id = repo.store_blog_link(
            {
                "company_id": company_id,
                "blog_type": "company",
                "blog_url": "https://blog.testcorp.com",
                "discovery_method": "html_anchor",
                "is_active": True,
                "discovered_at": _now_iso(),
                "last_checked_at": None,
            }
        )
        assert blog_id > 0

        row = db.fetchone("SELECT * FROM blog_links WHERE id = ?", (blog_id,))
        assert row is not None
        assert row["blog_url"] == "https://blog.testcorp.com"
        assert row["is_active"] == 1

    def test_store_blog_link_duplicate_returns_zero(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SocialMediaLinkRepository(db)
        data = {
            "company_id": company_id,
            "blog_type": "company",
            "blog_url": "https://blog.testcorp.com",
            "discovery_method": "html_anchor",
            "is_active": True,
            "discovered_at": _now_iso(),
        }
        first_id = repo.store_blog_link(data)
        assert first_id > 0

        duplicate_id = repo.store_blog_link(data)
        assert duplicate_id == 0

    def test_store_and_get_company_logo(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SocialMediaLinkRepository(db)

        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        logo_id = repo.store_company_logo(
            {
                "company_id": company_id,
                "image_data": image_bytes,
                "image_format": "png",
                "perceptual_hash": "abcdef1234567890",
                "source_url": "https://testcorp.com/logo.png",
                "extraction_location": "header",
                "width": 200,
                "height": 50,
                "extracted_at": _now_iso(),
            }
        )
        assert logo_id > 0

        logo = repo.get_company_logo(company_id)
        assert logo is not None
        assert logo["image_data"] == image_bytes
        assert logo["image_format"] == "png"
        assert logo["perceptual_hash"] == "abcdef1234567890"
        assert logo["width"] == 200
        assert logo["height"] == 50

    def test_get_company_logo_returns_latest(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SocialMediaLinkRepository(db)

        repo.store_company_logo(
            {
                "company_id": company_id,
                "image_data": b"old_logo",
                "image_format": "png",
                "perceptual_hash": "hash_old",
                "source_url": "https://testcorp.com/old_logo.png",
                "extraction_location": "header",
                "extracted_at": _past_iso(10),
            }
        )
        repo.store_company_logo(
            {
                "company_id": company_id,
                "image_data": b"new_logo",
                "image_format": "png",
                "perceptual_hash": "hash_new",
                "source_url": "https://testcorp.com/new_logo.png",
                "extraction_location": "header",
                "extracted_at": _now_iso(),
            }
        )

        logo = repo.get_company_logo(company_id)
        assert logo is not None
        assert logo["image_data"] == b"new_logo"
        assert logo["perceptual_hash"] == "hash_new"

    def test_store_logo_duplicate_hash_returns_zero(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SocialMediaLinkRepository(db)
        data = {
            "company_id": company_id,
            "image_data": b"logo_data",
            "image_format": "png",
            "perceptual_hash": "same_hash",
            "source_url": "https://testcorp.com/logo.png",
            "extraction_location": "header",
            "extracted_at": _now_iso(),
        }
        first_id = repo.store_company_logo(data)
        assert first_id > 0

        duplicate_id = repo.store_company_logo(data)
        assert duplicate_id == 0

    def test_get_company_logo_nonexistent(self, db: Database) -> None:
        repo = SocialMediaLinkRepository(db)
        cid = _insert_company(db)
        assert repo.get_company_logo(cid) is None


# ===========================================================================
# Section 7: NewsArticleRepository tests
# ===========================================================================


class TestNewsArticleStore:
    """Test news article storage and retrieval."""

    def _make_article_data(self, company_id: int, **overrides: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "company_id": company_id,
            "title": "Test Corp Raises $10M in Funding",
            "content_url": "https://techcrunch.com/test-corp-funding",
            "source": "kagi",
            "published_at": _now_iso(),
            "discovered_at": _now_iso(),
            "match_confidence": 0.85,
            "match_evidence": ["domain_match", "name_in_title"],
            "logo_similarity": 0.92,
            "company_match_snippet": "Test Corp announced today",
            "keyword_match_snippet": "raised $10M in Series A",
            "significance_classification": "significant",
            "significance_sentiment": "positive",
            "significance_confidence": 0.90,
            "matched_keywords": ["funding", "series_a"],
            "matched_categories": ["positive_funding"],
            "significance_notes": "Funding round detected",
        }
        data.update(overrides)
        return data

    def test_store_and_retrieve(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = NewsArticleRepository(db)
        data = self._make_article_data(company_id)

        article_id = repo.store_news_article(data)
        assert article_id > 0

        articles = repo.get_news_articles(company_id)
        assert len(articles) == 1
        article = articles[0]
        assert article["title"] == "Test Corp Raises $10M in Funding"
        assert article["source"] == "kagi"
        assert article["match_confidence"] == pytest.approx(0.85)
        assert article["logo_similarity"] == pytest.approx(0.92)
        assert article["significance_classification"] == "significant"
        assert article["significance_sentiment"] == "positive"

    def test_json_roundtrip_for_list_fields(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = NewsArticleRepository(db)
        data = self._make_article_data(company_id)
        repo.store_news_article(data)

        articles = repo.get_news_articles(company_id)
        article = articles[0]
        assert article["match_evidence"] == ["domain_match", "name_in_title"]
        assert article["matched_keywords"] == ["funding", "series_a"]
        assert article["matched_categories"] == ["positive_funding"]

    def test_store_without_significance(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = NewsArticleRepository(db)
        data = self._make_article_data(
            company_id,
            content_url="https://example.com/no-sig",
            significance_classification=None,
            significance_sentiment=None,
            significance_confidence=None,
            matched_keywords=[],
            matched_categories=[],
            significance_notes=None,
        )
        article_id = repo.store_news_article(data)
        assert article_id > 0

        articles = repo.get_news_articles(company_id)
        article = next(a for a in articles if a["id"] == article_id)
        assert article["significance_classification"] is None
        assert article["matched_keywords"] == []
        assert article["matched_categories"] == []

    def test_unique_content_url_returns_zero(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = NewsArticleRepository(db)
        data = self._make_article_data(company_id)

        first_id = repo.store_news_article(data)
        assert first_id > 0

        duplicate_id = repo.store_news_article(data)
        assert duplicate_id == 0


class TestNewsArticleDuplicateCheck:
    """Test check_duplicate_news_url."""

    def test_duplicate_check_false_for_new_url(self, db: Database) -> None:
        repo = NewsArticleRepository(db)
        assert repo.check_duplicate_news_url("https://example.com/brand-new") is False

    def test_duplicate_check_true_for_existing_url(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = NewsArticleRepository(db)
        url = "https://example.com/already-stored"

        repo.store_news_article(
            {
                "company_id": company_id,
                "title": "Existing Article",
                "content_url": url,
                "source": "kagi",
                "published_at": _now_iso(),
                "discovered_at": _now_iso(),
                "match_confidence": 0.80,
            }
        )

        assert repo.check_duplicate_news_url(url) is True

    def test_duplicate_url_is_global_across_companies(self, db: Database) -> None:
        repo = NewsArticleRepository(db)
        cid_a = _insert_company(db, "A", "https://a.com")
        cid_b = _insert_company(db, "B", "https://b.com")

        url = "https://shared-article.com/story"
        repo.store_news_article(
            {
                "company_id": cid_a,
                "title": "Shared Story",
                "content_url": url,
                "source": "kagi",
                "published_at": _now_iso(),
                "discovered_at": _now_iso(),
                "match_confidence": 0.75,
            }
        )

        # Same URL for different company should fail (UNIQUE on content_url is global)
        assert repo.check_duplicate_news_url(url) is True
        duplicate_id = repo.store_news_article(
            {
                "company_id": cid_b,
                "title": "Shared Story for B",
                "content_url": url,
                "source": "kagi",
                "published_at": _now_iso(),
                "discovered_at": _now_iso(),
                "match_confidence": 0.70,
            }
        )
        assert duplicate_id == 0


class TestNewsArticleDateRange:
    """Test get_news_for_date_range."""

    def test_date_range_filter(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = NewsArticleRepository(db)

        dates = [_past_iso(30), _past_iso(15), _past_iso(5), _now_iso()]
        for i, pub_date in enumerate(dates):
            repo.store_news_article(
                {
                    "company_id": company_id,
                    "title": f"Article {i}",
                    "content_url": f"https://news.com/article-{i}",
                    "source": "kagi",
                    "published_at": pub_date,
                    "discovered_at": _now_iso(),
                    "match_confidence": 0.80,
                }
            )

        # Query range that should include articles from 20 days ago to 2 days ago
        start = _past_iso(20)
        end = _past_iso(2)
        results = repo.get_news_for_date_range(company_id, start, end)

        # Should include the 15-day and 5-day articles
        assert len(results) == 2
        # Ordered by published_at DESC
        assert results[0]["published_at"] >= results[1]["published_at"]


class TestNewsArticleSignificant:
    """Test get_significant_news."""

    def test_get_significant_news(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = NewsArticleRepository(db)

        repo.store_news_article(
            {
                "company_id": company_id,
                "title": "Significant News",
                "content_url": "https://news.com/sig",
                "source": "kagi",
                "published_at": _now_iso(),
                "discovered_at": _now_iso(),
                "match_confidence": 0.85,
                "significance_classification": "significant",
                "significance_sentiment": "positive",
                "significance_confidence": 0.90,
                "matched_keywords": ["funding"],
            }
        )
        repo.store_news_article(
            {
                "company_id": company_id,
                "title": "Insignificant News",
                "content_url": "https://news.com/insig",
                "source": "kagi",
                "published_at": _now_iso(),
                "discovered_at": _now_iso(),
                "match_confidence": 0.80,
                "significance_classification": "insignificant",
                "significance_sentiment": "neutral",
                "significance_confidence": 0.75,
            }
        )

        significant = repo.get_significant_news(days=365)
        assert len(significant) == 1
        assert significant[0]["title"] == "Significant News"
        assert significant[0]["company_name"] == "Test Corp"

    def test_get_significant_news_filter_by_sentiment(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = NewsArticleRepository(db)

        repo.store_news_article(
            {
                "company_id": company_id,
                "title": "Good News",
                "content_url": "https://news.com/good",
                "source": "kagi",
                "published_at": _now_iso(),
                "discovered_at": _now_iso(),
                "match_confidence": 0.85,
                "significance_classification": "significant",
                "significance_sentiment": "positive",
            }
        )
        repo.store_news_article(
            {
                "company_id": company_id,
                "title": "Bad News",
                "content_url": "https://news.com/bad",
                "source": "kagi",
                "published_at": _now_iso(),
                "discovered_at": _now_iso(),
                "match_confidence": 0.85,
                "significance_classification": "significant",
                "significance_sentiment": "negative",
            }
        )

        positive = repo.get_significant_news(days=365, sentiment="positive")
        assert len(positive) == 1
        assert positive[0]["significance_sentiment"] == "positive"

        negative = repo.get_significant_news(days=365, sentiment="negative")
        assert len(negative) == 1
        assert negative[0]["significance_sentiment"] == "negative"

    def test_get_news_articles_respects_limit(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = NewsArticleRepository(db)

        for i in range(10):
            repo.store_news_article(
                {
                    "company_id": company_id,
                    "title": f"Article {i}",
                    "content_url": f"https://news.com/{i}",
                    "source": "kagi",
                    "published_at": _past_iso(i),
                    "discovered_at": _now_iso(),
                    "match_confidence": 0.80,
                }
            )

        articles = repo.get_news_articles(company_id, limit=5)
        assert len(articles) == 5

    def test_get_news_articles_ordered_desc(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = NewsArticleRepository(db)

        for i in range(5):
            repo.store_news_article(
                {
                    "company_id": company_id,
                    "title": f"Article {i}",
                    "content_url": f"https://news.com/ordered-{i}",
                    "source": "kagi",
                    "published_at": _past_iso(i * 5),
                    "discovered_at": _now_iso(),
                    "match_confidence": 0.80,
                }
            )

        articles = repo.get_news_articles(company_id)
        for i in range(len(articles) - 1):
            assert articles[i]["published_at"] >= articles[i + 1]["published_at"]


# ===========================================================================
# Section 8: Cross-cutting concerns
# ===========================================================================


class TestForeignKeyEnforcement:
    """Verify foreign keys reject orphan inserts (not just cascade deletes)."""

    def test_snapshot_requires_valid_company_id(self, db: Database) -> None:
        repo = SnapshotRepository(db)
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            repo.store_snapshot(
                {
                    "company_id": 99999,
                    "url": "https://orphan.com",
                    "captured_at": _now_iso(),
                    "content_checksum": "abc",
                }
            )

    def test_social_link_requires_valid_company_id(self, db: Database) -> None:
        repo = SocialMediaLinkRepository(db)
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            repo.store_social_link(
                {
                    "company_id": 99999,
                    "platform": "twitter",
                    "profile_url": "https://twitter.com/orphan",
                    "discovery_method": "html",
                    "verification_status": "unverified",
                    "discovered_at": _now_iso(),
                }
            )

    def test_news_article_requires_valid_company_id(self, db: Database) -> None:
        repo = NewsArticleRepository(db)
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            repo.store_news_article(
                {
                    "company_id": 99999,
                    "title": "Orphan Article",
                    "content_url": "https://news.com/orphan",
                    "source": "kagi",
                    "published_at": _now_iso(),
                    "discovered_at": _now_iso(),
                    "match_confidence": 0.5,
                }
            )

    def test_change_record_requires_valid_company_id(self, db: Database) -> None:
        repo = ChangeRecordRepository(db)
        # Need valid snapshot IDs from a real company, but use bogus company_id
        cid = _insert_company(db)
        snap_a = _insert_snapshot(db, cid, _past_iso(5))
        snap_b = _insert_snapshot(db, cid, _now_iso())

        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            repo.store_change_record(
                {
                    "company_id": 99999,
                    "snapshot_id_old": snap_a,
                    "snapshot_id_new": snap_b,
                    "checksum_old": "a",
                    "checksum_new": "b",
                    "has_changed": True,
                    "change_magnitude": "MINOR",
                    "detected_at": _now_iso(),
                }
            )

    def test_company_status_requires_valid_company_id(self, db: Database) -> None:
        repo = CompanyStatusRepository(db)
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            repo.store_status(
                {
                    "company_id": 99999,
                    "status": "operational",
                    "confidence": 0.90,
                    "indicators": [],
                    "last_checked": _now_iso(),
                }
            )
