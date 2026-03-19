"""Integration tests for CEO LinkedIn discovery workflow.

Full end-to-end tests with real temp database, mocked Kagi search.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.domains.discovery.repositories.social_media_link_repository import (
    SocialMediaLinkRepository,
)
from src.domains.leadership.repositories.leadership_mention_repository import (
    LeadershipMentionRepository,
)
from src.domains.leadership.repositories.leadership_repository import (
    LeadershipRepository,
)
from src.domains.leadership.services.ceo_linkedin_discovery import (
    CeoLinkedinDiscovery,
)
from src.domains.monitoring.repositories.snapshot_repository import (
    SnapshotRepository,
)
from src.repositories.company_repository import CompanyRepository
from src.services.database import Database


@pytest.fixture
def tmp_db(tmp_path: Any) -> Database:
    """Create a temp database with full schema."""
    db = Database(db_path=str(tmp_path / "test.db"))
    db.init_db()
    return db


def _insert_company(db: Database, name: str, homepage_url: str) -> int:
    """Insert a test company and return its ID."""
    now = datetime.now(UTC).isoformat()
    cursor = db.execute(
        """INSERT INTO companies (name, homepage_url, source_sheet, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (name, homepage_url, "Sheet1", now, now),
    )
    db.connection.commit()
    return cursor.lastrowid or 0


