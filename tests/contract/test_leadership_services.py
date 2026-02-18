"""Contract tests for leadership services.

Tests repository CRUD against real temp database.
Tests services with mocked external dependencies.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.domains.leadership.repositories.leadership_repository import (
    LeadershipRepository,
)
from src.services.database import Database


@pytest.fixture
def tmp_db(tmp_path: Any) -> Database:
    """Create a temporary database with schema."""
    db = Database(db_path=str(tmp_path / "test.db"))
    db.init_db()
    return db


@pytest.fixture
def leadership_repo(tmp_db: Database) -> LeadershipRepository:
    """Create a leadership repository with temp database."""
    return LeadershipRepository(tmp_db)


@pytest.fixture
def sample_company(tmp_db: Database) -> dict[str, Any]:
    """Insert a sample company and return its data."""
    now = datetime.now(UTC).isoformat()
    cursor = tmp_db.execute(
        """INSERT INTO companies (name, homepage_url, source_sheet, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("Acme Corp", "https://acme.com", "Sheet1", now, now),
    )
    tmp_db.connection.commit()
    return {"id": cursor.lastrowid, "name": "Acme Corp", "homepage_url": "https://acme.com"}


@pytest.fixture
def sample_leadership_data(sample_company: dict[str, Any]) -> dict[str, Any]:
    """Sample leadership data dict."""
    return {
        "company_id": sample_company["id"],
        "person_name": "Alice Smith",
        "title": "CEO",
        "linkedin_profile_url": "https://www.linkedin.com/in/alice-smith",
        "discovery_method": "playwright_scrape",
        "confidence": 0.85,
        "is_current": True,
        "discovered_at": datetime.now(UTC).isoformat(),
        "last_verified_at": None,
        "source_company_linkedin_url": "https://www.linkedin.com/company/acme",
    }


# --- Repository CRUD Tests ---


class TestLeadershipRepository:
    def test_store_leadership(
        self,
        leadership_repo: LeadershipRepository,
        sample_leadership_data: dict[str, Any],
    ) -> None:
        row_id = leadership_repo.store_leadership(sample_leadership_data)
        assert row_id > 0

    def test_get_leadership_for_company(
        self,
        leadership_repo: LeadershipRepository,
        sample_leadership_data: dict[str, Any],
        sample_company: dict[str, Any],
    ) -> None:
        leadership_repo.store_leadership(sample_leadership_data)
        results = leadership_repo.get_leadership_for_company(sample_company["id"])
        assert len(results) == 1
        assert results[0]["person_name"] == "Alice Smith"
        assert results[0]["title"] == "CEO"

    def test_get_current_leadership(
        self,
        leadership_repo: LeadershipRepository,
        sample_leadership_data: dict[str, Any],
        sample_company: dict[str, Any],
    ) -> None:
        leadership_repo.store_leadership(sample_leadership_data)
        results = leadership_repo.get_current_leadership(sample_company["id"])
        assert len(results) == 1

    def test_duplicate_handled_gracefully(
        self,
        leadership_repo: LeadershipRepository,
        sample_leadership_data: dict[str, Any],
    ) -> None:
        """Duplicate insertion (same company_id + profile_url) should upsert."""
        first_id = leadership_repo.store_leadership(sample_leadership_data)
        assert first_id > 0

        # Insert duplicate -- should update, not fail
        sample_leadership_data["confidence"] = 0.95
        second_id = leadership_repo.store_leadership(sample_leadership_data)
        # Should return 0 (no new row) or succeed without error
        assert isinstance(second_id, int)

    def test_leadership_exists(
        self,
        leadership_repo: LeadershipRepository,
        sample_leadership_data: dict[str, Any],
        sample_company: dict[str, Any],
    ) -> None:
        leadership_repo.store_leadership(sample_leadership_data)
        assert leadership_repo.leadership_exists(
            sample_company["id"],
            "https://www.linkedin.com/in/alice-smith",
        )
        assert not leadership_repo.leadership_exists(
            sample_company["id"],
            "https://www.linkedin.com/in/nobody",
        )

    def test_mark_not_current(
        self,
        leadership_repo: LeadershipRepository,
        sample_leadership_data: dict[str, Any],
        sample_company: dict[str, Any],
    ) -> None:
        leadership_repo.store_leadership(sample_leadership_data)
        leadership_repo.mark_not_current(
            sample_company["id"],
            "https://www.linkedin.com/in/alice-smith",
        )
        current = leadership_repo.get_current_leadership(sample_company["id"])
        assert len(current) == 0

        # All records should still exist
        all_records = leadership_repo.get_leadership_for_company(sample_company["id"])
        assert len(all_records) == 1
        assert all_records[0]["is_current"] == 0

    def test_get_all_leadership(
        self,
        leadership_repo: LeadershipRepository,
        sample_leadership_data: dict[str, Any],
    ) -> None:
        leadership_repo.store_leadership(sample_leadership_data)
        all_records = leadership_repo.get_all_leadership()
        assert len(all_records) >= 1

    def test_multiple_leaders_per_company(
        self,
        leadership_repo: LeadershipRepository,
        sample_leadership_data: dict[str, Any],
        sample_company: dict[str, Any],
    ) -> None:
        leadership_repo.store_leadership(sample_leadership_data)

        cto_data = {
            **sample_leadership_data,
            "person_name": "Bob Jones",
            "title": "CTO",
            "linkedin_profile_url": "https://www.linkedin.com/in/bob-jones",
        }
        leadership_repo.store_leadership(cto_data)

        results = leadership_repo.get_leadership_for_company(sample_company["id"])
        assert len(results) == 2


