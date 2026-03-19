"""Integration tests for social media content monitoring workflow.

End-to-end tests covering: social URL collection -> snapshot capture ->
change detection -> significance analysis -> enrichment of homepage analysis.

Uses real temp SQLite DB. Mocks only external API clients (FirecrawlClient).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

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
from src.domains.monitoring.repositories.snapshot_repository import (
    SnapshotRepository,
)
from src.domains.monitoring.repositories.social_change_record_repository import (
    SocialChangeRecordRepository,
)
from src.domains.monitoring.repositories.social_snapshot_repository import (
    SocialSnapshotRepository,
)
from src.domains.monitoring.services.change_detector import ChangeDetector
from src.domains.monitoring.services.social_change_detector import SocialChangeDetector
from src.domains.monitoring.services.social_snapshot_manager import (
    SocialSnapshotManager,
)
from src.domains.monitoring.services.status_analyzer import StatusAnalyzer
from src.repositories.company_repository import CompanyRepository

if TYPE_CHECKING:
    from pathlib import Path

    from src.services.database import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workflow_db(tmp_path: Path) -> Database:
    """Fresh initialized database for integration tests."""
    from src.services.database import Database as DatabaseImpl

    db_path = str(tmp_path / "social_integration_test.db")
    database = DatabaseImpl(db_path=db_path)
    database.init_db()
    return database


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _insert_company(db: Database, name: str, homepage_url: str) -> int:
    now = _now_iso()
    cursor = db.execute(
        """INSERT INTO companies
           (name, homepage_url, source_sheet, flagged_for_review, created_at, updated_at)
           VALUES (?, ?, 'Online Presence', 0, ?, ?)""",
        (name, homepage_url, now, now),
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


def _mock_firecrawl_batch(documents: list[dict[str, Any]]) -> MagicMock:
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


# ===========================================================================
# 1. Full capture -> change detection workflow
# ===========================================================================


class TestSocialMonitoringFullWorkflow:
    """End-to-end: discover URLs -> capture snapshots -> detect changes."""

    def test_full_pipeline_capture_and_detect(self, workflow_db: Database) -> None:
        """Capture two rounds, then detect changes with significance."""
        db = workflow_db
        company_id = _insert_company(db, "AlphaCo", "https://alpha.com")
        _insert_medium_link(db, company_id, "https://medium.com/@alphaco")
        _insert_blog_link(db, company_id, "https://alpha.com/blog")

        social_snapshot_repo = SocialSnapshotRepository(db, "test-user")
        social_link_repo = SocialMediaLinkRepository(db, "test-user")
        company_repo = CompanyRepository(db, "test-user")

        # --- Round 1: Initial capture ---
        mock_fc1 = _mock_firecrawl_batch(
            [
                {
                    "source_url": "https://medium.com/@alphaco",
                    "markdown": "# AlphaCo Blog\n\nPublished on 2025-06-01\n\nOur journey begins.",
                    "html": "<h1>AlphaCo Blog</h1>",
                    "statusCode": 200,
                },
                {
                    "source_url": "https://alpha.com/blog",
                    "markdown": "# Company Blog\n\nPosted January 15, 2025\n\nProduct update.",
                    "html": "<h1>Company Blog</h1>",
                    "statusCode": 200,
                },
            ]
        )

        manager1 = SocialSnapshotManager(
            social_snapshot_repo=social_snapshot_repo,
            social_link_repo=social_link_repo,
            company_repo=company_repo,
            firecrawl_client=mock_fc1,
        )
        result1 = manager1.capture_social_snapshots()
        assert result1["total"] == 2
        assert result1["captured"] == 2

        # --- Round 2: Changed content ---
        mock_fc2 = _mock_firecrawl_batch(
            [
                {
                    "source_url": "https://medium.com/@alphaco",
                    "markdown": (
                        "# AlphaCo Blog\n\nPublished on 2025-08-15\n\n"
                        "We are excited to announce our Series B funding round "
                        "of $50M led by Sequoia Capital."
                    ),
                    "html": "<h1>AlphaCo Blog - Funding</h1>",
                    "statusCode": 200,
                },
                {
                    "source_url": "https://alpha.com/blog",
                    "markdown": (
                        "# Company Blog\n\nPosted August 10, 2025\n\n"
                        "Product update with new features and improvements."
                    ),
                    "html": "<h1>Company Blog - Update</h1>",
                    "statusCode": 200,
                },
            ]
        )

        manager2 = SocialSnapshotManager(
            social_snapshot_repo=social_snapshot_repo,
            social_link_repo=social_link_repo,
            company_repo=company_repo,
            firecrawl_client=mock_fc2,
        )
        result2 = manager2.capture_social_snapshots()
        assert result2["captured"] == 2

        # --- Detect changes ---
        social_change_repo = SocialChangeRecordRepository(db, "test-user")
        detector = SocialChangeDetector(
            social_snapshot_repo=social_snapshot_repo,
            social_change_record_repo=social_change_repo,
            company_repo=company_repo,
        )

        detect_result = detector.detect_all_changes()
        assert detect_result["changes_found"] == 2

        # Verify change records stored
        medium_changes = social_change_repo.get_changes_for_company(company_id)
        assert len(medium_changes) == 2
        assert all(c["has_changed"] for c in medium_changes)

    def test_no_change_when_content_identical(self, workflow_db: Database) -> None:
        """Same content in both rounds yields no change."""
        db = workflow_db
        company_id = _insert_company(db, "StaticCo", "https://static.com")
        _insert_medium_link(db, company_id, "https://medium.com/@staticco")

        social_snapshot_repo = SocialSnapshotRepository(db, "test-user")
        social_link_repo = SocialMediaLinkRepository(db, "test-user")
        company_repo = CompanyRepository(db, "test-user")

        identical_markdown = "# StaticCo\n\nPosted 2025-01-01\n\nNothing new here."
        mock_fc = _mock_firecrawl_batch(
            [
                {
                    "source_url": "https://medium.com/@staticco",
                    "markdown": identical_markdown,
                    "html": "<h1>StaticCo</h1>",
                    "statusCode": 200,
                }
            ]
        )

        # Two rounds with identical content
        for _ in range(2):
            manager = SocialSnapshotManager(
                social_snapshot_repo=social_snapshot_repo,
                social_link_repo=social_link_repo,
                company_repo=company_repo,
                firecrawl_client=mock_fc,
            )
            manager.capture_social_snapshots()

        social_change_repo = SocialChangeRecordRepository(db, "test-user")
        detector = SocialChangeDetector(
            social_snapshot_repo=social_snapshot_repo,
            social_change_record_repo=social_change_repo,
            company_repo=company_repo,
        )

        detect_result = detector.detect_all_changes()
        assert detect_result["changes_found"] == 0

    def test_significance_analysis_runs_on_changes(self, workflow_db: Database) -> None:
        """Changes containing significant keywords get classified."""
        db = workflow_db
        company_id = _insert_company(db, "FundedCo", "https://funded.com")
        _insert_medium_link(db, company_id, "https://medium.com/@fundedco")

        social_snapshot_repo = SocialSnapshotRepository(db, "test-user")
        social_link_repo = SocialMediaLinkRepository(db, "test-user")
        company_repo = CompanyRepository(db, "test-user")

        # Round 1: Basic content
        mock_fc1 = _mock_firecrawl_batch(
            [
                {
                    "source_url": "https://medium.com/@fundedco",
                    "markdown": "# FundedCo\n\nWe build great products.",
                    "html": "<h1>FundedCo</h1>",
                    "statusCode": 200,
                }
            ]
        )
        SocialSnapshotManager(
            social_snapshot_repo=social_snapshot_repo,
            social_link_repo=social_link_repo,
            company_repo=company_repo,
            firecrawl_client=mock_fc1,
        ).capture_social_snapshots()

        # Round 2: Significant change -- layoffs and closure
        mock_fc2 = _mock_firecrawl_batch(
            [
                {
                    "source_url": "https://medium.com/@fundedco",
                    "markdown": (
                        "# FundedCo\n\nWe regret to inform you that FundedCo "
                        "is shutting down operations. All employees have been "
                        "laid off effective immediately. The company has ceased "
                        "all business operations."
                    ),
                    "html": "<h1>FundedCo - Shutdown</h1>",
                    "statusCode": 200,
                }
            ]
        )
        SocialSnapshotManager(
            social_snapshot_repo=social_snapshot_repo,
            social_link_repo=social_link_repo,
            company_repo=company_repo,
            firecrawl_client=mock_fc2,
        ).capture_social_snapshots()

        # Detect
        social_change_repo = SocialChangeRecordRepository(db, "test-user")
        detector = SocialChangeDetector(
            social_snapshot_repo=social_snapshot_repo,
            social_change_record_repo=social_change_repo,
            company_repo=company_repo,
        )

        detect_result = detector.detect_all_changes()
        assert detect_result["changes_found"] == 1

        changes = social_change_repo.get_changes_for_company(company_id)
        # Verify significance analysis ran (classification field is populated)
        analyzed_changes = [c for c in changes if c.get("significance_classification") is not None]
        assert len(analyzed_changes) >= 1
        # Sentiment depends on diff extraction -- just verify it was set
        assert analyzed_changes[0]["significance_sentiment"] is not None


# ===========================================================================
# 2. Multi-company workflow
# ===========================================================================


class TestMultiCompanySocialWorkflow:
    """Multiple companies with social sources."""

    def test_captures_across_multiple_companies(self, workflow_db: Database) -> None:
        """Snapshot capture and change detection work across multiple companies."""
        db = workflow_db
        co1 = _insert_company(db, "Co1", "https://co1.com")
        co2 = _insert_company(db, "Co2", "https://co2.com")
        _insert_medium_link(db, co1, "https://medium.com/@co1")
        _insert_blog_link(db, co2, "https://co2.com/blog")

        social_snapshot_repo = SocialSnapshotRepository(db, "test-user")
        social_link_repo = SocialMediaLinkRepository(db, "test-user")
        company_repo = CompanyRepository(db, "test-user")

        mock_fc = _mock_firecrawl_batch(
            [
                {
                    "source_url": "https://medium.com/@co1",
                    "markdown": "# Co1\n\nInitial post.",
                    "html": "<h1>Co1</h1>",
                    "statusCode": 200,
                },
                {
                    "source_url": "https://co2.com/blog",
                    "markdown": "# Co2 Blog\n\nFirst entry.",
                    "html": "<h1>Co2 Blog</h1>",
                    "statusCode": 200,
                },
            ]
        )

        manager = SocialSnapshotManager(
            social_snapshot_repo=social_snapshot_repo,
            social_link_repo=social_link_repo,
            company_repo=company_repo,
            firecrawl_client=mock_fc,
        )

        result = manager.capture_social_snapshots()
        assert result["captured"] == 2

        # Verify each company has its own snapshot
        co1_sources = social_snapshot_repo.get_all_sources_for_company(co1)
        co2_sources = social_snapshot_repo.get_all_sources_for_company(co2)
        assert len(co1_sources) == 1
        assert len(co2_sources) == 1

    def test_company_filter_restricts_capture(self, workflow_db: Database) -> None:
        """company_id filter limits capture to one company."""
        db = workflow_db
        co1 = _insert_company(db, "Co1", "https://co1.com")
        co2 = _insert_company(db, "Co2", "https://co2.com")
        _insert_medium_link(db, co1, "https://medium.com/@co1")
        _insert_medium_link(db, co2, "https://medium.com/@co2")

        social_snapshot_repo = SocialSnapshotRepository(db, "test-user")
        social_link_repo = SocialMediaLinkRepository(db, "test-user")
        company_repo = CompanyRepository(db, "test-user")

        mock_fc = _mock_firecrawl_batch(
            [
                {
                    "source_url": "https://medium.com/@co1",
                    "markdown": "# Co1 Medium\n\nContent.",
                    "html": "<h1>Co1</h1>",
                    "statusCode": 200,
                }
            ]
        )

        manager = SocialSnapshotManager(
            social_snapshot_repo=social_snapshot_repo,
            social_link_repo=social_link_repo,
            company_repo=company_repo,
            firecrawl_client=mock_fc,
        )

        result = manager.capture_social_snapshots(company_id=co1)
        assert result["total"] == 1
        assert result["captured"] == 1


# ===========================================================================
# 3. Error resilience
# ===========================================================================


class TestSocialMonitoringErrorResilience:
    """Error handling in the social monitoring pipeline."""

    def test_batch_failure_does_not_crash(self, workflow_db: Database) -> None:
        """Pipeline continues when batch API fails."""
        db = workflow_db
        company_id = _insert_company(db, "FailCo", "https://fail.com")
        _insert_medium_link(db, company_id, "https://medium.com/@failco")

        social_snapshot_repo = SocialSnapshotRepository(db, "test-user")
        social_link_repo = SocialMediaLinkRepository(db, "test-user")
        company_repo = CompanyRepository(db, "test-user")

        mock_fc = MagicMock()
        mock_fc.batch_capture_snapshots.side_effect = ConnectionError("Network down")

        manager = SocialSnapshotManager(
            social_snapshot_repo=social_snapshot_repo,
            social_link_repo=social_link_repo,
            company_repo=company_repo,
            firecrawl_client=mock_fc,
        )

        result = manager.capture_social_snapshots()
        assert result["failed"] >= 1
        assert len(result["errors"]) >= 1
        assert result["captured"] == 0

    def test_single_snapshot_skipped_in_change_detection(self, workflow_db: Database) -> None:
        """Only one snapshot means no change detection possible."""
        db = workflow_db
        company_id = _insert_company(db, "NewCo", "https://new.com")
        _insert_medium_link(db, company_id, "https://medium.com/@newco")

        social_snapshot_repo = SocialSnapshotRepository(db, "test-user")
        social_link_repo = SocialMediaLinkRepository(db, "test-user")
        company_repo = CompanyRepository(db, "test-user")

        mock_fc = _mock_firecrawl_batch(
            [
                {
                    "source_url": "https://medium.com/@newco",
                    "markdown": "# NewCo\n\nFirst post.",
                    "html": "<h1>NewCo</h1>",
                    "statusCode": 200,
                }
            ]
        )

        SocialSnapshotManager(
            social_snapshot_repo=social_snapshot_repo,
            social_link_repo=social_link_repo,
            company_repo=company_repo,
            firecrawl_client=mock_fc,
        ).capture_social_snapshots()

        # Only 1 snapshot exists -- change detection should skip
        social_change_repo = SocialChangeRecordRepository(db, "test-user")
        detector = SocialChangeDetector(
            social_snapshot_repo=social_snapshot_repo,
            social_change_record_repo=social_change_repo,
            company_repo=company_repo,
        )

        # No pairs with 2+ snapshots
        detect_result = detector.detect_all_changes()
        assert detect_result["changes_found"] == 0


# ===========================================================================
# 4. Post date extraction integration
# ===========================================================================


class TestPostDateExtraction:
    """Verify post date extraction flows through the pipeline."""

    def test_latest_post_date_stored_in_snapshot(self, workflow_db: Database) -> None:
        """Captured snapshots store extracted post dates."""
        db = workflow_db
        company_id = _insert_company(db, "DateCo", "https://date.com")
        _insert_medium_link(db, company_id, "https://medium.com/@dateco")

        social_snapshot_repo = SocialSnapshotRepository(db, "test-user")
        social_link_repo = SocialMediaLinkRepository(db, "test-user")
        company_repo = CompanyRepository(db, "test-user")

        mock_fc = _mock_firecrawl_batch(
            [
                {
                    "source_url": "https://medium.com/@dateco",
                    "markdown": (
                        "# DateCo Updates\n\n"
                        "Published on 2025-07-15\n\n"
                        "Big announcement.\n\n"
                        "Published on 2025-03-01\n\n"
                        "Earlier post."
                    ),
                    "html": "<h1>DateCo</h1>",
                    "statusCode": 200,
                }
            ]
        )

        SocialSnapshotManager(
            social_snapshot_repo=social_snapshot_repo,
            social_link_repo=social_link_repo,
            company_repo=company_repo,
            firecrawl_client=mock_fc,
        ).capture_social_snapshots()

        snapshots = social_snapshot_repo.get_latest_snapshots(
            company_id, "https://medium.com/@dateco"
        )
        assert len(snapshots) == 1
        assert snapshots[0]["latest_post_date"] is not None
        # Should be the most recent date (2025-07-15)
        assert "2025-07-15" in snapshots[0]["latest_post_date"]


# ===========================================================================
# 5. --include-social enrichment integration
# ===========================================================================


def _insert_homepage_snapshot(
    db: Database,
    company_id: int,
    content_markdown: str,
    captured_at: str | None = None,
) -> int:
    """Insert a homepage snapshot and return its ID."""
    now = captured_at or _now_iso()
    checksum = hashlib.md5(content_markdown.encode("utf-8")).hexdigest()
    cursor = db.execute(
        """INSERT INTO snapshots
           (company_id, url, content_markdown, content_html,
            status_code, captured_at, has_paywall, has_auth_required, content_checksum)
           VALUES (?, 'https://example.com', ?, '', 200, ?, 0, 0, ?)""",
        (company_id, content_markdown, now, checksum),
    )
    db.connection.commit()
    return cursor.lastrowid or 0


def _insert_social_snapshot(
    db: Database,
    company_id: int,
    source_url: str,
    source_type: str,
    content_markdown: str,
    latest_post_date: str | None = None,
) -> int:
    """Insert a social media snapshot and return its ID."""
    now = _now_iso()
    checksum = hashlib.md5(content_markdown.encode("utf-8")).hexdigest()
    cursor = db.execute(
        """INSERT INTO social_media_snapshots
           (company_id, source_url, source_type, content_markdown, content_html,
            status_code, captured_at, content_checksum, latest_post_date)
           VALUES (?, ?, ?, ?, '', 200, ?, ?, ?)""",
        (company_id, source_url, source_type, content_markdown, now, checksum, latest_post_date),
    )
    db.connection.commit()
    return cursor.lastrowid or 0


class TestIncludeSocialChangeDetectorEnrichment:
    """Verify --include-social passes social context through to LLM."""

    def test_social_context_passed_to_llm_classify_significance(
        self, workflow_db: Database
    ) -> None:
        """When social_snapshot_repo is set, LLM receives social_context."""
        db = workflow_db
        company_id = _insert_company(db, "EnrichCo", "https://enrich.com")

        # Insert two differing homepage snapshots so change is detected
        _insert_homepage_snapshot(db, company_id, "# EnrichCo\n\nVersion 1 content.")
        _insert_homepage_snapshot(
            db,
            company_id,
            "# EnrichCo\n\nVersion 2 with layoffs and restructuring announcement.",
        )

        # Insert a social snapshot with a recent post date
        _insert_social_snapshot(
            db,
            company_id,
            source_url="https://medium.com/@enrichco",
            source_type="medium",
            content_markdown="# EnrichCo Blog\n\nLatest updates.",
            latest_post_date="2025-06-01T00:00:00",
        )

        snapshot_repo = SnapshotRepository(db, "test-user")
        change_record_repo = ChangeRecordRepository(db, "test-user")
        company_repo = CompanyRepository(db, "test-user")
        social_snapshot_repo = SocialSnapshotRepository(db, "test-user")

        mock_llm = MagicMock()
        mock_llm.classify_significance_with_status.return_value = {
            "classification": "significant",
            "sentiment": "negative",
            "confidence": 0.9,
            "reasoning": "Layoffs detected with social context.",
            "company_status": "operational",
            "status_reason": "Company shows active operations.",
        }

        detector = ChangeDetector(
            snapshot_repo=snapshot_repo,
            change_record_repo=change_record_repo,
            company_repo=company_repo,
            llm_client=mock_llm,
            llm_enabled=True,
            social_snapshot_repo=social_snapshot_repo,
        )

        detector.detect_all_changes()

        # Verify LLM was called with a non-empty social_context
        assert mock_llm.classify_significance_with_status.called
        call_kwargs = mock_llm.classify_significance_with_status.call_args
        social_context_arg = call_kwargs.kwargs.get("social_context", "")
        assert social_context_arg != "", "social_context should be non-empty"
        assert "medium" in social_context_arg.lower()

    def test_no_social_context_without_social_repo(self, workflow_db: Database) -> None:
        """Without social_snapshot_repo, LLM gets empty social_context."""
        db = workflow_db
        company_id = _insert_company(db, "NoSocialCo", "https://nosocial.com")

        _insert_homepage_snapshot(db, company_id, "# NoSocialCo\n\nVersion 1.")
        _insert_homepage_snapshot(
            db, company_id, "# NoSocialCo\n\nVersion 2 with acquisition news."
        )

        snapshot_repo = SnapshotRepository(db, "test-user")
        change_record_repo = ChangeRecordRepository(db, "test-user")
        company_repo = CompanyRepository(db, "test-user")

        mock_llm = MagicMock()
        mock_llm.classify_significance_with_status.return_value = {
            "classification": "significant",
            "sentiment": "negative",
            "confidence": 0.85,
            "company_status": "operational",
            "status_reason": "Active company detected.",
        }

        detector = ChangeDetector(
            snapshot_repo=snapshot_repo,
            change_record_repo=change_record_repo,
            company_repo=company_repo,
            llm_client=mock_llm,
            llm_enabled=True,
            # social_snapshot_repo NOT set
        )

        detector.detect_all_changes()

        assert mock_llm.classify_significance_with_status.called
        call_kwargs = mock_llm.classify_significance_with_status.call_args
        social_context_arg = call_kwargs.kwargs.get("social_context", "")
        assert social_context_arg == ""


class TestIncludeSocialStatusAnalyzerEnrichment:
    """Verify --include-social adds social indicators to status analysis."""

    def test_social_inactivity_added_as_indicator(self, workflow_db: Database) -> None:
        """StatusAnalyzer includes social inactivity when social_snapshot_repo is set."""
        db = workflow_db
        company_id = _insert_company(db, "InactiveCo", "https://inactive.com")

        # Insert a homepage snapshot so status analysis doesn't skip
        _insert_homepage_snapshot(
            db,
            company_id,
            "# InactiveCo\n\nWelcome to our site. Copyright 2025.",
        )

        # Insert a social snapshot with an OLD post date (inactive)
        _insert_social_snapshot(
            db,
            company_id,
            source_url="https://medium.com/@inactiveco",
            source_type="medium",
            content_markdown="# Old post",
            latest_post_date="2023-01-01T00:00:00",
        )

        snapshot_repo = SnapshotRepository(db, "test-user")
        status_repo = CompanyStatusRepository(db, "test-user")
        company_repo = CompanyRepository(db, "test-user")
        social_snapshot_repo = SocialSnapshotRepository(db, "test-user")

        analyzer = StatusAnalyzer(
            snapshot_repo=snapshot_repo,
            status_repo=status_repo,
            company_repo=company_repo,
            social_snapshot_repo=social_snapshot_repo,
        )

        analyzer.analyze_all_statuses()

        # Retrieve stored status and check for social indicator
        row = db.fetchone(
            "SELECT indicators FROM company_statuses WHERE company_id = ?",
            (company_id,),
        )
        assert row is not None
        import json

        indicators = json.loads(row["indicators"])
        social_indicators = [i for i in indicators if "social_media" in i.get("type", "")]
        assert len(social_indicators) >= 1
        assert any("inactive" in i["type"] for i in social_indicators)

    def test_no_social_indicators_without_repo(self, workflow_db: Database) -> None:
        """Without social_snapshot_repo, no social indicators appear."""
        db = workflow_db
        company_id = _insert_company(db, "PlainCo", "https://plain.com")

        _insert_homepage_snapshot(db, company_id, "# PlainCo\n\nWelcome. Copyright 2025.")

        snapshot_repo = SnapshotRepository(db, "test-user")
        status_repo = CompanyStatusRepository(db, "test-user")
        company_repo = CompanyRepository(db, "test-user")

        analyzer = StatusAnalyzer(
            snapshot_repo=snapshot_repo,
            status_repo=status_repo,
            company_repo=company_repo,
            # social_snapshot_repo NOT set
        )

        analyzer.analyze_all_statuses()

        row = db.fetchone(
            "SELECT indicators FROM company_statuses WHERE company_id = ?",
            (company_id,),
        )
        assert row is not None
        import json

        indicators = json.loads(row["indicators"])
        social_indicators = [i for i in indicators if "social_media" in i.get("type", "")]
        assert len(social_indicators) == 0
