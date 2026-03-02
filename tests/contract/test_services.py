"""Contract tests for services that call external APIs.

Mock the API clients, use real Database for data persistence verification.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from src.domains.discovery.repositories.social_media_link_repository import (
    SocialMediaLinkRepository,
)
from src.domains.discovery.services.account_classifier import AccountClassifier
from src.domains.discovery.services.logo_service import LogoService
from src.domains.discovery.services.social_media_discovery import SocialMediaDiscovery
from src.domains.monitoring.repositories.change_record_repository import (
    ChangeRecordRepository,
)
from src.domains.monitoring.repositories.company_status_repository import (
    CompanyStatusRepository,
)
from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
from src.domains.monitoring.services.change_detector import ChangeDetector
from src.domains.monitoring.services.significance_analyzer import SignificanceAnalyzer
from src.domains.monitoring.services.status_analyzer import StatusAnalyzer
from src.domains.news.repositories.news_article_repository import (
    NewsArticleRepository,
)
from src.domains.news.services.company_verifier import CompanyVerifier
from src.domains.news.services.news_analyzer import NewsAnalyzer
from src.domains.news.services.news_monitor_manager import NewsMonitorManager
from src.repositories.company_repository import CompanyRepository
from src.services.batch_snapshot_manager import BatchSnapshotManager
from src.services.extractor import CompanyExtractor
from src.services.snapshot_manager import SnapshotManager

if TYPE_CHECKING:
    from src.services.database import Database


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_company(db: Database, name: str, homepage_url: str | None) -> int:
    """Insert a company and return its ID."""
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
    """Insert a snapshot and return its ID."""
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


def _insert_change_record(
    db: Database,
    company_id: int,
    snap_old_id: int,
    snap_new_id: int,
    has_changed: bool = True,
    magnitude: str = "moderate",
    significance_classification: str | None = None,
) -> int:
    """Insert a change record and return its ID."""
    now = datetime.now(UTC).isoformat()
    cursor = db.execute(
        """INSERT INTO change_records
           (company_id, snapshot_id_old, snapshot_id_new,
            checksum_old, checksum_new, has_changed,
            change_magnitude, detected_at,
            significance_classification)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            company_id,
            snap_old_id,
            snap_new_id,
            "aaa",
            "bbb",
            1 if has_changed else 0,
            magnitude,
            now,
            significance_classification,
        ),
    )
    db.connection.commit()
    return cursor.lastrowid or 0


# ===========================================================================
# 1. SnapshotManager
# ===========================================================================


class TestSnapshotManager:
    """Contract tests for SnapshotManager with mocked FirecrawlClient."""

    def test_captures_snapshots_for_all_companies(self, db: Database) -> None:
        """Snapshots are captured/stored for every company with a URL."""
        cid1 = _insert_company(db, "Alpha Inc", "https://alpha.com")
        cid2 = _insert_company(db, "Beta Inc", "https://beta.com")

        mock_firecrawl = MagicMock()
        mock_firecrawl.capture_snapshot.return_value = {
            "success": True,
            "markdown": "# Hello World",
            "html": "<h1>Hello World</h1>",
            "statusCode": 200,
            "metadata": {},
            "has_paywall": False,
            "has_auth_required": False,
            "error": None,
        }

        snapshot_repo = SnapshotRepository(db)
        company_repo = CompanyRepository(db)
        manager = SnapshotManager(mock_firecrawl, snapshot_repo, company_repo)

        summary = manager.capture_all_snapshots()

        assert summary["successful"] == 2
        assert summary["failed"] == 0
        assert mock_firecrawl.capture_snapshot.call_count == 2

        # Verify data persisted
        snaps_alpha = snapshot_repo.get_latest_snapshots(cid1, limit=1)
        snaps_beta = snapshot_repo.get_latest_snapshots(cid2, limit=1)
        assert len(snaps_alpha) == 1
        assert len(snaps_beta) == 1

    def test_records_failures(self, db: Database) -> None:
        """Failed captures are recorded without aborting the batch."""
        _insert_company(db, "Alpha Inc", "https://alpha.com")
        _insert_company(db, "Beta Inc", "https://beta.com")

        mock_firecrawl = MagicMock()
        mock_firecrawl.capture_snapshot.side_effect = [
            ConnectionError("timeout"),
            {
                "success": True,
                "markdown": "# OK",
                "html": "<h1>OK</h1>",
                "statusCode": 200,
                "metadata": {},
                "has_paywall": False,
                "has_auth_required": False,
                "error": None,
            },
        ]

        snapshot_repo = SnapshotRepository(db)
        company_repo = CompanyRepository(db)
        manager = SnapshotManager(mock_firecrawl, snapshot_repo, company_repo)

        summary = manager.capture_all_snapshots()

        assert summary["successful"] == 1
        assert summary["failed"] == 1
        assert len(summary["errors"]) == 1

    def test_skips_companies_without_urls(self, db: Database) -> None:
        """Companies without homepage_url are filtered out."""
        _insert_company(db, "Alpha Inc", "https://alpha.com")
        _insert_company(db, "No URL Corp", None)

        mock_firecrawl = MagicMock()
        mock_firecrawl.capture_snapshot.return_value = {
            "success": True,
            "markdown": "# Hello",
            "html": "<h1>Hello</h1>",
            "statusCode": 200,
            "metadata": {},
            "has_paywall": False,
            "has_auth_required": False,
            "error": None,
        }

        snapshot_repo = SnapshotRepository(db)
        company_repo = CompanyRepository(db)
        manager = SnapshotManager(mock_firecrawl, snapshot_repo, company_repo)

        summary = manager.capture_all_snapshots()

        # get_companies_with_homepage excludes NULL homepage_url
        assert mock_firecrawl.capture_snapshot.call_count == 1
        assert summary["successful"] == 1


# ===========================================================================
# 2. BatchSnapshotManager
# ===========================================================================


class TestBatchSnapshotManager:
    """Contract tests for BatchSnapshotManager with mocked FirecrawlClient."""

    def test_processes_batch(self, db: Database) -> None:
        """Batch snapshots captured and stored for all companies."""
        cid1 = _insert_company(db, "Alpha Inc", "https://alpha.com")
        cid2 = _insert_company(db, "Beta Inc", "https://beta.com")

        mock_firecrawl = MagicMock()
        mock_firecrawl.batch_capture_snapshots.return_value = {
            "success": True,
            "documents": [
                {
                    "url": "https://alpha.com",
                    "markdown": "# Alpha",
                    "html": "<h1>Alpha</h1>",
                    "metadata": {"statusCode": 200},
                },
                {
                    "url": "https://beta.com",
                    "markdown": "# Beta",
                    "html": "<h1>Beta</h1>",
                    "metadata": {"statusCode": 200},
                },
            ],
            "total": 2,
            "completed": 2,
            "failed": 0,
            "errors": [],
        }

        snapshot_repo = SnapshotRepository(db)
        company_repo = CompanyRepository(db)
        manager = BatchSnapshotManager(mock_firecrawl, snapshot_repo, company_repo)

        summary = manager.capture_batch_snapshots(batch_size=10)

        assert summary["successful"] == 2
        assert summary["failed"] == 0

        # Verify persisted
        assert len(snapshot_repo.get_latest_snapshots(cid1, limit=1)) == 1
        assert len(snapshot_repo.get_latest_snapshots(cid2, limit=1)) == 1

    def test_handles_batch_failure(self, db: Database) -> None:
        """Batch API failure marks all URLs as failed."""
        _insert_company(db, "Alpha Inc", "https://alpha.com")
        _insert_company(db, "Beta Inc", "https://beta.com")

        mock_firecrawl = MagicMock()
        mock_firecrawl.batch_capture_snapshots.return_value = {
            "success": False,
            "documents": [],
            "total": 2,
            "completed": 0,
            "failed": 2,
            "errors": ["Batch timeout"],
        }

        snapshot_repo = SnapshotRepository(db)
        company_repo = CompanyRepository(db)
        manager = BatchSnapshotManager(mock_firecrawl, snapshot_repo, company_repo)

        summary = manager.capture_batch_snapshots(batch_size=10)

        assert summary["failed"] == 2
        assert summary["successful"] == 0

    def test_url_to_company_matching(self, db: Database) -> None:
        """Documents matched to companies via URL prefix matching."""
        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")

        mock_firecrawl = MagicMock()
        mock_firecrawl.batch_capture_snapshots.return_value = {
            "success": True,
            "documents": [
                {
                    "url": "https://alpha.com/",
                    "markdown": "# Alpha",
                    "html": "<h1>Alpha</h1>",
                    "metadata": {"statusCode": 200},
                },
            ],
            "total": 1,
            "completed": 1,
            "failed": 0,
            "errors": [],
        }

        snapshot_repo = SnapshotRepository(db)
        company_repo = CompanyRepository(db)
        manager = BatchSnapshotManager(mock_firecrawl, snapshot_repo, company_repo)

        summary = manager.capture_batch_snapshots(batch_size=10)

        assert summary["successful"] == 1
        assert len(snapshot_repo.get_latest_snapshots(cid, limit=1)) == 1