def _insert_snapshot(
    db: Database,
    company_id: int,
    content_markdown: str,
    url: str = "https://example.com",
) -> int:
    """Insert a snapshot and return its ID."""
    checksum = hashlib.md5(content_markdown.encode("utf-8")).hexdigest()
    now = datetime.now(UTC).isoformat()
    cursor = db.execute(
        """INSERT INTO snapshots (company_id, url, content_markdown,
           status_code, captured_at, content_checksum)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (company_id, url, content_markdown, 200, now, checksum),
    )
    db.connection.commit()
    return cursor.lastrowid or 0


def _build_ceo_discovery(
    db: Database,
    kagi_results: list[dict[str, str]] | None = None,
    kagi_error: Exception | None = None,
) -> CeoLinkedinDiscovery:
    """Build a CeoLinkedinDiscovery with mocked search."""
    mock_search = MagicMock()
    if kagi_error:
        mock_search.search_ceo_linkedin.side_effect = kagi_error
    else:
        mock_search.search_ceo_linkedin.return_value = kagi_results or []

    return CeoLinkedinDiscovery(
        leadership_search=mock_search,
        leadership_repo=LeadershipRepository(db, "test-user"),
        leadership_mention_repo=LeadershipMentionRepository(db, "test-user"),
        snapshot_repo=SnapshotRepository(db, "test-user"),
        social_link_repo=SocialMediaLinkRepository(db, "test-user"),
        company_repo=CompanyRepository(db, "test-user"),
    )


class TestCeoLinkedinDiscoveryWorkflow:
    """Full workflow tests for CEO LinkedIn discovery."""

    def test_full_flow_snapshot_to_kagi_to_store(self, tmp_db: Database) -> None:
        """Full pipeline: company with snapshot -> extract mentions -> Kagi search -> store."""
        company_id = _insert_company(tmp_db, "Acme Corp", "https://acme.com")
        _insert_snapshot(
            tmp_db,
            company_id,
            "# About Us\n\nOur CEO Sarah Chen leads the team.",
            url="https://acme.com",
        )

        discovery = _build_ceo_discovery(
            tmp_db,
            kagi_results=[
                {
                    "name": "Sarah Chen",
                    "title": "CEO",
                    "profile_url": "https://linkedin.com/in/sarah-chen",
                },
            ],
        )

        result = discovery.discover_for_company(company_id)

        assert result["company_name"] == "Acme Corp"
        assert result["profiles_found"] == 1
        assert result["ceo_name_used"] == "Sarah Chen"

        # Verify leadership mention stored
        mention_repo = LeadershipMentionRepository(tmp_db, "test-user")
        mentions = mention_repo.get_mentions_for_company(company_id)
        assert len(mentions) >= 1
        assert any(m["person_name"] == "Sarah Chen" for m in mentions)

        # Verify company_leadership stored
        leadership_repo = LeadershipRepository(tmp_db, "test-user")
        leaders = leadership_repo.get_leadership_for_company(company_id)
        assert len(leaders) == 1
        assert leaders[0]["person_name"] == "Sarah Chen"
        assert leaders[0]["discovery_method"] == "kagi_ceo_search"

        # Verify social_media_links stored
        social_repo = SocialMediaLinkRepository(tmp_db, "test-user")
        links = social_repo.get_links_for_company(company_id)
        linkedin_links = [lk for lk in links if lk["platform"] == "linkedin"]
        assert len(linkedin_links) == 1

    def test_cli_ceo_name_overrides_db_mentions(self, tmp_db: Database) -> None:
        """CLI ceo_name parameter takes priority over DB mentions."""
        company_id = _insert_company(tmp_db, "TechStart", "https://techstart.io")
        _insert_snapshot(
            tmp_db,
            company_id,
            "Our CEO Alice Brown leads innovation.",
        )

        mock_search = MagicMock()
        mock_search.search_ceo_linkedin.return_value = []

        discovery = CeoLinkedinDiscovery(
            leadership_search=mock_search,
            leadership_repo=LeadershipRepository(tmp_db, "test-user"),
            leadership_mention_repo=LeadershipMentionRepository(tmp_db, "test-user"),
            snapshot_repo=SnapshotRepository(tmp_db, "test-user"),
            social_link_repo=SocialMediaLinkRepository(tmp_db, "test-user"),
            company_repo=CompanyRepository(tmp_db, "test-user"),
        )

        result = discovery.discover_for_company(company_id, ceo_name="Override Name")
        assert result["ceo_name_used"] == "Override Name"

        # Verify Kagi was called with the overridden name
        mock_search.search_ceo_linkedin.assert_called_once_with("TechStart", "Override Name")

    def test_dedup_across_homepage_scrape_and_kagi(self, tmp_db: Database) -> None:
        """Profile already in social_media_links from homepage scrape is not duplicated."""
        company_id = _insert_company(tmp_db, "DedupCo", "https://dedup.co")

        # Pre-existing LinkedIn link from homepage discovery.
        # URL must match the normalized form (normalize_social_url removes www.)
        now = datetime.now(UTC).isoformat()
        tmp_db.execute(
            """INSERT INTO social_media_links
               (company_id, platform, profile_url, discovery_method,
                verification_status, discovered_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                company_id,
                "linkedin",
                "https://linkedin.com/in/bob-ceo",
                "page_footer",
                "unverified",
                now,
            ),
        )
        tmp_db.connection.commit()

        discovery = _build_ceo_discovery(
            tmp_db,
            kagi_results=[
                {
                    "name": "Bob CEO",
                    "title": "CEO",
                    "profile_url": "https://linkedin.com/in/bob-ceo",
                },
            ],
        )

        result = discovery.discover_for_company(company_id)

        # Profile found in Kagi but already existed in social_media_links
        assert result["already_existed"] == 1

        # Should still be only 1 LinkedIn link, not 2
        social_repo = SocialMediaLinkRepository(tmp_db, "test-user")
        links = social_repo.get_links_for_company(company_id)
        linkedin_links = [lk for lk in links if lk["platform"] == "linkedin"]
        assert len(linkedin_links) == 1

    def test_multiple_founders_both_discovered(self, tmp_db: Database) -> None:
        """Multiple co-founders from snapshot and Kagi results are all stored."""
        company_id = _insert_company(tmp_db, "FounderCo", "https://founder.co")
        _insert_snapshot(
            tmp_db,
            company_id,
            "Co-founded by Alice Jones and Bob Smith in 2019.",
        )

        discovery = _build_ceo_discovery(
            tmp_db,
            kagi_results=[
                {
                    "name": "Alice Jones",
                    "title": "Co-Founder",
                    "profile_url": "https://linkedin.com/in/alice-jones",
                },
                {
                    "name": "Bob Smith",
                    "title": "Co-Founder",
                    "profile_url": "https://linkedin.com/in/bob-smith",
                },
            ],
        )

        result = discovery.discover_for_company(company_id)
        assert result["profiles_found"] == 2

        # Both stored in company_leadership
        leadership_repo = LeadershipRepository(tmp_db, "test-user")
        leaders = leadership_repo.get_leadership_for_company(company_id)
        names = {leader["person_name"] for leader in leaders}
        assert "Alice Jones" in names
        assert "Bob Smith" in names

    def test_rerun_updates_last_verified_at(self, tmp_db: Database) -> None:
        """Re-running discovery updates last_verified_at for existing records."""
        company_id = _insert_company(tmp_db, "RerunCo", "https://rerun.co")

        kagi_results = [
            {
                "name": "Jane CEO",
                "title": "CEO",
                "profile_url": "https://linkedin.com/in/jane-ceo",
            },
        ]

        # First run: creates record
        discovery1 = _build_ceo_discovery(tmp_db, kagi_results=kagi_results)
        result1 = discovery1.discover_for_company(company_id)
        assert result1["profiles_found"] == 1
        assert result1["reverified"] == 0

        # Second run: reverifies
        discovery2 = _build_ceo_discovery(tmp_db, kagi_results=kagi_results)
        result2 = discovery2.discover_for_company(company_id)
        assert result2["profiles_found"] == 0
        assert result2["reverified"] == 1

        # Only 1 record in DB (not duplicated)
        leadership_repo = LeadershipRepository(tmp_db, "test-user")
        leaders = leadership_repo.get_leadership_for_company(company_id)
        assert len(leaders) == 1

    def test_company_with_no_snapshot_still_searches_kagi(self, tmp_db: Database) -> None:
        """Company without a snapshot still searches Kagi (just without person_name)."""
        company_id = _insert_company(tmp_db, "NoSnapCo", "https://nosnap.co")

        mock_search = MagicMock()
        mock_search.search_ceo_linkedin.return_value = [
            {
                "name": "Found Person",
                "title": "CEO",
                "profile_url": "https://linkedin.com/in/found-person",
            },
        ]

        discovery = CeoLinkedinDiscovery(
            leadership_search=mock_search,
            leadership_repo=LeadershipRepository(tmp_db, "test-user"),
            leadership_mention_repo=LeadershipMentionRepository(tmp_db, "test-user"),
            snapshot_repo=SnapshotRepository(tmp_db, "test-user"),
            social_link_repo=SocialMediaLinkRepository(tmp_db, "test-user"),
            company_repo=CompanyRepository(tmp_db, "test-user"),
        )

        result = discovery.discover_for_company(company_id)
        assert result["profiles_found"] == 1
        assert result["ceo_name_used"] is None

        # Kagi was called without a person name
        mock_search.search_ceo_linkedin.assert_called_once_with("NoSnapCo", None)

    def test_dry_run_produces_output_without_writes(self, tmp_db: Database) -> None:
        """dry_run=True shows what would be done without writing to DB."""
        company_id = _insert_company(tmp_db, "DryRunCo", "https://dryrun.co")
        _insert_snapshot(
            tmp_db,
            company_id,
            "CEO: John Smith leads our company.",
        )

        discovery = _build_ceo_discovery(
            tmp_db,
            kagi_results=[
                {
                    "name": "John Smith",
                    "title": "CEO",
                    "profile_url": "https://linkedin.com/in/john-smith",
                },
            ],
        )

        result = discovery.discover_for_company(company_id, dry_run=True)
        assert result["profiles_found"] == 1

        # No records should be written to DB
        leadership_repo = LeadershipRepository(tmp_db, "test-user")
        leaders = leadership_repo.get_leadership_for_company(company_id)
        assert len(leaders) == 0

        mention_repo = LeadershipMentionRepository(tmp_db, "test-user")
        mentions = mention_repo.get_mentions_for_company(company_id)
        assert len(mentions) == 0

        social_repo = SocialMediaLinkRepository(tmp_db, "test-user")
        links = social_repo.get_links_for_company(company_id)
        assert len(links) == 0