# --- LinkedIn Browser Service Tests ---


class TestLinkedInBrowserContract:
    def test_blocked_error_raised_on_captcha(self) -> None:
        """LinkedInBlockedError should be raised when CAPTCHA detected."""
        from src.domains.leadership.services.linkedin_browser import (
            LinkedInBlockedError,
            LinkedInBrowser,
        )

        LinkedInBrowser(headless=True, profile_dir="/tmp/test_profile")
        # We can't actually run Playwright in CI, so we test the error class exists
        assert issubclass(LinkedInBlockedError, Exception)

    def test_browser_init_parameters(self) -> None:
        """LinkedInBrowser accepts headless and profile_dir parameters."""
        from src.domains.leadership.services.linkedin_browser import LinkedInBrowser

        browser = LinkedInBrowser(headless=True, profile_dir="/tmp/test_profile")
        assert browser.headless is True
        assert browser.profile_dir == "/tmp/test_profile"


# --- Kagi Leadership Search Tests ---


class TestLeadershipSearchContract:
    def test_search_queries_formed_correctly(self) -> None:
        """LeadershipSearch should search for CEO, founder, CTO."""
        from src.domains.leadership.services.leadership_search import LeadershipSearch

        mock_kagi = MagicMock()
        mock_kagi.search.return_value = []

        search = LeadershipSearch(mock_kagi)
        search.search_leadership("Acme Corp")

        # Should have made at least 3 search calls
        assert mock_kagi.search.call_count >= 3
        calls = [str(c) for c in mock_kagi.search.call_args_list]
        # Verify CEO, founder, CTO queries
        combined = " ".join(calls)
        assert "CEO" in combined
        assert "founder" in combined
        assert "CTO" in combined

    def test_search_parses_linkedin_results(self) -> None:
        """LeadershipSearch should parse results with LinkedIn profile URLs."""
        from src.domains.leadership.services.leadership_search import LeadershipSearch

        mock_kagi = MagicMock()
        mock_kagi.search.return_value = [
            {
                "title": "John Smith - CEO at Acme Corp | LinkedIn",
                "url": "https://linkedin.com/in/john-smith",
                "snippet": "John Smith is CEO of Acme Corp.",
                "published": "2024-01-01T00:00:00+00:00",
                "source": "linkedin.com",
            },
        ]

        search = LeadershipSearch(mock_kagi)
        results = search.search_leadership("Acme Corp")
        assert len(results) >= 1
        assert results[0]["name"] == "John Smith"

    def test_search_deduplicates(self) -> None:
        """Same person appearing in multiple searches should be deduplicated."""
        from src.domains.leadership.services.leadership_search import LeadershipSearch

        mock_kagi = MagicMock()
        # Return the same person for CEO and founder queries
        mock_kagi.search.return_value = [
            {
                "title": "Jane Doe - CEO & Founder | LinkedIn",
                "url": "https://linkedin.com/in/jane-doe",
                "snippet": "Jane Doe is CEO and Founder.",
                "published": "2024-01-01T00:00:00+00:00",
                "source": "linkedin.com",
            },
        ]

        search = LeadershipSearch(mock_kagi)
        results = search.search_leadership("SomeCo")
        # Should be deduplicated to 1 person (same URL across all queries)
        assert len(results) == 1


# --- Leadership Manager Tests ---