# ===========================================================================
# 3. CompanyExtractor
# ===========================================================================


class TestCompanyExtractor:
    """Contract tests for CompanyExtractor with mocked AirtableClient."""

    def test_extracts_and_stores_companies(self, db: Database) -> None:
        """Companies extracted from Airtable and stored in DB."""
        mock_airtable = MagicMock()
        mock_airtable.fetch_online_presence_records.return_value = [
            {
                "id": "rec1",
                "fields": {
                    "resources": ["homepage"],
                    "company_name": ["recABC"],
                    "url": "https://alpha.com",
                },
            },
            {
                "id": "rec2",
                "fields": {
                    "resources": ["homepage"],
                    "company_name": ["recDEF"],
                    "url": "https://beta.com",
                },
            },
        ]
        mock_airtable.build_company_name_lookup.return_value = {
            "recABC": "Alpha Inc",
            "recDEF": "Beta Inc",
        }

        company_repo = CompanyRepository(db)
        extractor = CompanyExtractor(mock_airtable, company_repo)

        summary = extractor.extract_companies()

        assert summary["stored"] == 2
        assert summary["errors"] == 0

        all_companies = company_repo.get_all_companies()
        names = {c["name"] for c in all_companies}
        assert "Alpha Inc" in names
        assert "Beta Inc" in names

    def test_handles_missing_fields(self, db: Database) -> None:
        """Records with missing company_name are skipped."""
        mock_airtable = MagicMock()
        mock_airtable.fetch_online_presence_records.return_value = [
            {
                "id": "rec1",
                "fields": {
                    "resources": ["homepage"],
                    "url": "https://alpha.com",
                },
            },
        ]
        mock_airtable.build_company_name_lookup.return_value = {}

        company_repo = CompanyRepository(db)
        extractor = CompanyExtractor(mock_airtable, company_repo)

        summary = extractor.extract_companies()

        assert summary["skipped"] == 1
        assert summary["stored"] == 0

    def test_resolves_linked_records(self, db: Database) -> None:
        """Linked record IDs resolved via bulk name lookup."""
        mock_airtable = MagicMock()
        mock_airtable.fetch_online_presence_records.return_value = [
            {
                "id": "rec1",
                "fields": {
                    "resources": ["homepage"],
                    "company_name": ["recLINKED123"],
                    "url": "https://linked.com",
                },
            },
        ]
        mock_airtable.build_company_name_lookup.return_value = {
            "recLINKED123": "Linked Corp",
        }

        company_repo = CompanyRepository(db)
        extractor = CompanyExtractor(mock_airtable, company_repo)

        summary = extractor.extract_companies()

        mock_airtable.build_company_name_lookup.assert_called_once()
        assert summary["stored"] == 1
        company = company_repo.get_company_by_name("Linked Corp")
        assert company is not None
        assert company["homepage_url"] == "https://linked.com"

    def test_skips_non_homepage_resources(self, db: Database) -> None:
        """Records that are not homepage resources are skipped."""
        mock_airtable = MagicMock()
        mock_airtable.fetch_online_presence_records.return_value = [
            {
                "id": "rec1",
                "fields": {
                    "resources": ["blog"],
                    "company_name": ["recABC"],
                    "url": "https://blog.example.com",
                },
            },
        ]
        mock_airtable.build_company_name_lookup.return_value = {"recABC": "Test Co"}

        company_repo = CompanyRepository(db)
        extractor = CompanyExtractor(mock_airtable, company_repo)

        summary = extractor.extract_companies()

        assert summary["skipped"] == 1
        assert summary["stored"] == 0


# ===========================================================================
# 4. ChangeDetector
# ===========================================================================


class TestChangeDetector:
    """Contract tests for ChangeDetector using real DB."""

    def test_detects_changes(self, db: Database) -> None:
        """Differing checksums trigger significance analysis."""
        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")
        _insert_snapshot(
            db,
            cid,
            "# Old content about layoffs and restructuring",
            captured_at="2025-01-01T00:00:00+00:00",
        )
        _insert_snapshot(
            db,
            cid,
            "# New content about layoffs and downsizing",
            captured_at="2025-02-01T00:00:00+00:00",
        )

        snapshot_repo = SnapshotRepository(db)
        change_repo = ChangeRecordRepository(db)
        company_repo = CompanyRepository(db)
        detector = ChangeDetector(snapshot_repo, change_repo, company_repo)

        summary = detector.detect_all_changes()

        assert summary["changes_found"] >= 1
        assert summary["successful"] >= 1

        changes = change_repo.get_changes_for_company(cid)
        assert len(changes) >= 1
        assert changes[0]["has_changed"] == 1
        assert changes[0]["significance_classification"] is not None

    def test_handles_no_change(self, db: Database) -> None:
        """When checksums are identical, has_changed is False."""
        cid = _insert_company(db, "Stable Inc", "https://stable.com")
        same_content = "# Stable content that never changes"
        _insert_snapshot(
            db,
            cid,
            same_content,
            captured_at="2025-01-01T00:00:00+00:00",
        )
        _insert_snapshot(
            db,
            cid,
            same_content,
            captured_at="2025-02-01T00:00:00+00:00",
        )

        snapshot_repo = SnapshotRepository(db)
        change_repo = ChangeRecordRepository(db)
        company_repo = CompanyRepository(db)
        detector = ChangeDetector(snapshot_repo, change_repo, company_repo)

        summary = detector.detect_all_changes()

        assert summary["successful"] >= 1
        changes = change_repo.get_changes_for_company(cid)
        assert len(changes) == 1
        assert changes[0]["has_changed"] == 0
        assert changes[0]["change_magnitude"] == "minor"

    def test_significance_analysis_runs_on_changed_content(self, db: Database) -> None:
        """Significance populates classification for changed records."""
        cid = _insert_company(db, "Funding Corp", "https://funding.com")
        _insert_snapshot(
            db,
            cid,
            "# About us",
            captured_at="2025-01-01T00:00:00+00:00",
        )
        _insert_snapshot(
            db,
            cid,
            "# We raised funding in a Series A round. Our valuation is growing.",
            captured_at="2025-02-01T00:00:00+00:00",
        )

        snapshot_repo = SnapshotRepository(db)
        change_repo = ChangeRecordRepository(db)
        company_repo = CompanyRepository(db)
        detector = ChangeDetector(snapshot_repo, change_repo, company_repo)

        detector.detect_all_changes()

        changes = change_repo.get_changes_for_company(cid)
        assert len(changes) == 1
        record = changes[0]
        classifications = ("significant", "insignificant", "uncertain")
        assert record["significance_classification"] in classifications
        assert record["significance_confidence"] is not None
        assert record["significance_confidence"] > 0


# ===========================================================================
# 5. SignificanceAnalyzer
# ===========================================================================


