"""Integration tests for the CDP-based leadership extraction workflow.

Tests the full pipeline with mocked external services (Chrome/LLM).
Uses real database and all internal components.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.domains.discovery.repositories.social_media_link_repository import (
    SocialMediaLinkRepository,
)
from src.domains.leadership.repositories.leadership_repository import (
    LeadershipRepository,
)
from src.domains.leadership.repositories.linkedin_snapshot_repository import (
    LinkedInSnapshotRepository,
)
from src.domains.leadership.services.leadership_manager import LeadershipManager
from src.models.company_leadership import LeadershipDiscoveryMethod
from src.repositories.company_repository import CompanyRepository
from src.services.database import Database


@pytest.fixture
def full_db(tmp_path: Any) -> tuple[Database, int]:
    """Set up a database with company + LinkedIn company link."""
    db = Database(db_path=str(tmp_path / "test.db"))
    db.init_db()
    now = datetime.now(UTC).isoformat()

    cursor = db.execute(
        """INSERT INTO companies
           (name, homepage_url, source_sheet, flagged_for_review, created_at, updated_at)
           VALUES (?, ?, ?, 0, ?, ?)""",
        ("Acme Corp", "https://acmecorp.com", "Online Presence", now, now),
    )
    company_id = cursor.lastrowid

    db.execute(
        """INSERT INTO social_media_links
           (company_id, platform, profile_url, account_type,
            discovery_method, verification_status, discovered_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            company_id,
            "linkedin",
            "https://www.linkedin.com/company/acmecorp",
            "company",
            "homepage_scrape",
            "unverified",
            now,
        ),
    )
    db.connection.commit()
    return db, company_id


class TestCDPLeadershipExtractionWorkflow:
    """Test the full extraction -> storage -> change detection pipeline."""

    def test_first_extraction_stores_leaders(self, full_db: tuple[Database, int]) -> None:
        db, company_id = full_db
        operator = "test"

        leadership_repo = LeadershipRepository(db, operator)
        social_repo = SocialMediaLinkRepository(db, operator)
        company_repo = CompanyRepository(db, operator)
        snapshot_repo = LinkedInSnapshotRepository(db, operator)

        mock_browser = MagicMock()
        mock_browser.extract_people.return_value = [
            {
                "name": "Alice CEO",
                "title": "CEO",
                "profile_url": "https://www.linkedin.com/in/aliceceo",
            },
            {
                "name": "Bob CTO",
                "title": "CTO",
                "profile_url": "https://www.linkedin.com/in/bobcto",
            },
        ]
        mock_browser.get_page_html.return_value = "<html>people</html>"
        mock_browser.capture_people_screenshots.return_value = []
        mock_browser.delay_between_pages.return_value = None
        mock_search = MagicMock()

        manager = LeadershipManager(
            cdp_browser=mock_browser,
            leadership_search=mock_search,
            leadership_repo=leadership_repo,
            social_link_repo=social_repo,
            company_repo=company_repo,
            snapshot_repo=snapshot_repo,
        )

        result = manager.extract_company_leadership(company_id)

        assert result["leaders_found"] == 2
        assert result["method_used"] == "cdp_scrape"

        # Verify stored in DB
        leaders = leadership_repo.get_current_leadership(company_id)
        assert len(leaders) == 2

    def test_second_extraction_detects_departure(self, full_db: tuple[Database, int]) -> None:
        db, company_id = full_db
        operator = "test"
        now = datetime.now(UTC).isoformat()

        leadership_repo = LeadershipRepository(db, operator)
        social_repo = SocialMediaLinkRepository(db, operator)
        company_repo = CompanyRepository(db, operator)
        snapshot_repo = LinkedInSnapshotRepository(db, operator)

        # Pre-populate: Alice was CEO
        leadership_repo.store_leadership(
            {
                "company_id": company_id,
                "person_name": "Alice CEO",
                "title": "CEO",
                "linkedin_profile_url": "https://www.linkedin.com/in/aliceceo",
                "discovery_method": "cdp_scrape",
                "confidence": 0.8,
                "is_current": True,
                "discovered_at": now,
                "last_verified_at": now,
            }
        )

        # Now extraction only finds Bob (Alice is gone)
        mock_browser = MagicMock()
        mock_browser.extract_people.return_value = [
            {
                "name": "Bob CTO",
                "title": "CTO",
                "profile_url": "https://www.linkedin.com/in/bobcto",
            },
        ]
        mock_browser.get_page_html.return_value = "<html>people</html>"
        mock_browser.capture_people_screenshots.return_value = []
        mock_browser.delay_between_pages.return_value = None
        mock_search = MagicMock()

        manager = LeadershipManager(
            cdp_browser=mock_browser,
            leadership_search=mock_search,
            leadership_repo=leadership_repo,
            social_link_repo=social_repo,
            company_repo=company_repo,
            snapshot_repo=snapshot_repo,
        )

        result = manager.extract_company_leadership(company_id)

        # Should detect CEO departure
        changes = result.get("leadership_changes", [])
        assert len(changes) >= 1
        departure = [c for c in changes if "departure" in c.get("change_type", "")]
        assert len(departure) == 1
        assert departure[0]["person_name"] == "Alice CEO"
        assert result["change_significance"] == "significant"

    def test_kagi_fallback_on_cdp_failure(self, full_db: tuple[Database, int]) -> None:
        db, company_id = full_db
        operator = "test"

        leadership_repo = LeadershipRepository(db, operator)
        social_repo = SocialMediaLinkRepository(db, operator)
        company_repo = CompanyRepository(db, operator)

        from src.domains.leadership.services.cdp_browser import CDPBlockedError

        mock_browser = MagicMock()
        mock_browser.extract_people.side_effect = CDPBlockedError("captcha")
        mock_browser.delay_between_pages.return_value = None

        mock_search = MagicMock()
        mock_search.search_leadership.return_value = [
            {"name": "Alice", "title": "CEO", "profile_url": "https://www.linkedin.com/in/alice"},
        ]

        manager = LeadershipManager(
            cdp_browser=mock_browser,
            leadership_search=mock_search,
            leadership_repo=leadership_repo,
            social_link_repo=social_repo,
            company_repo=company_repo,
        )

        result = manager.extract_company_leadership(company_id)

        assert result["method_used"] == "kagi_search"
        assert result["leaders_found"] == 1
        assert "CDP blocked" in result["errors"][0]