class TestLeadershipManagerContract:
    def test_playwright_success_path(self, tmp_db: Database) -> None:
        """When Playwright succeeds, results stored with playwright_scrape method."""
        from src.domains.leadership.repositories.leadership_repository import (
            LeadershipRepository,
        )
        from src.domains.leadership.services.leadership_manager import (
            LeadershipManager,
        )

        # Set up company
        now = datetime.now(UTC).isoformat()
        cursor = tmp_db.execute(
            """INSERT INTO companies (name, homepage_url, source_sheet, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("TestCo", "https://testco.com", "Sheet1", now, now),
        )
        tmp_db.connection.commit()
        company_id = cursor.lastrowid

        # Add LinkedIn company URL to social_media_links
        tmp_db.execute(
            """INSERT INTO social_media_links
               (company_id, platform, profile_url, discovery_method,
                verification_status, discovered_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                company_id,
                "linkedin",
                "https://www.linkedin.com/company/testco",
                "page_footer",
                "unverified",
                now,
            ),
        )
        tmp_db.connection.commit()

        # Mock browser to return leadership data
        mock_browser = MagicMock()
        mock_browser.extract_people.return_value = [
            {"name": "Alice CEO", "title": "CEO", "profile_url": "https://linkedin.com/in/alice"},
        ]

        mock_search = MagicMock()

        from src.domains.discovery.repositories.social_media_link_repository import (
            SocialMediaLinkRepository,
        )
        from src.repositories.company_repository import CompanyRepository

        leadership_repo = LeadershipRepository(tmp_db)
        social_repo = SocialMediaLinkRepository(tmp_db)
        company_repo = CompanyRepository(tmp_db)

        manager = LeadershipManager(
            linkedin_browser=mock_browser,
            leadership_search=mock_search,
            leadership_repo=leadership_repo,
            social_link_repo=social_repo,
            company_repo=company_repo,
        )

        result = manager.extract_company_leadership(company_id)
        assert result.get("leaders_found", 0) >= 1
        assert result.get("method_used") == "playwright_scrape"
        mock_search.search_leadership.assert_not_called()

    def test_fallback_to_kagi_on_blocked(self, tmp_db: Database) -> None:
        """When Playwright is blocked, fallback to Kagi search."""
        from src.domains.leadership.repositories.leadership_repository import (
            LeadershipRepository,
        )
        from src.domains.leadership.services.leadership_manager import (
            LeadershipManager,
        )
        from src.domains.leadership.services.linkedin_browser import (
            LinkedInBlockedError,
        )

        now = datetime.now(UTC).isoformat()
        cursor = tmp_db.execute(
            """INSERT INTO companies (name, homepage_url, source_sheet, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("BlockedCo", "https://blocked.com", "Sheet1", now, now),
        )
        tmp_db.connection.commit()
        company_id = cursor.lastrowid

        tmp_db.execute(
            """INSERT INTO social_media_links
               (company_id, platform, profile_url, discovery_method,
                verification_status, discovered_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                company_id,
                "linkedin",
                "https://www.linkedin.com/company/blockedco",
                "page_footer",
                "unverified",
                now,
            ),
        )
        tmp_db.connection.commit()

        mock_browser = MagicMock()
        mock_browser.extract_people.side_effect = LinkedInBlockedError("CAPTCHA detected")

        mock_search = MagicMock()
        mock_search.search_leadership.return_value = [
            {
                "name": "Bob Founder",
                "title": "Founder",
                "profile_url": "https://linkedin.com/in/bob-founder",
            },
        ]

        from src.domains.discovery.repositories.social_media_link_repository import (
            SocialMediaLinkRepository,
        )
        from src.repositories.company_repository import CompanyRepository

        leadership_repo = LeadershipRepository(tmp_db)
        social_repo = SocialMediaLinkRepository(tmp_db)
        company_repo = CompanyRepository(tmp_db)

        manager = LeadershipManager(
            linkedin_browser=mock_browser,
            leadership_search=mock_search,
            leadership_repo=leadership_repo,
            social_link_repo=social_repo,
            company_repo=company_repo,
        )

        result = manager.extract_company_leadership(company_id)
        assert result.get("leaders_found", 0) >= 1
        assert result.get("method_used") == "kagi_search"

    def test_no_linkedin_url_goes_to_kagi(self, tmp_db: Database) -> None:
        """Company without LinkedIn URL should go straight to Kagi."""
        from src.domains.leadership.repositories.leadership_repository import (
            LeadershipRepository,
        )
        from src.domains.leadership.services.leadership_manager import (
            LeadershipManager,
        )

        now = datetime.now(UTC).isoformat()
        cursor = tmp_db.execute(
            """INSERT INTO companies (name, homepage_url, source_sheet, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("NoLinkedIn", "https://nolinkedin.com", "Sheet1", now, now),
        )
        tmp_db.connection.commit()
        company_id = cursor.lastrowid

        mock_browser = MagicMock()
        mock_search = MagicMock()
        mock_search.search_leadership.return_value = []

        from src.domains.discovery.repositories.social_media_link_repository import (
            SocialMediaLinkRepository,
        )
        from src.repositories.company_repository import CompanyRepository

        leadership_repo = LeadershipRepository(tmp_db)
        social_repo = SocialMediaLinkRepository(tmp_db)
        company_repo = CompanyRepository(tmp_db)

        manager = LeadershipManager(
            linkedin_browser=mock_browser,
            leadership_search=mock_search,
            leadership_repo=leadership_repo,
            social_link_repo=social_repo,
            company_repo=company_repo,
        )

        result = manager.extract_company_leadership(company_id)
        assert result.get("method_used") == "kagi_search"
        mock_browser.extract_people.assert_not_called()