class TestCeoLinkedinBatchDiscovery:
    """Batch processing tests."""

    def test_batch_processes_multiple_companies(self, tmp_db: Database) -> None:
        """Batch discovery processes all companies with homepage URLs."""
        for i in range(3):
            _insert_company(tmp_db, f"BatchCo{i}", f"https://batch{i}.com")

        discovery = _build_ceo_discovery(
            tmp_db,
            kagi_results=[
                {
                    "name": "Some CEO",
                    "title": "CEO",
                    "profile_url": "https://linkedin.com/in/ceo-generic",
                },
            ],
        )

        result = discovery.discover_all(limit=3, max_workers=1)
        assert result["processed"] == 3
        assert result["successful"] == 3

    def test_batch_with_kagi_error_continues(self, tmp_db: Database) -> None:
        """Kagi errors for individual companies don't abort the batch."""
        _insert_company(tmp_db, "ErrorCo", "https://error.co")
        _insert_company(tmp_db, "OkCo", "https://ok.co")

        # Build with error - all companies will get the same error
        # but errors are caught per-company
        discovery = _build_ceo_discovery(
            tmp_db,
            kagi_error=ConnectionError("Kagi unavailable"),
        )

        result = discovery.discover_all(limit=2, max_workers=1)
        # Both processed, both have errors but neither crashed
        assert result["processed"] == 2


class TestLeadershipMentionsTable:
    """Database schema tests for the leadership_mentions table."""

    def test_table_created_on_init(self, tmp_db: Database) -> None:
        """leadership_mentions table should exist after init_db."""
        rows = tmp_db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='leadership_mentions'"
        )
        assert len(rows) == 1

    def test_foreign_key_cascade(self, tmp_db: Database) -> None:
        """Deleting company should cascade to leadership_mentions records."""
        company_id = _insert_company(tmp_db, "CascadeCo", "https://cascade.co")

        now = datetime.now(UTC).isoformat()
        tmp_db.execute(
            """INSERT INTO leadership_mentions
               (company_id, person_name, title_context, source, confidence, extracted_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (company_id, "Test Person", "CEO", "homepage_snapshot", 0.5, now),
        )
        tmp_db.connection.commit()

        # Delete the company
        tmp_db.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        tmp_db.connection.commit()

        # Mentions should be gone
        rows = tmp_db.fetchall(
            "SELECT * FROM leadership_mentions WHERE company_id = ?",
            (company_id,),
        )
        assert len(rows) == 0