class TestCDPDiscoveryMethodEnum:
    def test_cdp_scrape_method(self) -> None:
        assert LeadershipDiscoveryMethod.CDP_SCRAPE == "cdp_scrape"

    def test_playwright_still_exists_for_compat(self) -> None:
        assert LeadershipDiscoveryMethod.PLAYWRIGHT_SCRAPE == "playwright_scrape"


class TestLinkedInSnapshotWorkflow:
    """Test snapshot storage during leadership extraction."""

    def test_company_snapshot_stored_on_extraction(self, full_db: tuple[Database, int]) -> None:
        db, company_id = full_db
        operator = "test"

        leadership_repo = LeadershipRepository(db, operator)
        social_repo = SocialMediaLinkRepository(db, operator)
        company_repo = CompanyRepository(db, operator)
        snapshot_repo = LinkedInSnapshotRepository(db, operator)

        mock_browser = MagicMock()
        mock_browser.extract_people.return_value = [
            {"name": "Jane", "title": "CEO", "profile_url": "https://www.linkedin.com/in/jane"},
        ]
        mock_browser.get_page_html.return_value = "<html>people page content</html>"
        mock_browser.capture_people_screenshots.return_value = []
        mock_browser.delay_between_pages.return_value = None
        mock_search = MagicMock()

        manager = LeadershipManager(
            cdp_browser=mock_browser,
            leadership_search=mock_search,
            leadership_repo=leadership_repo,
            social_link_repo=social_repo,
            company_repo=company_repo,
            snapshot_repo=snapshot_repo,
        )

        manager.extract_company_leadership(company_id)

        # Verify snapshot was stored
        snapshots = snapshot_repo.get_snapshots_for_company(company_id)
        assert len(snapshots) == 1
        assert snapshots[0]["url_type"] == "company"
        assert snapshots[0]["content_html"] == "<html>people page content</html>"
        assert snapshots[0]["content_checksum"] is not None
