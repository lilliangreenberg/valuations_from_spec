"""SQLite database service."""

from __future__ import annotations

import contextlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Generator

logger = structlog.get_logger(__name__)


class Database:
    """SQLite database service with schema management."""

    def __init__(self, db_path: str = "data/companies.db") -> None:
        self.db_path = db_path
        self._ensure_directory()
        self._connection: sqlite3.Connection | None = None

    def _ensure_directory(self) -> None:
        """Ensure the parent directory of the database file exists."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    @property
    def connection(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
        return self._connection

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """Context manager for database transactions."""
        conn = self.connection
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def execute(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> sqlite3.Cursor:
        """Execute a single SQL statement."""
        return self.connection.execute(sql, params)

    def executemany(
        self,
        sql: str,
        params_list: list[tuple[Any, ...] | dict[str, Any]],
    ) -> sqlite3.Cursor:
        """Execute SQL statement for each set of params."""
        return self.connection.executemany(sql, params_list)

    def fetchone(
        self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()
    ) -> sqlite3.Row | None:
        """Execute and fetch one row."""
        cursor = self.execute(sql, params)
        return cursor.fetchone()

    def fetchall(
        self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()
    ) -> list[sqlite3.Row]:
        """Execute and fetch all rows."""
        cursor = self.execute(sql, params)
        return cursor.fetchall()

    def close(self) -> None:
        """Close the database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def init_db(self) -> None:
        """Initialize database schema. Creates all tables and indexes."""
        logger.info("initializing_database", path=self.db_path)

        with self.transaction() as cursor:
            # companies table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS companies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    homepage_url TEXT,
                    source_sheet TEXT NOT NULL,
                    flagged_for_review INTEGER DEFAULT 0,
                    flag_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(name, homepage_url)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(name)")

            # snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    content_markdown TEXT,
                    content_html TEXT,
                    status_code INTEGER,
                    captured_at TEXT NOT NULL,
                    has_paywall INTEGER DEFAULT 0,
                    has_auth_required INTEGER DEFAULT 0,
                    error_message TEXT,
                    content_checksum TEXT,
                    http_last_modified TEXT,
                    capture_metadata TEXT,
                    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_snapshots_company_id ON snapshots(company_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_snapshots_captured_at ON snapshots(captured_at)"
            )

            # change_records table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS change_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    snapshot_id_old INTEGER NOT NULL,
                    snapshot_id_new INTEGER NOT NULL,
                    checksum_old TEXT NOT NULL,
                    checksum_new TEXT NOT NULL,
                    has_changed INTEGER NOT NULL,
                    change_magnitude TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    significance_classification TEXT,
                    significance_sentiment TEXT,
                    significance_confidence REAL,
                    matched_keywords TEXT,
                    matched_categories TEXT,
                    significance_notes TEXT,
                    evidence_snippets TEXT,
                    FOREIGN KEY (company_id)
                        REFERENCES companies(id) ON DELETE CASCADE,
                    FOREIGN KEY (snapshot_id_old)
                        REFERENCES snapshots(id) ON DELETE CASCADE,
                    FOREIGN KEY (snapshot_id_new)
                        REFERENCES snapshots(id) ON DELETE CASCADE
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_change_records_company_id"
                " ON change_records(company_id)"
            )

            # company_statuses table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS company_statuses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    indicators TEXT NOT NULL,
                    last_checked TEXT NOT NULL,
                    http_last_modified TEXT,
                    FOREIGN KEY (company_id)
                        REFERENCES companies(id) ON DELETE CASCADE
                )
            """)

            # social_media_links table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS social_media_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    profile_url TEXT NOT NULL,
                    discovery_method TEXT NOT NULL,
                    verification_status TEXT NOT NULL,
                    similarity_score REAL,
                    discovered_at TEXT NOT NULL,
                    last_verified_at TEXT,
                    html_location TEXT,
                    account_type TEXT,
                    account_confidence REAL,
                    rejection_reason TEXT,
                    FOREIGN KEY (company_id)
                        REFERENCES companies(id) ON DELETE CASCADE,
                    UNIQUE(company_id, profile_url)
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_social_media_links_company_id"
                " ON social_media_links(company_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_social_media_links_platform"
                " ON social_media_links(platform)"
            )

            # blog_links table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blog_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    blog_type TEXT NOT NULL,
                    blog_url TEXT NOT NULL,
                    discovery_method TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    discovered_at TEXT NOT NULL,
                    last_checked_at TEXT,
                    FOREIGN KEY (company_id)
                        REFERENCES companies(id) ON DELETE CASCADE,
                    UNIQUE(company_id, blog_url)
                )
            """)

            # news_articles table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS news_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    content_url TEXT NOT NULL,
                    source TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    match_confidence REAL NOT NULL,
                    match_evidence TEXT,
                    logo_similarity REAL,
                    company_match_snippet TEXT,
                    keyword_match_snippet TEXT,
                    significance_classification TEXT,
                    significance_sentiment TEXT,
                    significance_confidence REAL,
                    matched_keywords TEXT,
                    matched_categories TEXT,
                    significance_notes TEXT,
                    FOREIGN KEY (company_id)
                        REFERENCES companies(id) ON DELETE CASCADE,
                    UNIQUE(content_url)
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_news_articles_company_id"
                " ON news_articles(company_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_news_articles_published_at"
                " ON news_articles(published_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_news_articles_significance"
                " ON news_articles(significance_classification)"
            )

            # processing_errors table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processing_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    entity_id INTEGER,
                    error_type TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    occurred_at TEXT NOT NULL
                )
            """)

            # company_logos table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS company_logos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    image_data BLOB NOT NULL,
                    image_format TEXT NOT NULL,
                    perceptual_hash TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    extraction_location TEXT NOT NULL,
                    width INTEGER,
                    height INTEGER,
                    extracted_at TEXT NOT NULL,
                    FOREIGN KEY (company_id)
                        REFERENCES companies(id) ON DELETE CASCADE,
                    UNIQUE(company_id, perceptual_hash)
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_company_logos_company_id"
                " ON company_logos(company_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_company_logos_perceptual_hash"
                " ON company_logos(perceptual_hash)"
            )

            # company_leadership table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS company_leadership (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    person_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    linkedin_profile_url TEXT NOT NULL,
                    discovery_method TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    is_current INTEGER NOT NULL DEFAULT 1,
                    discovered_at TEXT NOT NULL,
                    last_verified_at TEXT,
                    source_company_linkedin_url TEXT,
                    FOREIGN KEY (company_id)
                        REFERENCES companies(id) ON DELETE CASCADE,
                    UNIQUE(company_id, linkedin_profile_url)
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_company_leadership_company_id"
                " ON company_leadership(company_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_company_leadership_title"
                " ON company_leadership(title)"
            )

        # Migrations: add baseline columns to snapshots table
        baseline_columns = [
            ("baseline_classification", "TEXT"),
            ("baseline_sentiment", "TEXT"),
            ("baseline_confidence", "REAL"),
            ("baseline_keywords", "TEXT"),
            ("baseline_categories", "TEXT"),
            ("baseline_notes", "TEXT"),
        ]
        for col_name, col_type in baseline_columns:
            with contextlib.suppress(sqlite3.OperationalError):
                self.execute(f"ALTER TABLE snapshots ADD COLUMN {col_name} {col_type}")

        logger.info("database_initialized", path=self.db_path)