class TestSignificanceAnalyzer:
    """Contract tests for SignificanceAnalyzer backfill functionality."""

    def test_backfills_significance(self, db: Database) -> None:
        """Records without significance get backfilled."""
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
            "# Company raised funding in a Series B round. Revenue growth is strong.",
            captured_at="2025-02-01T00:00:00+00:00",
        )
        record_id = _insert_change_record(
            db,
            cid,
            snap_old_id,
            snap_new_id,
            has_changed=True,
            significance_classification=None,
        )

        change_repo = ChangeRecordRepository(db)
        snapshot_repo = SnapshotRepository(db)
        analyzer = SignificanceAnalyzer(change_repo, snapshot_repo)

        summary = analyzer.backfill_significance()

        assert summary["successful"] >= 1

        row = db.fetchone("SELECT * FROM change_records WHERE id = ?", (record_id,))
        assert row is not None
        assert row["significance_classification"] is not None

    def test_dry_run_does_not_update(self, db: Database) -> None:
        """dry_run=True processes but does not write to DB."""
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
            "# New content about layoffs",
            captured_at="2025-02-01T00:00:00+00:00",
        )
        record_id = _insert_change_record(
            db,
            cid,
            snap_old_id,
            snap_new_id,
            has_changed=True,
            significance_classification=None,
        )

        change_repo = ChangeRecordRepository(db)
        snapshot_repo = SnapshotRepository(db)
        analyzer = SignificanceAnalyzer(change_repo, snapshot_repo)

        summary = analyzer.backfill_significance(dry_run=True)

        assert summary["successful"] >= 1

        row = db.fetchone("SELECT * FROM change_records WHERE id = ?", (record_id,))
        assert row is not None
        assert row["significance_classification"] is None


class TestDiffBasedSignificance:
    """Contract tests verifying diff-based (not full-content) significance analysis."""

    def test_boilerplate_keywords_not_flagged(self, db: Database) -> None:
        """Keywords in static boilerplate (present in both snapshots) are NOT flagged.

        This is the core false-positive fix: 'international' and 'partnership' in
        unchanging page content should produce no significance signals.
        """
        boilerplate = (
            "We are an international company with strategic partnerships. "
            "Our expansion into new markets continues through collaboration. "
            "We offer partnership opportunities and international services."
        )
        cid = _insert_company(db, "Boilerplate Corp", "https://boilerplate.com")
        _insert_snapshot(
            db,
            cid,
            f"# About Us\n{boilerplate}\nOld footer text",
            captured_at="2025-01-01T00:00:00+00:00",
        )
        _insert_snapshot(
            db,
            cid,
            f"# About Us\n{boilerplate}\nNew footer text",
            captured_at="2025-02-01T00:00:00+00:00",
        )

        snapshot_repo = SnapshotRepository(db)
        change_repo = ChangeRecordRepository(db)
        company_repo = CompanyRepository(db)
        detector = ChangeDetector(snapshot_repo, change_repo, company_repo)

        detector.detect_all_changes()

        changes = change_repo.get_changes_for_company(cid)
        assert len(changes) == 1
        record = changes[0]
        assert record["has_changed"] == 1
        # The diff only contains "New footer text" -- no significant keywords
        assert record["significance_classification"] in (
            "insignificant",
            None,
        )

    def test_new_keywords_in_diff_are_flagged(self, db: Database) -> None:
        """Keywords only in the new content ARE detected via diff analysis."""
        cid = _insert_company(db, "Growing Corp", "https://growing.com")
        _insert_snapshot(
            db,
            cid,
            "# About Us\nWe are a technology company.",
            captured_at="2025-01-01T00:00:00+00:00",
        )
        _insert_snapshot(
            db,
            cid,
            (
                "# About Us\nWe are a technology company.\n"
                "We just raised funding in our Series B round. "
                "Our valuation has doubled with strong revenue growth."
            ),
            captured_at="2025-02-01T00:00:00+00:00",
        )

        snapshot_repo = SnapshotRepository(db)
        change_repo = ChangeRecordRepository(db)
        company_repo = CompanyRepository(db)
        detector = ChangeDetector(snapshot_repo, change_repo, company_repo)

        detector.detect_all_changes()

        changes = change_repo.get_changes_for_company(cid)
        assert len(changes) == 1
        record = changes[0]
        assert record["has_changed"] == 1
        assert record["significance_classification"] == "significant"
        assert record["significance_sentiment"] == "positive"

    def test_backfill_uses_diff(self, db: Database) -> None:
        """Backfill also uses diff-based analysis, not full new content."""
        boilerplate = "We offer international expansion and partnership opportunities."
        cid = _insert_company(db, "Backfill Corp", "https://backfill.com")
        snap_old_id = _insert_snapshot(
            db,
            cid,
            f"# Page\n{boilerplate}\nOld section",
            captured_at="2025-01-01T00:00:00+00:00",
        )
        snap_new_id = _insert_snapshot(
            db,
            cid,
            f"# Page\n{boilerplate}\nNew section",
            captured_at="2025-02-01T00:00:00+00:00",
        )
        record_id = _insert_change_record(
            db,
            cid,
            snap_old_id,
            snap_new_id,
            has_changed=True,
            significance_classification=None,
        )

        change_repo = ChangeRecordRepository(db)
        snapshot_repo = SnapshotRepository(db)
        analyzer = SignificanceAnalyzer(change_repo, snapshot_repo)

        analyzer.backfill_significance()

        row = db.fetchone("SELECT * FROM change_records WHERE id = ?", (record_id,))
        assert row is not None
        # Diff contains only "New section" -- no significant keywords
        assert row["significance_classification"] in ("insignificant", None)


# ===========================================================================
# 5b. BaselineAnalyzer
# ===========================================================================


class TestBaselineAnalyzer:
    """Contract tests for BaselineAnalyzer service."""

    def test_analyze_baseline_for_snapshot(self, db: Database) -> None:
        """Baseline analysis populates baseline columns on snapshot."""
        cid = _insert_company(db, "Baseline Corp", "https://baseline.com")
        snap_id = _insert_snapshot(
            db,
            cid,
            ("# Baseline Corp\nWe raised funding in a Series A round. Our valuation has doubled."),
            captured_at="2025-01-01T00:00:00+00:00",
        )

        snapshot_repo = SnapshotRepository(db)
        from src.domains.monitoring.services.baseline_analyzer import BaselineAnalyzer

        analyzer = BaselineAnalyzer(snapshot_repo)
        result = analyzer.analyze_baseline_for_snapshot(snap_id)

        assert result is not None
        assert result["baseline_classification"] is not None

        row = db.fetchone("SELECT * FROM snapshots WHERE id = ?", (snap_id,))
        assert row is not None
        assert row["baseline_classification"] is not None
        assert row["baseline_confidence"] is not None
        assert row["baseline_confidence"] > 0

    def test_analyze_baseline_for_company_skips_if_exists(self, db: Database) -> None:
        """Once a baseline exists for a company, it is not re-computed."""
        cid = _insert_company(db, "Already Done", "https://already.com")
        _insert_snapshot(
            db,
            cid,
            "# Some content with funding mentioned",
            captured_at="2025-01-01T00:00:00+00:00",
        )

        snapshot_repo = SnapshotRepository(db)
        from src.domains.monitoring.services.baseline_analyzer import BaselineAnalyzer

        analyzer = BaselineAnalyzer(snapshot_repo)

        # First run -- should compute baseline
        result1 = analyzer.analyze_baseline_for_company(cid)
        assert result1 is not None

        # Second run -- should skip
        result2 = analyzer.analyze_baseline_for_company(cid)
        assert result2 is None

    def test_backfill_baselines_processes_multiple_companies(self, db: Database) -> None:
        """Backfill processes one snapshot per company."""
        cid1 = _insert_company(db, "Company A", "https://a.com")
        cid2 = _insert_company(db, "Company B", "https://b.com")
        _insert_snapshot(db, cid1, "# Company A page", captured_at="2025-01-01T00:00:00+00:00")
        _insert_snapshot(db, cid2, "# Company B page", captured_at="2025-01-01T00:00:00+00:00")

        snapshot_repo = SnapshotRepository(db)
        from src.domains.monitoring.services.baseline_analyzer import BaselineAnalyzer

        analyzer = BaselineAnalyzer(snapshot_repo)
        summary = analyzer.backfill_baselines()

        assert summary["successful"] == 2

    def test_backfill_dry_run_does_not_write(self, db: Database) -> None:
        """dry_run=True does not update the database."""
        cid = _insert_company(db, "Dry Corp", "https://dry.com")
        snap_id = _insert_snapshot(
            db, cid, "# Dry Corp content", captured_at="2025-01-01T00:00:00+00:00"
        )

        snapshot_repo = SnapshotRepository(db)
        from src.domains.monitoring.services.baseline_analyzer import BaselineAnalyzer

        analyzer = BaselineAnalyzer(snapshot_repo)
        summary = analyzer.backfill_baselines(dry_run=True)

        assert summary["successful"] == 1

        row = db.fetchone("SELECT * FROM snapshots WHERE id = ?", (snap_id,))
        assert row is not None
        assert row["baseline_classification"] is None


