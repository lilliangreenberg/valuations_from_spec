"""Contract tests for SocialSnapshotManager.

Uses a real temp SQLite DB but mocks the FirecrawlClient to avoid API calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from src.domains.discovery.repositories.social_media_link_repository import (
    SocialMediaLinkRepository,
)
from src.domains.monitoring.repositories.social_snapshot_repository import (
    SocialSnapshotRepository,
)
from src.domains.monitoring.services.social_snapshot_manager import (
    SocialSnapshotManager,
)
from src.repositories.company_repository import CompanyRepository

if TYPE_CHECKING:
    from src.services.database import Database


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _insert_company(db: Database, name: str, url: str) -> int:
    now = _now_iso()
    cursor = db.execute(
        """INSERT INTO companies
           (name, homepage_url, source_sheet, flagged_for_review, created_at, updated_at)
           VALUES (?, ?, 'Test', 0, ?, ?)""",
        (name, url, now, now),
    )
    db.connection.commit()
    return cursor.lastrowid or 0


def _insert_medium_link(db: Database, company_id: int, url: str) -> None:
    now = _now_iso()
    db.execute(
        """INSERT INTO social_media_links
           (company_id, platform, profile_url, discovery_method,
            verification_status, discovered_at)
           VALUES (?, 'medium', ?, 'page_content', 'unverified', ?)""",
        (company_id, url, now),
    )
    db.connection.commit()


def _insert_blog_link(db: Database, company_id: int, url: str) -> None:
    now = _now_iso()
    db.execute(
        """INSERT INTO blog_links
           (company_id, blog_type, blog_url, discovery_method, is_active, discovered_at)
           VALUES (?, 'company_blog', ?, 'page_content', 1, ?)""",
        (company_id, url, now),
    )
    db.connection.commit()


def _mock_firecrawl_batch(
    documents: list[dict[str, Any]],
) -> MagicMock:
    mock = MagicMock()
    mock.batch_capture_snapshots.return_value = {
        "success": True,
        "documents": documents,
        "total": len(documents),
        "completed": len(documents),
        "failed": 0,
        "errors": [],
    }
    return mock


class TestSocialSnapshotManagerCollectUrls:
    """Tests for collect_social_urls."""

    def test_collects_medium_and_blog_urls(self, db: Database) -> None:
        company_id = _insert_company(db, "TestCo", "https://testco.com")
        _insert_medium_link(db, company_id, "https://medium.com/@testco")
        _insert_blog_link(db, company_id, "https://testco.com/blog")

        manager = SocialSnapshotManager(
            social_snapshot_repo=SocialSnapshotRepository(db, "test-user"),
            social_link_repo=SocialMediaLinkRepository(db, "test-user"),
            company_repo=CompanyRepository(db, "test-user"),
            firecrawl_client=MagicMock(),
        )

        urls = manager.collect_social_urls()
        assert len(urls) == 2
        types = {u["source_type"] for u in urls}
        assert types == {"medium", "blog"}

    def test_filters_by_company_id(self, db: Database) -> None:
        co1 = _insert_company(db, "Co1", "https://co1.com")
        co2 = _insert_company(db, "Co2", "https://co2.com")
        _insert_medium_link(db, co1, "https://medium.com/@co1")
        _insert_medium_link(db, co2, "https://medium.com/@co2")
        _insert_blog_link(db, co1, "https://co1.com/blog")

        manager = SocialSnapshotManager(
            social_snapshot_repo=SocialSnapshotRepository(db, "test-user"),
            social_link_repo=SocialMediaLinkRepository(db, "test-user"),
            company_repo=CompanyRepository(db, "test-user"),
            firecrawl_client=MagicMock(),
        )

        urls = manager.collect_social_urls(company_id=co1)
        assert len(urls) == 2
        assert all(u["company_id"] == co1 for u in urls)

    def test_empty_when_no_social_links(self, db: Database) -> None:
        _insert_company(db, "EmptyCo", "https://empty.com")

        manager = SocialSnapshotManager(
            social_snapshot_repo=SocialSnapshotRepository(db, "test-user"),
            social_link_repo=SocialMediaLinkRepository(db, "test-user"),
            company_repo=CompanyRepository(db, "test-user"),
            firecrawl_client=MagicMock(),
        )

        urls = manager.collect_social_urls()
        assert len(urls) == 0


class TestSocialSnapshotManagerCapture:
    """Tests for capture_social_snapshots."""

    def test_captures_and_stores_snapshots(self, db: Database) -> None:
        company_id = _insert_company(db, "TestCo", "https://testco.com")
        _insert_medium_link(db, company_id, "https://medium.com/@testco")

        mock_fc = _mock_firecrawl_batch(
            [
                {
                    "source_url": "https://medium.com/@testco",
                    "markdown": "# Post\n\nPublished on 2025-06-01\n\nContent here.",
                    "html": "<h1>Post</h1>",
                    "statusCode": 200,
                    "error": None,
                }
            ]
        )

        snap_repo = SocialSnapshotRepository(db, "test-user")
        manager = SocialSnapshotManager(
            social_snapshot_repo=snap_repo,
            social_link_repo=SocialMediaLinkRepository(db, "test-user"),
            company_repo=CompanyRepository(db, "test-user"),
            firecrawl_client=mock_fc,
        )

        result = manager.capture_social_snapshots()
        assert result["total"] == 1
        assert result["captured"] == 1
        assert result["failed"] == 0

        # Verify snapshot stored
        snapshots = snap_repo.get_latest_snapshots(company_id, "https://medium.com/@testco")
        assert len(snapshots) == 1
        assert snapshots[0]["source_type"] == "medium"
        assert snapshots[0]["content_checksum"] is not None
        assert snapshots[0]["latest_post_date"] is not None

    def test_no_urls_returns_zero_summary(self, db: Database) -> None:
        _insert_company(db, "Empty", "https://empty.com")

        manager = SocialSnapshotManager(
            social_snapshot_repo=SocialSnapshotRepository(db, "test-user"),
            social_link_repo=SocialMediaLinkRepository(db, "test-user"),
            company_repo=CompanyRepository(db, "test-user"),
            firecrawl_client=MagicMock(),
        )

        result = manager.capture_social_snapshots()
        assert result["total"] == 0
        assert result["captured"] == 0

    def test_limit_restricts_urls(self, db: Database) -> None:
        company_id = _insert_company(db, "TestCo", "https://testco.com")
        _insert_medium_link(db, company_id, "https://medium.com/@testco")
        _insert_blog_link(db, company_id, "https://testco.com/blog")

        mock_fc = _mock_firecrawl_batch(
            [
                {
                    "source_url": "https://medium.com/@testco",
                    "markdown": "# Post\n\n2025-03-01",
                    "html": "<h1>Post</h1>",
                    "statusCode": 200,
                }
            ]
        )

        manager = SocialSnapshotManager(
            social_snapshot_repo=SocialSnapshotRepository(db, "test-user"),
            social_link_repo=SocialMediaLinkRepository(db, "test-user"),
            company_repo=CompanyRepository(db, "test-user"),
            firecrawl_client=mock_fc,
        )

        result = manager.capture_social_snapshots(limit=1)
        assert result["total"] == 1

    def test_batch_api_failure_records_errors(self, db: Database) -> None:
        company_id = _insert_company(db, "TestCo", "https://testco.com")
        _insert_medium_link(db, company_id, "https://medium.com/@testco")

        mock_fc = MagicMock()
        mock_fc.batch_capture_snapshots.side_effect = ConnectionError("Network error")

        manager = SocialSnapshotManager(
            social_snapshot_repo=SocialSnapshotRepository(db, "test-user"),
            social_link_repo=SocialMediaLinkRepository(db, "test-user"),
            company_repo=CompanyRepository(db, "test-user"),
            firecrawl_client=mock_fc,
        )

        result = manager.capture_social_snapshots()
        assert result["failed"] >= 1
        assert len(result["errors"]) >= 1
