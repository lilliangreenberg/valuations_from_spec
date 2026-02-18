"""Integration tests for leadership extraction workflow.

Full end-to-end tests with real temp database, mocked external APIs.
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
from src.domains.leadership.services.leadership_manager import LeadershipManager
from src.domains.leadership.services.linkedin_browser import LinkedInBlockedError
from src.repositories.company_repository import CompanyRepository
from src.services.database import Database


@pytest.fixture
def tmp_db(tmp_path: Any) -> Database:
    """Create a temp database with full schema."""
    db = Database(db_path=str(tmp_path / "test.db"))
    db.init_db()
    return db


@pytest.fixture
def company_id(tmp_db: Database) -> int:
    """Insert a test company and return its ID."""
    now = datetime.now(UTC).isoformat()
    cursor = tmp_db.execute(
        """INSERT INTO companies (name, homepage_url, source_sheet, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("IntegrationCo", "https://integration.co", "Sheet1", now, now),
    )
    tmp_db.connection.commit()
    return cursor.lastrowid or 0


@pytest.fixture
def company_with_linkedin(tmp_db: Database, company_id: int) -> int:
    """Add a LinkedIn company URL for the test company."""
    now = datetime.now(UTC).isoformat()
    tmp_db.execute(
        """INSERT INTO social_media_links
           (company_id, platform, profile_url, discovery_method,
            verification_status, discovered_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            company_id,
            "linkedin",
            "https://www.linkedin.com/company/integrationco",
            "page_footer",
            "unverified",
            now,
        ),
    )
    tmp_db.connection.commit()
    return company_id


def _build_manager(
    tmp_db: Database,
    browser_people: list[dict[str, str]] | None = None,
    browser_error: Exception | None = None,
    kagi_results: list[dict[str, str]] | None = None,
) -> LeadershipManager:
    """Build a LeadershipManager with mocked browser and search."""
    mock_browser = MagicMock()
    if browser_error:
        mock_browser.extract_people.side_effect = browser_error
    else:
        mock_browser.extract_people.return_value = browser_people or []

    mock_search = MagicMock()
    mock_search.search_leadership.return_value = kagi_results or []

    return LeadershipManager(
        linkedin_browser=mock_browser,
        leadership_search=mock_search,
        leadership_repo=LeadershipRepository(tmp_db),
        social_link_repo=SocialMediaLinkRepository(tmp_db),
        company_repo=CompanyRepository(tmp_db),
    )


class TestLeadershipExtractionWorkflow:
    def test_full_playwright_extraction(self, tmp_db: Database, company_with_linkedin: int) -> None:
        """Full workflow: company -> LinkedIn URL -> Playwright -> stored."""
        manager = _build_manager(
            tmp_db,
            browser_people=[
                {
                    "name": "Alice CEO",
                    "title": "CEO",
                    "profile_url": "https://linkedin.com/in/alice-ceo",
                },
                {
                    "name": "Bob CTO",
                    "title": "CTO",
                    "profile_url": "https://linkedin.com/in/bob-cto",
                },
                {
                    "name": "Eve Engineer",
                    "title": "Software Engineer",
                    "profile_url": "https://linkedin.com/in/eve-eng",
                },
            ],
        )

        result = manager.extract_company_leadership(company_with_linkedin)
        assert result["method_used"] == "playwright_scrape"
        # Only leadership titles stored (CEO, CTO), not engineer
        assert result["leaders_found"] == 2

        # Verify in database
        repo = LeadershipRepository(tmp_db)
        leaders = repo.get_leadership_for_company(company_with_linkedin)
        assert len(leaders) == 2

    def test_fallback_to_kagi_workflow(self, tmp_db: Database, company_with_linkedin: int) -> None:
        """Playwright blocked -> fallback to Kagi -> stored."""
        manager = _build_manager(
            tmp_db,
            browser_error=LinkedInBlockedError("CAPTCHA"),
            kagi_results=[
                {
                    "name": "Carol Founder",
                    "title": "Founder",
                    "profile_url": "https://linkedin.com/in/carol-founder",
                },
            ],
        )

        result = manager.extract_company_leadership(company_with_linkedin)
        assert result["method_used"] == "kagi_search"
        assert result["leaders_found"] == 1
        assert len(result["errors"]) >= 1  # Playwright error logged

    def test_no_linkedin_url_uses_kagi(self, tmp_db: Database, company_id: int) -> None:
        """Company without LinkedIn URL goes straight to Kagi."""
        manager = _build_manager(
            tmp_db,
            kagi_results=[
                {
                    "name": "Dave CEO",
                    "title": "CEO",
                    "profile_url": "https://linkedin.com/in/dave-ceo",
                },
            ],
        )

        result = manager.extract_company_leadership(company_id)
        assert result["method_used"] == "kagi_search"

    def test_deduplication_across_runs(self, tmp_db: Database, company_with_linkedin: int) -> None:
        """Running extraction twice does not create duplicate records."""
        people = [
            {
                "name": "Alice CEO",
                "title": "CEO",
                "profile_url": "https://linkedin.com/in/alice-ceo",
            },
        ]

        manager = _build_manager(tmp_db, browser_people=people)

        # Run twice
        manager.extract_company_leadership(company_with_linkedin)
        manager.extract_company_leadership(company_with_linkedin)

        # Should still have only 1 record
        repo = LeadershipRepository(tmp_db)
        leaders = repo.get_leadership_for_company(company_with_linkedin)
        assert len(leaders) == 1

    def test_ceo_departure_detected_and_flagged(
        self, tmp_db: Database, company_with_linkedin: int
    ) -> None:
        """When CEO leaves between runs, change is detected as critical."""
        # First run: company has CEO
        manager1 = _build_manager(
            tmp_db,
            browser_people=[
                {
                    "name": "OldCEO",
                    "title": "CEO",
                    "profile_url": "https://linkedin.com/in/old-ceo",
                },
            ],
        )
        manager1.extract_company_leadership(company_with_linkedin)

        # Second run: CEO is gone, new person appears
        manager2 = _build_manager(
            tmp_db,
            browser_people=[
                {
                    "name": "NewCTO",
                    "title": "CTO",
                    "profile_url": "https://linkedin.com/in/new-cto",
                },
            ],
        )
        result = manager2.extract_company_leadership(company_with_linkedin)

        # CEO departure should be detected
        changes = result.get("leadership_changes", [])
        departures = [c for c in changes if "departure" in c.get("change_type", "")]
        assert len(departures) >= 1
        assert any(c.get("severity") == "critical" for c in departures)

        # Old CEO should be marked not current
        repo = LeadershipRepository(tmp_db)
        current = repo.get_current_leadership(company_with_linkedin)
        old_ceo = [
            leader for leader in current if "old-ceo" in leader.get("linkedin_profile_url", "")
        ]
        assert len(old_ceo) == 0

    def test_batch_extraction(self, tmp_db: Database) -> None:
        """Batch extraction processes multiple companies."""
        now = datetime.now(UTC).isoformat()

        # Create 3 companies
        company_ids = []
        for i in range(3):
            cursor = tmp_db.execute(
                """INSERT INTO companies
                   (name, homepage_url, source_sheet, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (f"BatchCo{i}", f"https://batch{i}.com", "Sheet1", now, now),
            )
            tmp_db.connection.commit()
            company_ids.append(cursor.lastrowid)

        manager = _build_manager(
            tmp_db,
            kagi_results=[
                {
                    "name": "Leader",
                    "title": "CEO",
                    "profile_url": "https://linkedin.com/in/leader",
                },
            ],
        )

        result = manager.extract_all_leadership(limit=3)
        assert result["processed"] == 3
        assert result["successful"] == 3

    def test_significance_classification_on_critical_change(
        self, tmp_db: Database, company_with_linkedin: int
    ) -> None:
        """Critical leadership change should be classified as significant."""
        # Pre-populate: company has founder
        manager1 = _build_manager(
            tmp_db,
            browser_people=[
                {
                    "name": "FounderPerson",
                    "title": "Founder",
                    "profile_url": "https://linkedin.com/in/founder",
                },
            ],
        )
        manager1.extract_company_leadership(company_with_linkedin)

        # Founder departs
        manager2 = _build_manager(tmp_db, browser_people=[])
        result = manager2.extract_company_leadership(company_with_linkedin)

        assert result.get("change_significance") == "significant"


class TestCompanyLeadershipTable:
    def test_table_created_on_init(self, tmp_db: Database) -> None:
        """company_leadership table should exist after init_db."""
        rows = tmp_db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='company_leadership'"
        )
        assert len(rows) == 1

    def test_foreign_key_cascade(self, tmp_db: Database, company_id: int) -> None:
        """Deleting company should cascade to leadership records."""
        now = datetime.now(UTC).isoformat()
        tmp_db.execute(
            """INSERT INTO company_leadership
               (company_id, person_name, title, linkedin_profile_url,
                discovery_method, confidence, is_current, discovered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                company_id,
                "Test Person",
                "CEO",
                "https://linkedin.com/in/test",
                "playwright_scrape",
                0.8,
                1,
                now,
            ),
        )
        tmp_db.connection.commit()

        # Delete the company
        tmp_db.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        tmp_db.connection.commit()

        # Leadership should be gone
        rows = tmp_db.fetchall(
            "SELECT * FROM company_leadership WHERE company_id = ?",
            (company_id,),
        )
        assert len(rows) == 0