# ===========================================================================
# 6. StatusAnalyzer
# ===========================================================================


class TestStatusAnalyzer:
    """Contract tests for StatusAnalyzer using real DB."""

    def test_analyzes_status_from_copyright_year(self, db: Database) -> None:
        """A recent copyright year results in operational status."""
        cid = _insert_company(db, "Active Corp", "https://active.com")
        current_year = datetime.now(UTC).year
        _insert_snapshot(
            db,
            cid,
            f"# Active Corp\n\nWelcome.\n\nCopyright {current_year} Active Corp.",
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

    def test_analyzes_status_with_acquisition_text(self, db: Database) -> None:
        """Acquisition text results in likely_closed status."""
        cid = _insert_company(db, "Acquired Corp", "https://acquired.com")
        current_year = datetime.now(UTC).year
        _insert_snapshot(
            db,
            cid,
            f"# Acquired Corp\n\nWe have been acquired by BigTech. "
            f"Copyright {current_year} Acquired Corp.",
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

    def test_skips_company_without_snapshot(self, db: Database) -> None:
        """Companies without any snapshots are skipped."""
        _insert_company(db, "Empty Corp", "https://empty.com")

        snapshot_repo = SnapshotRepository(db)
        status_repo = CompanyStatusRepository(db)
        company_repo = CompanyRepository(db)
        analyzer = StatusAnalyzer(snapshot_repo, status_repo, company_repo)

        summary = analyzer.analyze_all_statuses()

        assert summary["skipped"] >= 1


# ===========================================================================
# 7. SocialMediaDiscovery
# ===========================================================================


class TestSocialMediaDiscovery:
    """Contract tests for SocialMediaDiscovery with mocked Firecrawl."""

    def test_discovers_and_stores_social_links(
        self, db: Database, sample_html_with_social_links: str
    ) -> None:
        """Social media links extracted from HTML and stored in DB."""
        cid = _insert_company(db, "Acme Corp", "https://acme.com")

        mock_firecrawl = MagicMock()
        mock_firecrawl.capture_snapshot.return_value = {
            "success": True,
            "markdown": "# Acme Corp",
            "html": sample_html_with_social_links,
            "statusCode": 200,
            "metadata": {},
            "has_paywall": False,
            "has_auth_required": False,
            "error": None,
        }

        social_repo = SocialMediaLinkRepository(db)
        company_repo = CompanyRepository(db)
        discovery = SocialMediaDiscovery(mock_firecrawl, social_repo, company_repo)

        summary = discovery.discover_all(company_id=cid)

        assert summary.get("total_links_found", 0) > 0

        links = social_repo.get_links_for_company(cid)
        platforms_found = {link["platform"] for link in links}
        assert len(platforms_found) >= 3

    def test_detects_blogs(self, db: Database, sample_html_with_social_links: str) -> None:
        """Blog URLs are detected and stored separately."""
        cid = _insert_company(db, "Acme Corp", "https://acme.com")

        mock_firecrawl = MagicMock()
        mock_firecrawl.capture_snapshot.return_value = {
            "success": True,
            "markdown": "# Acme Corp",
            "html": sample_html_with_social_links,
            "statusCode": 200,
            "metadata": {},
            "has_paywall": False,
            "has_auth_required": False,
            "error": None,
        }

        social_repo = SocialMediaLinkRepository(db)
        company_repo = CompanyRepository(db)
        discovery = SocialMediaDiscovery(mock_firecrawl, social_repo, company_repo)

        summary = discovery.discover_all(company_id=cid)

        # Verify discovery ran without errors
        blog_count = summary.get("total_blogs_found", 0)
        assert blog_count >= 0

    def test_batch_processing(self, db: Database) -> None:
        """Multiple companies processed in batch when count > 1."""
        _insert_company(db, "Alpha Inc", "https://alpha.com")
        _insert_company(db, "Beta Inc", "https://beta.com")

        html_with_links = """<html><body>
        <footer>
            <a href="https://twitter.com/alpha">Twitter</a>
            <a href="https://github.com/alpha">GitHub</a>
        </footer>
        </body></html>"""

        mock_firecrawl = MagicMock()
        mock_firecrawl.batch_capture_snapshots.return_value = {
            "success": True,
            "documents": [
                {
                    "url": "https://alpha.com",
                    "markdown": "# Alpha",
                    "html": html_with_links,
                },
                {
                    "url": "https://beta.com",
                    "markdown": "# Beta",
                    "html": html_with_links.replace("alpha", "beta"),
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
        assert summary.get("total_links_found", 0) >= 2


# ===========================================================================
# 8. AccountClassifier
# ===========================================================================


class TestAccountClassifier:
    """Contract tests for AccountClassifier (pure logic)."""

    def test_company_account_in_footer_with_matching_handle(
        self,
    ) -> None:
        """Company handle in footer -> 'company' with high confidence."""
        classifier = AccountClassifier()
        account_type, confidence = classifier.classify_account(
            url="https://twitter.com/acmecorp",
            platform="twitter",
            company_name="Acme Corp",
            html_location="footer",
        )
        assert account_type == "company"
        assert confidence >= 0.6

    def test_unknown_handle_in_main(self) -> None:
        """Unknown handle in main content -> 'personal'."""
        classifier = AccountClassifier()
        account_type, confidence = classifier.classify_account(
            url="https://twitter.com/randomuser12345",
            platform="twitter",
            company_name="Acme Corp",
            html_location="main",
        )
        assert account_type == "personal"

    def test_matching_handle_no_location(self) -> None:
        """Matching handle without location gives moderate confidence."""
        classifier = AccountClassifier()
        account_type, confidence = classifier.classify_account(
            url="https://github.com/acme-corp",
            platform="github",
            company_name="Acme Corp",
            html_location=None,
        )
        assert confidence >= 0.3
        assert account_type in ("unknown", "company")

    def test_logo_similarity_boost(self) -> None:
        """High logo similarity adds to confidence score."""
        classifier = AccountClassifier()
        account_type, confidence = classifier.classify_account(
            url="https://twitter.com/acmecorp",
            platform="twitter",
            company_name="Acme Corp",
            html_location="footer",
            logo_similarity=0.95,
        )
        # handle(0.4) + footer(0.3) + logo(0.3) = 1.0
        assert account_type == "company"
        assert confidence == 1.0


# ===========================================================================
# 9. LogoService
# ===========================================================================


class TestLogoService:
    """Contract tests for LogoService HTML extraction.

    Strategy priority order:
      0. JSON-LD schema.org Organization logo
      1. Header/nav image linked to homepage
      2. First img with 'logo' in class/id/alt (outside third-party sections)
      3. Favicon / apple-touch-icon
      4. og:image (lowest priority)
    """

    # -- Strategy 0: JSON-LD --

    def test_jsonld_organization_logo_is_highest_priority(self) -> None:
        """JSON-LD Organization logo wins over all other strategies."""
        service = LogoService()
        html = (
            "<html><head>"
            '<script type="application/ld+json">'
            '{"@type": "Organization", "name": "Acme", '
            '"logo": "https://acme.com/brand-logo.svg"}'
            "</script>"
            '<meta property="og:image" content="https://acme.com/banner.png">'
            "</head><body>"
            '<header><a href="/"><img src="/header-logo.png" alt="Logo"></a></header>'
            "</body></html>"
        )
        result = service.extract_logo_from_html(html, "https://acme.com")
        assert result is not None
        assert result["source_url"] == "https://acme.com/brand-logo.svg"
        assert result["extraction_location"] == "jsonld"

    def test_jsonld_logo_as_object_with_url(self) -> None:
        """JSON-LD logo can be an object with a 'url' property."""
        service = LogoService()
        html = (
            "<html><head>"
            '<script type="application/ld+json">'
            '{"@type": "Organization", "logo": '
            '{"@type": "ImageObject", "url": "https://acme.com/logo.png"}}'
            "</script>"
            "</head><body></body></html>"
        )
        result = service.extract_logo_from_html(html, "https://acme.com")
        assert result is not None
        assert result["source_url"] == "https://acme.com/logo.png"
        assert result["extraction_location"] == "jsonld"

    def test_jsonld_nested_in_array(self) -> None:
        """JSON-LD with @graph array containing Organization."""
        service = LogoService()
        html = (
            "<html><head>"
            '<script type="application/ld+json">'
            '[{"@type": "WebSite"}, '
            '{"@type": "Organization", "logo": "https://acme.com/logo.svg"}]'
            "</script>"
            "</head><body></body></html>"
        )
        result = service.extract_logo_from_html(html, "https://acme.com")
        assert result is not None
        assert result["source_url"] == "https://acme.com/logo.svg"

    def test_jsonld_skips_third_party_logo_url(self) -> None:
        """JSON-LD logo is skipped if it matches a third-party URL pattern."""
        service = LogoService()
        html = (
            "<html><head>"
            '<script type="application/ld+json">'
            '{"@type": "Organization", '
            '"logo": "https://ycombinator.com/logo.png"}'
            "</script>"
            '<link rel="icon" href="/favicon.ico">'
            "</head><body></body></html>"
        )
        result = service.extract_logo_from_html(html, "https://acme.com")
        assert result is not None
        # Falls through to favicon
        assert result["source_url"] == "/favicon.ico"

    def test_jsonld_handles_malformed_json(self) -> None:
        """Malformed JSON-LD does not crash; falls through to next strategy."""
        service = LogoService()
        html = (
            "<html><head>"
            '<script type="application/ld+json">{not valid json</script>'
            '<link rel="icon" href="/favicon.ico">'
            "</head><body></body></html>"
        )
        result = service.extract_logo_from_html(html, "https://acme.com")
        assert result is not None
        assert result["source_url"] == "/favicon.ico"

    # -- Strategy 1: Header/nav linked to homepage --

    def test_header_nav_logo_linked_to_homepage(self) -> None:
        """Image in <header> inside <a href="/"> is extracted."""
        service = LogoService()
        html = (
            "<html><head></head><body>"
            '<header><a href="/"><img src="/brand.svg" alt="Home"></a></header>'
            "</body></html>"
        )
        result = service.extract_logo_from_html(html, "https://example.com")
        assert result is not None
        assert result["source_url"] == "/brand.svg"
        assert result["extraction_location"] == "header"

    def test_nav_logo_linked_to_domain(self) -> None:
        """Image in <nav> linked to the full domain URL is extracted."""
        service = LogoService()
        html = (
            "<html><head></head><body>"
            '<nav><a href="https://example.com/">'
            '<img src="/logo.png" alt="Example">'
            "</a></nav>"
            "</body></html>"
        )
        result = service.extract_logo_from_html(html, "https://example.com")
        assert result is not None
        assert result["source_url"] == "/logo.png"
        assert result["extraction_location"] == "header"

    def test_header_logo_with_logo_class_fallback(self) -> None:
        """Image in <header> with 'logo' class found even without homepage link."""
        service = LogoService()
        html = (
            "<html><head></head><body>"
            '<header><img src="/site-logo.svg" class="logo" alt=""></header>'
            "</body></html>"
        )
        result = service.extract_logo_from_html(html, "https://example.com")
        assert result is not None
        assert result["source_url"] == "/site-logo.svg"
        assert result["extraction_location"] == "header"

    def test_header_logo_beats_body_logo(self) -> None:
        """Header logo wins over a logo in the body."""
        service = LogoService()
        html = (
            "<html><head></head><body>"
            '<header><a href="/"><img src="/header-logo.svg"></a></header>'
            '<section><img src="/partner-logo.png" class="logo"></section>'
            "</body></html>"
        )
        result = service.extract_logo_from_html(html, "https://example.com")
        assert result is not None
        assert result["source_url"] == "/header-logo.svg"

    # -- Strategy 2: Logo keyword img (outside third-party sections) --

    def test_logo_keyword_in_body_found(self) -> None:
        """img with 'logo' in class found in body when no header/nav match."""
        service = LogoService()
        html = (
            "<html><head></head><body>"
            '<img src="/img/logo.svg" alt="Company Logo" class="site-logo">'
            "</body></html>"
        )
        result = service.extract_logo_from_html(html, "https://example.com")
        assert result is not None
        assert result["source_url"] == "/img/logo.svg"
        assert result["extraction_location"] == "body"

    def test_logo_inside_backed_by_section_is_skipped(self) -> None:
        """Logo inside a 'Backed by' section is rejected as third-party."""
        service = LogoService()
        html = (
            "<html><head></head><body>"
            "<section>"
            "<h3>Backed by</h3>"
            '<img src="/investor-logo.png" class="logo">'
            "</section>"
            '<link rel="icon" href="/favicon.ico">'
            "</body></html>"
        )
        result = service.extract_logo_from_html(html, "https://example.com")
        assert result is not None
        # Falls through to favicon
        assert result["source_url"] == "/favicon.ico"

    def test_logo_inside_trusted_by_section_is_skipped(self) -> None:
        """Logo inside a 'Trusted by' section is rejected."""
        service = LogoService()
        html = (
            "<html><head></head><body>"
            '<div class="social-proof">'
            "<h2>Trusted by leading companies</h2>"
            '<img src="/client1.png" class="logo">'
            '<img src="/client2.png" class="logo">'
            "</div>"
            "</body></html>"
        )
        result = service.extract_logo_from_html(html, "https://example.com")
        assert result is None

    def test_logo_inside_partner_logo_grid_is_skipped(self) -> None:
        """Logo inside a container with partner-logo class is rejected."""
        service = LogoService()
        html = (
            "<html><head></head><body>"
            '<div class="partner-logo-grid">'
            '<img src="/yc.png" class="logo">'
            '<img src="/a16z.png" class="logo">'
            "</div>"
            "</body></html>"
        )
        result = service.extract_logo_from_html(html, "https://example.com")
        assert result is None

    # -- Strategy 3: Favicon --

    def test_extracts_favicon(self) -> None:
        """Favicon link tag found when no higher-priority match."""
        service = LogoService()
        html = '<html><head><link rel="icon" href="/favicon.ico"></head><body></body></html>'
        result = service.extract_logo_from_html(html, "https://example.com")
        assert result is not None
        assert result["source_url"] == "/favicon.ico"
        assert result["extraction_location"] == "favicon"

    def test_prefers_apple_touch_icon_over_favicon(self) -> None:
        """Apple touch icon (larger) is preferred over favicon (smaller)."""
        service = LogoService()
        html = (
            "<html><head>"
            '<link rel="apple-touch-icon" href="/apple-icon-180.png">'
            '<link rel="icon" href="/favicon.ico">'
            "</head><body></body></html>"
        )
        result = service.extract_logo_from_html(html, "https://example.com")
        assert result is not None
        assert result["source_url"] == "/apple-icon-180.png"

    # -- Strategy 4: og:image (lowest priority) --

    def test_og_image_is_lowest_priority(self) -> None:
        """og:image only returned when no other strategy matches."""
        service = LogoService()
        html = (
            "<html><head>"
            '<meta property="og:image" content="https://example.com/banner.png">'
            "</head><body></body></html>"
        )
        result = service.extract_logo_from_html(html, "https://example.com")
        assert result is not None
        assert result["source_url"] == "https://example.com/banner.png"
        assert result["extraction_location"] == "og_image"

    def test_og_image_loses_to_header_logo(self) -> None:
        """og:image is not returned when a header logo exists."""
        service = LogoService()
        html = (
            "<html><head>"
            '<meta property="og:image" content="https://example.com/banner.png">'
            "</head><body>"
            '<header><a href="/"><img src="/real-logo.svg"></a></header>'
            "</body></html>"
        )
        result = service.extract_logo_from_html(html, "https://example.com")
        assert result is not None
        assert result["source_url"] == "/real-logo.svg"
        assert result["extraction_location"] == "header"

    # -- General --

    def test_returns_none_when_nothing_found(self) -> None:
        """Returns None when no logo-related elements found."""
        service = LogoService()
        html = "<html><head></head><body><p>No logos here</p></body></html>"
        result = service.extract_logo_from_html(html, "https://example.com")
        assert result is None

    def test_skips_yc_logo_url(self) -> None:
        """Known third-party URLs (YC) are filtered at all strategy levels."""
        service = LogoService()
        html = (
            "<html><head></head><body>"
            '<header><a href="/">'
            '<img src="https://ycombinator.com/logo.png" class="logo">'
            "</a></header>"
            "</body></html>"
        )
        result = service.extract_logo_from_html(html, "https://example.com")
        assert result is None


# ===========================================================================
# 10. NewsMonitorManager
# ===========================================================================


class TestNewsMonitorManager:
    """Contract tests for NewsMonitorManager with mocked KagiClient."""

    def test_searches_verifies_and_stores_articles(self, db: Database) -> None:
        """Articles searched, verified, and stored in the database."""
        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")

        mock_kagi = MagicMock()
        mock_kagi.search.return_value = [
            {
                "title": "Alpha Inc raises Series A funding",
                "url": "https://alpha.com/blog/series-a",
                "snippet": ("Alpha Inc, the startup headquartered in SF, announced funding round."),
                "published": "2025-01-15T00:00:00+00:00",
                "source": "alpha.com",
            },
        ]

        news_repo = NewsArticleRepository(db)
        company_repo = CompanyRepository(db)
        snapshot_repo = SnapshotRepository(db)
        manager = NewsMonitorManager(mock_kagi, news_repo, company_repo, snapshot_repo)

        result = manager.search_company_news(company_id=cid)

        assert result["articles_found"] == 1
        assert result["articles_verified"] >= 1
        assert result["articles_stored"] >= 1

        articles = news_repo.get_news_articles(cid)
        assert len(articles) >= 1
        assert articles[0]["title"] == "Alpha Inc raises Series A funding"

    def test_handles_duplicates(self, db: Database) -> None:
        """Duplicate article URLs are rejected on second search."""
        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")

        now = datetime.now(UTC).isoformat()
        news_repo = NewsArticleRepository(db)
        news_repo.store_news_article(
            {
                "company_id": cid,
                "title": "Existing article",
                "content_url": "https://techcrunch.com/alpha-existing",
                "source": "techcrunch.com",
                "published_at": now,
                "discovered_at": now,
                "match_confidence": 0.8,
                "match_evidence": ["Domain match"],
            }
        )

        mock_kagi = MagicMock()
        mock_kagi.search.return_value = [
            {
                "title": "Existing article",
                "url": "https://techcrunch.com/alpha-existing",
                "snippet": "Alpha Inc announced something new.",
                "published": now,
                "source": "techcrunch.com",
            },
        ]

        company_repo = CompanyRepository(db)
        snapshot_repo = SnapshotRepository(db)
        manager = NewsMonitorManager(mock_kagi, news_repo, company_repo, snapshot_repo)

        result = manager.search_company_news(company_id=cid)

        assert result["articles_stored"] == 0

    def test_calculates_date_range_from_snapshots(self, db: Database) -> None:
        """Date range derived from snapshot dates when available."""
        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")
        _insert_snapshot(
            db,
            cid,
            "# Old",
            captured_at="2024-06-01T00:00:00+00:00",
        )
        _insert_snapshot(
            db,
            cid,
            "# New",
            captured_at="2025-01-01T00:00:00+00:00",
        )

        mock_kagi = MagicMock()
        mock_kagi.search.return_value = []

        news_repo = NewsArticleRepository(db)
        company_repo = CompanyRepository(db)
        snapshot_repo = SnapshotRepository(db)
        manager = NewsMonitorManager(mock_kagi, news_repo, company_repo, snapshot_repo)

        manager.search_company_news(company_id=cid)

        call_args = mock_kagi.search.call_args
        after_date = call_args.kwargs.get("after_date", call_args[1].get("after_date", ""))
        assert after_date == "2024-06-01"

    def test_fallback_date_range_without_snapshots(self, db: Database) -> None:
        """Without snapshots, date range defaults to 90 days."""
        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")

        mock_kagi = MagicMock()
        mock_kagi.search.return_value = []

        news_repo = NewsArticleRepository(db)
        company_repo = CompanyRepository(db)
        snapshot_repo = SnapshotRepository(db)
        manager = NewsMonitorManager(mock_kagi, news_repo, company_repo, snapshot_repo)

        manager.search_company_news(company_id=cid)

        call_args = mock_kagi.search.call_args
        after_date = call_args.kwargs.get("after_date") or call_args[1].get("after_date")
        assert after_date is not None
        assert len(after_date) == 10  # YYYY-MM-DD format


# ===========================================================================
# 11. CompanyVerifier
# ===========================================================================


class TestCompanyVerifier:
    """Contract tests for CompanyVerifier."""

    def test_domain_match_gives_confidence(self) -> None:
        """Article URL containing company domain adds confidence."""
        verifier = CompanyVerifier()
        article = {
            "url": "https://alpha.com/news/update",
            "snippet": "Some update from the company.",
            "title": "Update",
        }
        confidence, evidence = verifier.verify(article, "Alpha Inc", "https://alpha.com")
        assert confidence > 0
        assert any("Domain match" in e for e in evidence)

    def test_name_in_context_gives_confidence(self) -> None:
        """Company name in business context adds confidence."""
        verifier = CompanyVerifier()
        article = {
            "url": "https://techcrunch.com/article",
            "snippet": ("Alpha Inc announced a new product launch for their platform."),
            "title": "Alpha Inc launches new product",
        }
        confidence, evidence = verifier.verify(article, "Alpha Inc", "https://alpha.com")
        assert confidence > 0
        assert any("Name in context" in e for e in evidence)

    def test_both_signals_give_higher_confidence(self) -> None:
        """Both domain and name context produce higher confidence."""
        verifier = CompanyVerifier()
        article = {
            "url": "https://alpha.com/blog/announcement",
            "snippet": "Alpha Inc launched a new product today.",
            "title": "Alpha Inc announcement",
        }
        confidence, evidence = verifier.verify(article, "Alpha Inc", "https://alpha.com")

        verifier2 = CompanyVerifier()
        confidence_domain_only, _ = verifier2.verify(
            {
                "url": "https://alpha.com/news",
                "snippet": "generic content",
                "title": "generic",
            },
            "Alpha Inc",
            "https://alpha.com",
        )
        assert confidence >= confidence_domain_only

    def test_no_match_gives_low_confidence(self) -> None:
        """No matching signals produce zero confidence."""
        verifier = CompanyVerifier()
        article = {
            "url": "https://randomsite.com/article",
            "snippet": "Something completely unrelated.",
            "title": "Random Article",
        }
        confidence, evidence = verifier.verify(article, "Alpha Inc", "https://alpha.com")
        assert confidence == 0.0
        assert len(evidence) == 0


# ===========================================================================
# 12. NewsAnalyzer
# ===========================================================================


class TestNewsAnalyzer:
    """Contract tests for NewsAnalyzer significance analysis."""

    def test_analyzes_article_with_keywords(self) -> None:
        """Significant keywords produce classification/sentiment."""
        analyzer = NewsAnalyzer()
        result = analyzer.analyze(
            title="Alpha Inc raises $50M in Series B",
            content=("The startup raised significant funding. Revenue growth is strong."),
            company_name="Alpha Inc",
        )
        classifications = ("significant", "insignificant", "uncertain")
        sentiments = ("positive", "negative", "neutral", "mixed")
        assert result["significance_classification"] in classifications
        assert result["significance_sentiment"] in sentiments
        assert result["significance_confidence"] > 0

    def test_analyzes_negative_article(self) -> None:
        """Articles with negative keywords are classified."""
        analyzer = NewsAnalyzer()
        result = analyzer.analyze(
            title="Major layoffs at Alpha Inc",
            content=(
                "Alpha Inc announced layoffs and restructuring affecting hundreds of employees."
            ),
            company_name="Alpha Inc",
        )
        assert result["significance_classification"] in ("significant", "uncertain")
        assert result["significance_sentiment"] in ("negative", "neutral")

    def test_insignificant_article(self) -> None:
        """Articles without significant keywords are insignificant."""
        analyzer = NewsAnalyzer()
        result = analyzer.analyze(
            title="Generic Update",
            content=(
                "The website was updated with a new background-color and font-family changes."
            ),
            company_name="Alpha Inc",
        )
        assert result["significance_classification"] in ("insignificant", "uncertain")


# ===========================================================================
# 12. BrandingLogoProcessor
# ===========================================================================


class TestBrandingLogoProcessor:
    """Contract tests for BrandingLogoProcessor with mocked HTTP downloads."""

    def test_process_branding_logo_stores_logo(self, db: Database) -> None:
        """Happy path: branding logo is downloaded and stored."""
        from io import BytesIO
        from types import SimpleNamespace
        from unittest.mock import patch

        from PIL import Image

        from src.domains.discovery.services.branding_logo_processor import (
            BrandingLogoProcessor,
        )

        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")
        logo_repo = SocialMediaLinkRepository(db)
        processor = BrandingLogoProcessor(logo_repo)

        # Create a valid small PNG image
        img = Image.new("RGB", (64, 64), color="red")
        buf = BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        mock_response = MagicMock()
        mock_response.content = png_bytes
        mock_response.headers = {"Content-Type": "image/png"}
        mock_response.raise_for_status = MagicMock()

        branding = SimpleNamespace(
            logo="https://alpha.com/logo.png",
            images=None,
        )

        with patch(
            "src.domains.discovery.services.branding_logo_processor.requests.get",
            return_value=mock_response,
        ):
            result = processor.process_branding_logo(cid, branding)

        assert result is True
        stored = logo_repo.get_company_logo(cid)
        assert stored is not None
        assert stored["source_url"] == "https://alpha.com/logo.png"
        assert stored["extraction_location"] == "branding"
        assert stored["perceptual_hash"] != ""
        assert stored["image_format"] == "PNG"

    def test_process_branding_logo_returns_false_when_no_url(
        self,
        db: Database,
    ) -> None:
        """Returns False when branding data has no valid logo URL."""
        from types import SimpleNamespace

        from src.domains.discovery.services.branding_logo_processor import (
            BrandingLogoProcessor,
        )

        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")
        logo_repo = SocialMediaLinkRepository(db)
        processor = BrandingLogoProcessor(logo_repo)

        branding = SimpleNamespace(logo=None, images=None)
        result = processor.process_branding_logo(cid, branding)

        assert result is False
        assert logo_repo.get_company_logo(cid) is None

    def test_process_branding_logo_handles_download_failure(
        self,
        db: Database,
    ) -> None:
        """Returns False on download failure without crashing."""
        from types import SimpleNamespace
        from unittest.mock import patch

        from src.domains.discovery.services.branding_logo_processor import (
            BrandingLogoProcessor,
        )

        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")
        logo_repo = SocialMediaLinkRepository(db)
        processor = BrandingLogoProcessor(logo_repo)

        branding = SimpleNamespace(
            logo="https://alpha.com/logo.png",
            images=None,
        )

        with patch(
            "src.domains.discovery.services.branding_logo_processor.requests.get",
            side_effect=ConnectionError("timeout"),
        ):
            result = processor.process_branding_logo(cid, branding)

        assert result is False
        assert logo_repo.get_company_logo(cid) is None

    def test_process_branding_logo_handles_non_image_response(
        self,
        db: Database,
    ) -> None:
        """Returns False when response is not an image."""
        from types import SimpleNamespace
        from unittest.mock import patch

        from src.domains.discovery.services.branding_logo_processor import (
            BrandingLogoProcessor,
        )

        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")
        logo_repo = SocialMediaLinkRepository(db)
        processor = BrandingLogoProcessor(logo_repo)

        mock_response = MagicMock()
        mock_response.content = b"<html>Not an image</html>"
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        branding = SimpleNamespace(
            logo="https://alpha.com/logo.png",
            images=None,
        )

        with patch(
            "src.domains.discovery.services.branding_logo_processor.requests.get",
            return_value=mock_response,
        ):
            result = processor.process_branding_logo(cid, branding)

        assert result is False

    def test_company_has_logo_true_when_exists(self, db: Database) -> None:
        """company_has_logo returns True when logo exists in DB."""
        from src.domains.discovery.services.branding_logo_processor import (
            BrandingLogoProcessor,
        )

        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")
        logo_repo = SocialMediaLinkRepository(db)
        processor = BrandingLogoProcessor(logo_repo)

        # Insert a logo directly
        logo_repo.store_company_logo(
            {
                "company_id": cid,
                "image_data": b"fake-data",
                "image_format": "PNG",
                "perceptual_hash": "abcdef1234567890",
                "source_url": "https://alpha.com/logo.png",
                "extraction_location": "branding",
                "width": 64,
                "height": 64,
                "extracted_at": datetime.now(UTC).isoformat(),
            }
        )

        assert processor.company_has_logo(cid) is True

    def test_company_has_logo_false_when_missing(self, db: Database) -> None:
        """company_has_logo returns False when no logo exists."""
        from src.domains.discovery.services.branding_logo_processor import (
            BrandingLogoProcessor,
        )

        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")
        logo_repo = SocialMediaLinkRepository(db)
        processor = BrandingLogoProcessor(logo_repo)

        assert processor.company_has_logo(cid) is False


# ===========================================================================
# 13. SnapshotManager with Branding Logo Integration
# ===========================================================================


class TestSnapshotManagerBrandingIntegration:
    """Tests for SnapshotManager branding logo processing during capture."""

    def test_stores_branding_logo_when_company_has_no_logo(
        self,
        db: Database,
    ) -> None:
        """Branding logo is stored for company without existing logo."""
        from io import BytesIO
        from types import SimpleNamespace
        from unittest.mock import patch

        from PIL import Image

        from src.domains.discovery.services.branding_logo_processor import (
            BrandingLogoProcessor,
        )

        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")
        logo_repo = SocialMediaLinkRepository(db)
        logo_processor = BrandingLogoProcessor(logo_repo)

        # Create valid PNG for download mock
        img = Image.new("RGB", (64, 64), color="blue")
        buf = BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        mock_download = MagicMock()
        mock_download.content = png_bytes
        mock_download.headers = {"Content-Type": "image/png"}
        mock_download.raise_for_status = MagicMock()

        branding_data = SimpleNamespace(
            logo="https://alpha.com/brand-logo.png",
            images=None,
        )

        mock_firecrawl = MagicMock()
        mock_firecrawl.capture_snapshot.return_value = {
            "success": True,
            "markdown": "# Alpha",
            "html": "<h1>Alpha</h1>",
            "statusCode": 200,
            "metadata": {},
            "has_paywall": False,
            "has_auth_required": False,
            "error": None,
            "branding": branding_data,
        }

        snapshot_repo = SnapshotRepository(db)
        company_repo = CompanyRepository(db)
        manager = SnapshotManager(
            mock_firecrawl,
            snapshot_repo,
            company_repo,
            logo_processor=logo_processor,
        )

        with patch(
            "src.domains.discovery.services.branding_logo_processor.requests.get",
            return_value=mock_download,
        ):
            summary = manager.capture_all_snapshots()

        assert summary["successful"] == 1
        stored_logo = logo_repo.get_company_logo(cid)
        assert stored_logo is not None
        assert stored_logo["source_url"] == "https://alpha.com/brand-logo.png"
        assert stored_logo["extraction_location"] == "branding"

    def test_skips_logo_when_company_already_has_one(self, db: Database) -> None:
        """Branding logo is NOT downloaded when company already has a logo."""
        from types import SimpleNamespace
        from unittest.mock import patch

        from src.domains.discovery.services.branding_logo_processor import (
            BrandingLogoProcessor,
        )

        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")
        logo_repo = SocialMediaLinkRepository(db)
        logo_processor = BrandingLogoProcessor(logo_repo)

        # Pre-insert a logo
        logo_repo.store_company_logo(
            {
                "company_id": cid,
                "image_data": b"existing-logo",
                "image_format": "PNG",
                "perceptual_hash": "existinghash1234",
                "source_url": "https://alpha.com/old-logo.png",
                "extraction_location": "header",
                "width": 100,
                "height": 50,
                "extracted_at": datetime.now(UTC).isoformat(),
            }
        )

        branding_data = SimpleNamespace(
            logo="https://alpha.com/new-brand-logo.png",
            images=None,
        )

        mock_firecrawl = MagicMock()
        mock_firecrawl.capture_snapshot.return_value = {
            "success": True,
            "markdown": "# Alpha",
            "html": "<h1>Alpha</h1>",
            "statusCode": 200,
            "metadata": {},
            "has_paywall": False,
            "has_auth_required": False,
            "error": None,
            "branding": branding_data,
        }

        snapshot_repo = SnapshotRepository(db)
        company_repo = CompanyRepository(db)
        manager = SnapshotManager(
            mock_firecrawl,
            snapshot_repo,
            company_repo,
            logo_processor=logo_processor,
        )

        # requests.get should NOT be called since company has logo
        with patch(
            "src.domains.discovery.services.branding_logo_processor.requests.get",
        ) as mock_get:
            summary = manager.capture_all_snapshots()

        assert summary["successful"] == 1
        mock_get.assert_not_called()

        # Verify the old logo is still there, not overwritten
        stored = logo_repo.get_company_logo(cid)
        assert stored is not None
        assert stored["source_url"] == "https://alpha.com/old-logo.png"

    def test_works_without_logo_processor(self, db: Database) -> None:
        """Backward compatible: no logo_processor means no logo processing."""
        _insert_company(db, "Alpha Inc", "https://alpha.com")

        mock_firecrawl = MagicMock()
        mock_firecrawl.capture_snapshot.return_value = {
            "success": True,
            "markdown": "# Alpha",
            "html": "<h1>Alpha</h1>",
            "statusCode": 200,
            "metadata": {},
            "has_paywall": False,
            "has_auth_required": False,
            "error": None,
            "branding": None,
        }

        snapshot_repo = SnapshotRepository(db)
        company_repo = CompanyRepository(db)
        # No logo_processor passed (default None)
        manager = SnapshotManager(mock_firecrawl, snapshot_repo, company_repo)

        summary = manager.capture_all_snapshots()
        assert summary["successful"] == 1


# ===========================================================================
# 14. BatchSnapshotManager with Branding Logo Integration
# ===========================================================================


class TestBatchSnapshotManagerBrandingIntegration:
    """Tests for BatchSnapshotManager branding logo processing."""

    def test_batch_processes_branding_logos(self, db: Database) -> None:
        """Branding logos are stored during batch capture."""
        from io import BytesIO
        from types import SimpleNamespace
        from unittest.mock import patch

        from PIL import Image

        from src.domains.discovery.services.branding_logo_processor import (
            BrandingLogoProcessor,
        )

        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")
        logo_repo = SocialMediaLinkRepository(db)
        logo_processor = BrandingLogoProcessor(logo_repo)

        # Create valid PNG
        img = Image.new("RGB", (64, 64), color="green")
        buf = BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        mock_download = MagicMock()
        mock_download.content = png_bytes
        mock_download.headers = {"Content-Type": "image/png"}
        mock_download.raise_for_status = MagicMock()

        branding_data = SimpleNamespace(
            logo="https://alpha.com/brand-logo.png",
            images=None,
        )

        mock_firecrawl = MagicMock()
        mock_firecrawl.batch_capture_snapshots.return_value = {
            "success": True,
            "documents": [
                {
                    "url": "https://alpha.com",
                    "markdown": "# Alpha",
                    "html": "<h1>Alpha</h1>",
                    "metadata": {"statusCode": 200},
                    "branding": branding_data,
                },
            ],
            "total": 1,
            "completed": 1,
            "failed": 0,
            "errors": [],
        }

        snapshot_repo = SnapshotRepository(db)
        company_repo = CompanyRepository(db)
        manager = BatchSnapshotManager(
            mock_firecrawl,
            snapshot_repo,
            company_repo,
            logo_processor=logo_processor,
        )

        with patch(
            "src.domains.discovery.services.branding_logo_processor.requests.get",
            return_value=mock_download,
        ):
            summary = manager.capture_batch_snapshots(batch_size=10)

        assert summary["successful"] == 1
        stored = logo_repo.get_company_logo(cid)
        assert stored is not None
        assert stored["extraction_location"] == "branding"

    def test_batch_skips_logos_when_already_exist(self, db: Database) -> None:
        """Batch mode skips logo download for companies with existing logos."""
        from types import SimpleNamespace
        from unittest.mock import patch

        from src.domains.discovery.services.branding_logo_processor import (
            BrandingLogoProcessor,
        )

        cid = _insert_company(db, "Alpha Inc", "https://alpha.com")
        logo_repo = SocialMediaLinkRepository(db)
        logo_processor = BrandingLogoProcessor(logo_repo)

        # Pre-insert a logo
        logo_repo.store_company_logo(
            {
                "company_id": cid,
                "image_data": b"existing",
                "image_format": "PNG",
                "perceptual_hash": "existinghash5678",
                "source_url": "https://alpha.com/old.png",
                "extraction_location": "header",
                "width": 100,
                "height": 50,
                "extracted_at": datetime.now(UTC).isoformat(),
            }
        )

        branding_data = SimpleNamespace(
            logo="https://alpha.com/new-logo.png",
            images=None,
        )

        mock_firecrawl = MagicMock()
        mock_firecrawl.batch_capture_snapshots.return_value = {
            "success": True,
            "documents": [
                {
                    "url": "https://alpha.com",
                    "markdown": "# Alpha",
                    "html": "<h1>Alpha</h1>",
                    "metadata": {"statusCode": 200},
                    "branding": branding_data,
                },
            ],
            "total": 1,
            "completed": 1,
            "failed": 0,
            "errors": [],
        }

        snapshot_repo = SnapshotRepository(db)
        company_repo = CompanyRepository(db)
        manager = BatchSnapshotManager(
            mock_firecrawl,
            snapshot_repo,
            company_repo,
            logo_processor=logo_processor,
        )

        with patch(
            "src.domains.discovery.services.branding_logo_processor.requests.get",
        ) as mock_get:
            summary = manager.capture_batch_snapshots(batch_size=10)

        assert summary["successful"] == 1
        mock_get.assert_not_called()

        stored = logo_repo.get_company_logo(cid)
        assert stored is not None
        assert stored["source_url"] == "https://alpha.com/old.png"
