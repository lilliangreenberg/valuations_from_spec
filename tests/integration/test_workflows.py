"""Integration tests for end-to-end workflows.

Exercise complete workflows across multiple components. Real Database with
tmp_path, mock only external API clients (FirecrawlClient, AirtableClient,
KagiClient).
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
from src.domains.discovery.services.social_media_discovery import (
    SocialMediaDiscovery,
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
from src.domains.monitoring.services.change_detector import ChangeDetector
from src.domains.monitoring.services.significance_analyzer import (
    SignificanceAnalyzer,
)
from src.domains.monitoring.services.status_analyzer import StatusAnalyzer
from src.domains.news.repositories.news_article_repository import (
    NewsArticleRepository,
)
from src.domains.news.services.news_monitor_manager import (
    NewsMonitorManager,
)
from src.repositories.company_repository import CompanyRepository
from src.services.extractor import CompanyExtractor
from src.services.snapshot_manager import SnapshotManager

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

    db_path = str(tmp_path / "integration_test.db")
    database = DatabaseImpl(db_path=db_path)
    database.init_db()
    return database


def _insert_company(db: Database, name: str, homepage_url: str | None) -> int:
    """Insert a company directly and return its ID."""
    now = datetime.now(UTC).isoformat()
    cursor = db.execute(
        """INSERT INTO companies (name, homepage_url, source_sheet,
           flagged_for_review, created_at, updated_at)
           VALUES (?, ?, ?, 0, ?, ?)""",
        (name, homepage_url, "Online Presence", now, now),
    )
    db.connection.commit()
    return cursor.lastrowid or 0


def _insert_snapshot(
    db: Database,
    company_id: int,
    content_markdown: str,
    content_html: str = "",
    captured_at: str | None = None,
) -> int:
    """Insert a snapshot directly and return its ID."""
    now = captured_at or datetime.now(UTC).isoformat()
    checksum = hashlib.md5(content_markdown.encode("utf-8")).hexdigest()
    cursor = db.execute(
        """INSERT INTO snapshots
           (company_id, url, content_markdown, content_html,
            status_code, captured_at, has_paywall,
            has_auth_required, content_checksum)
           VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?)""",
        (
            company_id,
            "https://example.com",
            content_markdown,
            content_html,
            200,
            now,
            checksum,
        ),
    )
    db.connection.commit()
    return cursor.lastrowid or 0


# ===========================================================================
# 1. Full extraction -> snapshot -> change detection workflow
# ===========================================================================


class TestExtractionSnapshotChangeWorkflow:
    """Full pipeline: extract -> snapshot -> detect changes."""

    def test_full_pipeline(self, workflow_db: Database) -> None:
        """Airtable extraction -> snapshot -> change -> detect."""
        db = workflow_db

        # --- Step 1: Extract companies from Airtable ---
        mock_airtable = MagicMock()
        mock_airtable.fetch_online_presence_records.return_value = [
            {
                "id": "rec1",
                "fields": {
                    "resources": ["homepage"],
                    "company_name": ["recLINK1"],
                    "url": "https://alpha.com",
                },
            },
            {
                "id": "rec2",
                "fields": {
                    "resources": ["homepage"],
                    "company_name": ["recLINK2"],
                    "url": "https://beta.com",
                },
            },
        ]
        mock_airtable.build_company_name_lookup.return_value = {
            "recLINK1": "Alpha Inc",
            "recLINK2": "Beta Inc",
        }

        company_repo = CompanyRepository(db)
        extractor = CompanyExtractor(mock_airtable, company_repo)
        extract_summary = extractor.extract_companies()

        assert extract_summary["stored"] == 2
        all_companies = company_repo.get_all_companies()
        assert len(all_companies) == 2

        # --- Step 2: First snapshot capture ---
        mock_firecrawl = MagicMock()

        def first_round_capture(url: str) -> dict[str, Any]:
            return {
                "success": True,
                "markdown": f"# Welcome to {url} - Version 1",
                "html": f"<h1>Welcome to {url}</h1>",
                "statusCode": 200,
                "metadata": {},
                "has_paywall": False,
                "has_auth_required": False,
                "error": None,
            }

        mock_firecrawl.capture_snapshot.side_effect = first_round_capture

        snapshot_repo = SnapshotRepository(db)
        manager = SnapshotManager(mock_firecrawl, snapshot_repo, company_repo)
        snap1_summary = manager.capture_all_snapshots()

        assert snap1_summary["successful"] == 2

        # --- Step 3: Second snapshot with different content ---
        def second_round_capture(url: str) -> dict[str, Any]:
            return {
                "success": True,
                "markdown": (f"# Welcome to {url} - Version 2 with layoffs and restructuring news"),
                "html": f"<h1>Welcome to {url} - Updated</h1>",
                "statusCode": 200,
                "metadata": {},
                "has_paywall": False,
                "has_auth_required": False,
                "error": None,
            }

        mock_firecrawl.capture_snapshot.side_effect = second_round_capture
        snap2_summary = manager.capture_all_snapshots()

        assert snap2_summary["successful"] == 2

        # --- Step 4: Detect changes ---
        change_repo = ChangeRecordRepository(db)
        detector = ChangeDetector(snapshot_repo, change_repo, company_repo)
        change_summary = detector.detect_all_changes()

        assert change_summary["changes_found"] == 2
        assert change_summary["successful"] == 2

        # Verify change records with significance
        for company in all_companies:
            changes = change_repo.get_changes_for_company(company["id"])
            assert len(changes) == 1
            record = changes[0]
            assert record["has_changed"] == 1
            assert record["significance_classification"] is not None


# ===========================================================================
# 2. Social media discovery workflow
# ===========================================================================


class TestSocialMediaDiscoveryWorkflow:
    """Social media discovery across multiple companies."""

    def test_discover_social_links_for_companies(self, workflow_db: Database) -> None:
        """Discover social media links from scraped HTML."""
        db = workflow_db
        cid1 = _insert_company(db, "Alpha Inc", "https://alpha.com")
        cid2 = _insert_company(db, "Beta Inc", "https://beta.com")

        html_alpha = """<html>
        <head>
            <meta property="og:url" content="https://alpha.com">
        </head>
        <body>
            <footer>
                <a href="https://twitter.com/alphainc">Twitter</a>
                <a href="https://linkedin.com/company/alpha-inc">
                    LinkedIn</a>
                <a href="https://github.com/alphainc">GitHub</a>
                <a href="https://blog.alpha.com/posts">Blog</a>
            </footer>
        </body>
        </html>"""

        html_beta = """<html>
        <body>
            <footer>
                <a href="https://www.youtube.com/@betainc">
                    YouTube</a>
                <a href="https://www.instagram.com/betainc">
                    Instagram</a>
            </footer>
        </body>
        </html>"""

        mock_firecrawl = MagicMock()
        mock_firecrawl.batch_capture_snapshots.return_value = {
            "success": True,
            "documents": [
                {
                    "url": "https://alpha.com",
                    "markdown": "# Alpha Inc",
                    "html": html_alpha,
                },
                {
                    "url": "https://beta.com",
                    "markdown": "# Beta Inc",
                    "html": html_beta,
                },
            ],
            "total": 2,
            "completed": 2,
            "failed": 0,
            "errors": [],
        }

        social_repo = SocialMediaLinkRepository(db)
        company_repo = CompanyRepository(db)
        discovery = SocialMediaDiscovery(mock_firecrawl, social_repo, company_repo)

        summary = discovery.discover_all(batch_size=50)

        assert summary["successful"] == 2

        # Alpha should have twitter, linkedin, github
        alpha_links = social_repo.get_links_for_company(cid1)
        alpha_platforms = {lnk["platform"] for lnk in alpha_links}
        assert "twitter" in alpha_platforms
        assert "linkedin" in alpha_platforms
        assert "github" in alpha_platforms

        # Beta should have youtube, instagram
        beta_links = social_repo.get_links_for_company(cid2)
        beta_platforms = {lnk["platform"] for lnk in beta_links}
        assert "youtube" in beta_platforms
        assert "instagram" in beta_platforms

        assert summary.get("total_links_found", 0) >= 4


# ===========================================================================
# 3. News monitoring workflow
# ===========================================================================


class TestNewsMonitoringWorkflow:
    """News monitoring: search -> verify -> store."""

    def test_news_search_and_storage(self, workflow_db: Database) -> None:
        """Articles searched, verified, and stored."""
        db = workflow_db
        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")

        mock_kagi = MagicMock()
        mock_kagi.search.return_value = [
            {
                "title": "Alpha Inc raises $30M Series A",
                "url": ("https://techcrunch.com/2025/alpha-inc-funding"),
                "snippet": ("Alpha Inc, the startup behind the popular platform, raised funding."),
                "published": "2025-06-15T00:00:00+00:00",
                "source": "techcrunch.com",
            },
            {
                "title": "Alpha Inc launches new product",
                "url": "https://alpha.com/blog/new-product",
                "snippet": ("Alpha Inc announced a major product launch today."),
                "published": "2025-07-01T00:00:00+00:00",
                "source": "alpha.com",
            },
        ]

        news_repo = NewsArticleRepository(db)
        company_repo = CompanyRepository(db)
        snapshot_repo = SnapshotRepository(db)
        manager = NewsMonitorManager(mock_kagi, news_repo, company_repo, snapshot_repo)

        result = manager.search_company_news(company_id=cid)

        assert result["articles_found"] == 2
        assert result["articles_verified"] >= 1
        assert result["articles_stored"] >= 1

        articles = news_repo.get_news_articles(cid)
        stored_urls = {a["content_url"] for a in articles}
        assert "https://alpha.com/blog/new-product" in stored_urls

    def test_duplicates_rejected_on_second_run(self, workflow_db: Database) -> None:
        """Running news search twice does not create duplicates."""
        db = workflow_db
        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")

        kagi_results = [
            {
                "title": "Alpha Inc launches product",
                "url": "https://alpha.com/blog/launch",
                "snippet": ("Alpha Inc announced a major product launch today."),
                "published": "2025-06-15T00:00:00+00:00",
                "source": "alpha.com",
            },
        ]

        mock_kagi = MagicMock()
        mock_kagi.search.return_value = kagi_results

        news_repo = NewsArticleRepository(db)
        company_repo = CompanyRepository(db)
        snapshot_repo = SnapshotRepository(db)
        manager = NewsMonitorManager(mock_kagi, news_repo, company_repo, snapshot_repo)

        # First run
        result1 = manager.search_company_news(company_id=cid)
        first_stored = result1["articles_stored"]
        assert first_stored >= 1

        # Second run - same URL should be rejected
        result2 = manager.search_company_news(company_id=cid)
        assert result2["articles_stored"] == 0

        all_articles = news_repo.get_news_articles(cid)
        assert len(all_articles) == first_stored


# ===========================================================================
# 4. Status analysis workflow
# ===========================================================================


class TestStatusAnalysisWorkflow:
    """Status analysis from snapshot content."""

    def test_operational_status(self, workflow_db: Database) -> None:
        """Recent copyright year -> operational."""
        db = workflow_db
        current_year = datetime.now(UTC).year
        cid = _insert_company(db, "Active Corp", "https://active.com")
        _insert_snapshot(
            db,
            cid,
            f"# Active Corp\n\nWe build great things.\n\n"
            f"Copyright {current_year} Active Corp. "
            f"All rights reserved.",
        )

        snapshot_repo = SnapshotRepository(db)
        status_repo = CompanyStatusRepository(db)
        company_repo = CompanyRepository(db)
        analyzer = StatusAnalyzer(snapshot_repo, status_repo, company_repo)

        summary = analyzer.analyze_all_statuses()

        assert summary["successful"] >= 1

        status = status_repo.get_latest_status(cid)
        assert status is not None
        assert status["status"] == "operational"
        assert status["confidence"] > 0

    def test_likely_closed_from_acquisition(self, workflow_db: Database) -> None:
        """Acquisition text -> likely_closed."""
        db = workflow_db
        current_year = datetime.now(UTC).year
        cid = _insert_company(db, "Old Corp", "https://old.com")
        _insert_snapshot(
            db,
            cid,
            f"# Old Corp\n\nOld Corp has been acquired by "
            f"BigTech Inc. All services are now part of "
            f"BigTech.\n\nCopyright {current_year} Old Corp.",
        )

        snapshot_repo = SnapshotRepository(db)
        status_repo = CompanyStatusRepository(db)
        company_repo = CompanyRepository(db)
        analyzer = StatusAnalyzer(snapshot_repo, status_repo, company_repo)

        summary = analyzer.analyze_all_statuses()

        assert summary["successful"] >= 1

        status = status_repo.get_latest_status(cid)
        assert status is not None
        assert status["status"] == "likely_closed"

    def test_multiple_companies_analyzed(self, workflow_db: Database) -> None:
        """All companies with snapshots analyzed in one batch."""
        db = workflow_db
        current_year = datetime.now(UTC).year

        cid1 = _insert_company(db, "Active Corp", "https://active.com")
        _insert_snapshot(
            db,
            cid1,
            f"# Active Corp\n\nCopyright {current_year} Active Corp.",
        )

        cid2 = _insert_company(db, "Stale Corp", "https://stale.com")
        _insert_snapshot(
            db,
            cid2,
            "# Stale Corp\n\nCopyright 2018 Stale Corp.",
        )

        cid3 = _insert_company(db, "No Snap Corp", "https://nosnap.com")
        # No snapshot for cid3

        snapshot_repo = SnapshotRepository(db)
        status_repo = CompanyStatusRepository(db)
        company_repo = CompanyRepository(db)
        analyzer = StatusAnalyzer(snapshot_repo, status_repo, company_repo)

        summary = analyzer.analyze_all_statuses()

        assert summary["successful"] >= 2
        assert summary["skipped"] >= 1  # No Snap Corp

        status1 = status_repo.get_latest_status(cid1)
        status2 = status_repo.get_latest_status(cid2)
        status3 = status_repo.get_latest_status(cid3)

        assert status1 is not None
        assert status1["status"] == "operational"

        assert status2 is not None
        assert status2["status"] in ("likely_closed", "uncertain")

        assert status3 is None


# ===========================================================================
# 5. Significance backfill workflow
# ===========================================================================


class TestSignificanceBackfillWorkflow:
    """Backfill significance for existing change records."""

    def test_backfill_updates_records(self, workflow_db: Database) -> None:
        """Change records without significance get backfilled."""
        db = workflow_db
        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")

        snap_old_id = _insert_snapshot(
            db,
            cid,
            "# Old content",
            captured_at="2025-01-01T00:00:00+00:00",
        )
        snap_new_id = _insert_snapshot(
            db,
            cid,
            "# Alpha Inc raised $50M in Series B funding. Revenue growth is strong.",
            captured_at="2025-02-01T00:00:00+00:00",
        )

        now = datetime.now(UTC).isoformat()
        db.execute(
            """INSERT INTO change_records
               (company_id, snapshot_id_old, snapshot_id_new,
                checksum_old, checksum_new, has_changed,
                change_magnitude, detected_at)
               VALUES (?, ?, ?, ?, ?, 1, 'moderate', ?)""",
            (cid, snap_old_id, snap_new_id, "aaa", "bbb", now),
        )
        db.connection.commit()

        change_repo = ChangeRecordRepository(db)
        snapshot_repo = SnapshotRepository(db)
        analyzer = SignificanceAnalyzer(change_repo, snapshot_repo)

        summary = analyzer.backfill_significance()

        assert summary["successful"] >= 1

        records = change_repo.get_changes_for_company(cid)
        assert len(records) == 1
        record = records[0]
        assert record["significance_classification"] is not None
        assert record["significance_confidence"] is not None
        assert record["significance_confidence"] > 0

    def test_dry_run_preserves_null(self, workflow_db: Database) -> None:
        """dry_run=True processes but does not persist changes."""
        db = workflow_db
        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")

        snap_old_id = _insert_snapshot(
            db,
            cid,
            "# Old content",
            captured_at="2025-01-01T00:00:00+00:00",
        )
        snap_new_id = _insert_snapshot(
            db,
            cid,
            "# Alpha Inc had major layoffs today",
            captured_at="2025-02-01T00:00:00+00:00",
        )

        now = datetime.now(UTC).isoformat()
        cursor = db.execute(
            """INSERT INTO change_records
               (company_id, snapshot_id_old, snapshot_id_new,
                checksum_old, checksum_new, has_changed,
                change_magnitude, detected_at)
               VALUES (?, ?, ?, ?, ?, 1, 'major', ?)""",
            (cid, snap_old_id, snap_new_id, "aaa", "bbb", now),
        )
        db.connection.commit()
        record_id = cursor.lastrowid

        change_repo = ChangeRecordRepository(db)
        snapshot_repo = SnapshotRepository(db)
        analyzer = SignificanceAnalyzer(change_repo, snapshot_repo)

        summary = analyzer.backfill_significance(dry_run=True)

        assert summary["successful"] >= 1

        row = db.fetchone(
            "SELECT * FROM change_records WHERE id = ?",
            (record_id,),
        )
        assert row is not None
        assert row["significance_classification"] is None

    def test_already_analyzed_records_skipped(self, workflow_db: Database) -> None:
        """Records with significance are not re-processed."""
        db = workflow_db
        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")

        snap_old_id = _insert_snapshot(
            db,
            cid,
            "# Old content",
            captured_at="2025-01-01T00:00:00+00:00",
        )
        snap_new_id = _insert_snapshot(
            db,
            cid,
            "# New content",
            captured_at="2025-02-01T00:00:00+00:00",
        )

        now = datetime.now(UTC).isoformat()
        db.execute(
            """INSERT INTO change_records
               (company_id, snapshot_id_old, snapshot_id_new,
                checksum_old, checksum_new, has_changed,
                change_magnitude, detected_at,
                significance_classification)
               VALUES (?, ?, ?, ?, ?, 1, 'minor', ?,
                       'insignificant')""",
            (cid, snap_old_id, snap_new_id, "aaa", "bbb", now),
        )
        db.connection.commit()

        change_repo = ChangeRecordRepository(db)
        snapshot_repo = SnapshotRepository(db)
        analyzer = SignificanceAnalyzer(change_repo, snapshot_repo)

        summary = analyzer.backfill_significance()

        assert summary["successful"] == 0
        assert summary["processed"] == 0

    def test_combined_workflow_detect_then_backfill(self, workflow_db: Database) -> None:
        """Change detection + backfill integration."""
        db = workflow_db
        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")
        _insert_snapshot(
            db,
            cid,
            "# Old content about the company",
            captured_at="2025-01-01T00:00:00+00:00",
        )
        _insert_snapshot(
            db,
            cid,
            "# Company raised funding in Series A. Major partnership announced.",
            captured_at="2025-02-01T00:00:00+00:00",
        )

        snapshot_repo = SnapshotRepository(db)
        change_repo = ChangeRecordRepository(db)
        company_repo = CompanyRepository(db)

        # Step 1: Detect changes (which also runs significance)
        detector = ChangeDetector(snapshot_repo, change_repo, company_repo)
        detect_summary = detector.detect_all_changes()

        assert detect_summary["changes_found"] >= 1

        # Step 2: Backfill should find nothing to do
        analyzer = SignificanceAnalyzer(change_repo, snapshot_repo)
        analyzer.backfill_significance()

        records = change_repo.get_changes_for_company(cid)
        for record in records:
            if record["has_changed"]:
                assert record["significance_classification"] is not None


# ===========================================================================
# 7. Baseline Signal Analysis Workflow
# ===========================================================================


class TestBaselineSignalWorkflow:
    """Integration tests for baseline signal analysis."""

    def test_auto_baseline_on_first_scrape(self, workflow_db: Database) -> None:
        """When SnapshotManager captures the first snapshot for a company,
        baseline analysis runs automatically."""
        db = workflow_db
        cid = _insert_company(db, "New Corp", "https://newcorp.com")

        snapshot_repo = SnapshotRepository(db)
        company_repo = CompanyRepository(db)

        # Mock firecrawl client
        mock_firecrawl = MagicMock()
        mock_firecrawl.capture_snapshot.return_value = {
            "markdown": (
                "# New Corp\nWe are shutting down operations. "
                "Ceased operations effective immediately. Winding down."
            ),
            "html": "<h1>New Corp</h1>",
            "metadata": {"statusCode": 200},
        }

        manager = SnapshotManager(mock_firecrawl, snapshot_repo, company_repo)
        manager.capture_all_snapshots()

        # Verify snapshot was stored
        snapshots = snapshot_repo.get_snapshots_for_company(cid)
        assert len(snapshots) == 1

        # Verify baseline was auto-computed
        snap = snapshots[0]
        assert snap["baseline_classification"] is not None
        assert snap["baseline_confidence"] is not None
        assert snap["baseline_confidence"] > 0

    def test_baseline_not_recomputed_on_second_scrape(self, workflow_db: Database) -> None:
        """Second scrape for same company does NOT recompute baseline."""
        db = workflow_db
        cid = _insert_company(db, "Existing Corp", "https://existing.com")

        # Insert first snapshot manually with baseline
        snap_id = _insert_snapshot(
            db, cid, "# Old content", captured_at="2025-01-01T00:00:00+00:00"
        )
        snapshot_repo = SnapshotRepository(db)
        snapshot_repo.update_baseline(
            snap_id,
            {
                "baseline_classification": "insignificant",
                "baseline_sentiment": "neutral",
                "baseline_confidence": 0.75,
                "baseline_keywords": [],
                "baseline_categories": [],
                "baseline_notes": "Original baseline",
            },
        )

        company_repo = CompanyRepository(db)

        mock_firecrawl = MagicMock()
        mock_firecrawl.capture_snapshot.return_value = {
            "markdown": "# New content with layoffs and restructuring",
            "html": "<h1>New content</h1>",
            "metadata": {"statusCode": 200},
        }

        manager = SnapshotManager(mock_firecrawl, snapshot_repo, company_repo)
        manager.capture_all_snapshots()

        # Should have 2 snapshots now
        snapshots = snapshot_repo.get_snapshots_for_company(cid)
        assert len(snapshots) == 2

        # First snapshot should still have original baseline
        first = snapshots[0]
        assert first["baseline_notes"] == "Original baseline"

        # Second snapshot should NOT have baseline (not first scrape)
        second = snapshots[1]
        assert second["baseline_classification"] is None

    def test_baseline_backfill_workflow(self, workflow_db: Database) -> None:
        """Backfill baselines for companies that were scraped before
        the baseline feature existed."""
        db = workflow_db

        # Create companies with existing snapshots (no baseline)
        cid1 = _insert_company(db, "Alpha Inc", "https://alpha.com")
        cid2 = _insert_company(db, "Beta Corp", "https://beta.com")

        _insert_snapshot(
            db,
            cid1,
            "# Alpha Inc\nWe raised funding in Series A. Revenue doubled.",
            captured_at="2025-01-01T00:00:00+00:00",
        )
        _insert_snapshot(
            db,
            cid2,
            "# Beta Corp\nOur team is growing with new hires.",
            captured_at="2025-01-01T00:00:00+00:00",
        )

        snapshot_repo = SnapshotRepository(db)
        from src.domains.monitoring.services.baseline_analyzer import BaselineAnalyzer

        analyzer = BaselineAnalyzer(snapshot_repo)
        summary = analyzer.backfill_baselines()

        assert summary["successful"] == 2

        # Verify both companies have baselines
        assert snapshot_repo.has_baseline_for_company(cid1) is True
        assert snapshot_repo.has_baseline_for_company(cid2) is True

    def test_diff_based_detection_with_baseline(self, workflow_db: Database) -> None:
        """Full workflow: first scrape gets baseline, change detection uses diff."""
        db = workflow_db
        cid = _insert_company(db, "Full Pipeline", "https://fullpipeline.com")

        # Insert two snapshots with shared boilerplate
        boilerplate = (
            "We are an international company with strategic partnerships "
            "and expansion into new markets."
        )
        _insert_snapshot(
            db,
            cid,
            f"# Full Pipeline\n{boilerplate}\nOld section",
            captured_at="2025-01-01T00:00:00+00:00",
        )
        _insert_snapshot(
            db,
            cid,
            f"# Full Pipeline\n{boilerplate}\nNew section with updated team info",
            captured_at="2025-02-01T00:00:00+00:00",
        )

        # Run baseline on first snapshot
        snapshot_repo = SnapshotRepository(db)
        from src.domains.monitoring.services.baseline_analyzer import BaselineAnalyzer

        baseline = BaselineAnalyzer(snapshot_repo)
        first_snaps = snapshot_repo.get_snapshots_for_company(cid)
        baseline.analyze_baseline_for_snapshot(first_snaps[0]["id"])

        # Baseline should have caught "international", "partnerships", "expansion"
        first_snap = snapshot_repo.get_snapshot_by_id(first_snaps[0]["id"])
        assert first_snap is not None
        assert first_snap["baseline_classification"] is not None

        # Run change detection -- should NOT flag boilerplate keywords
        change_repo = ChangeRecordRepository(db)
        company_repo = CompanyRepository(db)
        detector = ChangeDetector(snapshot_repo, change_repo, company_repo)
        detector.detect_all_changes()

        changes = change_repo.get_changes_for_company(cid)
        assert len(changes) == 1
        record = changes[0]
        assert record["has_changed"] == 1
        # Diff only contains "New section with updated team info" -- no keywords
        assert record["significance_classification"] in ("insignificant", None)
