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
    return LeadershipRepository(tmp_db, "test-user")


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


# --- CDP Browser Service Tests ---


class TestCDPBrowserContract:
    def test_blocked_error_raised(self) -> None:
        """CDPBlockedError should be a proper exception."""
        from src.domains.leadership.services.cdp_browser import CDPBlockedError

        assert issubclass(CDPBlockedError, Exception)

    def test_browser_init_parameters(self) -> None:
        """CDPBrowser accepts profile_dir parameter."""
        from src.domains.leadership.services.cdp_browser import CDPBrowser

        browser = CDPBrowser(profile_dir="/tmp/test_profile")
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
    def test_cdp_success_path(self, tmp_db: Database) -> None:
        """When CDP succeeds, results stored with cdp_scrape method."""
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

        # Mock CDP browser to return leadership data
        mock_browser = MagicMock()
        mock_browser.extract_people.return_value = [
            {"name": "Alice CEO", "title": "CEO", "profile_url": "https://linkedin.com/in/alice"},
        ]
        mock_browser.get_page_html.return_value = "<html>mock</html>"
        mock_browser.capture_people_screenshots.return_value = []
        mock_browser.delay_between_pages.return_value = None

        mock_search = MagicMock()

        from src.domains.discovery.repositories.social_media_link_repository import (
            SocialMediaLinkRepository,
        )
        from src.repositories.company_repository import CompanyRepository

        leadership_repo = LeadershipRepository(tmp_db, "test-user")
        social_repo = SocialMediaLinkRepository(tmp_db, "test-user")
        company_repo = CompanyRepository(tmp_db, "test-user")

        manager = LeadershipManager(
            cdp_browser=mock_browser,
            leadership_search=mock_search,
            leadership_repo=leadership_repo,
            social_link_repo=social_repo,
            company_repo=company_repo,
        )

        result = manager.extract_company_leadership(company_id)
        assert result.get("leaders_found", 0) >= 1
        assert result.get("method_used") == "cdp_scrape"
        mock_search.search_leadership.assert_not_called()

    def test_fallback_to_kagi_on_blocked(self, tmp_db: Database) -> None:
        """When CDP is blocked, fallback to Kagi search."""
        from src.domains.leadership.repositories.leadership_repository import (
            LeadershipRepository,
        )
        from src.domains.leadership.services.cdp_browser import CDPBlockedError
        from src.domains.leadership.services.leadership_manager import (
            LeadershipManager,
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
        mock_browser.extract_people.side_effect = CDPBlockedError("CAPTCHA detected")
        mock_browser.delay_between_pages.return_value = None

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

        leadership_repo = LeadershipRepository(tmp_db, "test-user")
        social_repo = SocialMediaLinkRepository(tmp_db, "test-user")
        company_repo = CompanyRepository(tmp_db, "test-user")

        manager = LeadershipManager(
            cdp_browser=mock_browser,
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
        mock_browser.delay_between_pages.return_value = None
        mock_search = MagicMock()
        mock_search.search_leadership.return_value = []

        from src.domains.discovery.repositories.social_media_link_repository import (
            SocialMediaLinkRepository,
        )
        from src.repositories.company_repository import CompanyRepository

        leadership_repo = LeadershipRepository(tmp_db, "test-user")
        social_repo = SocialMediaLinkRepository(tmp_db, "test-user")
        company_repo = CompanyRepository(tmp_db, "test-user")

        manager = LeadershipManager(
            cdp_browser=mock_browser,
            leadership_search=mock_search,
            leadership_repo=leadership_repo,
            social_link_repo=social_repo,
            company_repo=company_repo,
        )

        result = manager.extract_company_leadership(company_id)
        assert result.get("method_used") == "kagi_search"
        mock_browser.extract_people.assert_not_called()


# --- LeadershipChangeRepository tests ---


class TestLeadershipChangeRepository:
    def _make_repo(self, tmp_db: Database):
        from src.domains.leadership.repositories.leadership_change_repository import (
            LeadershipChangeRepository,
        )

        return LeadershipChangeRepository(tmp_db, "test-user")

    def _sample_event(self, company_id: int, change_type: str = "ceo_departure") -> dict[str, Any]:
        return {
            "company_id": company_id,
            "change_type": change_type,
            "person_name": "Alice Smith",
            "title": "CEO",
            "linkedin_profile_url": "https://www.linkedin.com/in/alice-smith",
            "severity": "critical",
            "detected_at": datetime.now(UTC).isoformat(),
            "confidence": 0.95,
            "discovery_method": "cdp_scrape",
        }

    def test_store_single_change(self, tmp_db: Database, sample_company: dict[str, Any]) -> None:
        repo = self._make_repo(tmp_db)
        row_id = repo.store_change(self._sample_event(sample_company["id"]))
        assert row_id > 0

        rows = repo.get_changes_for_company(sample_company["id"])
        assert len(rows) == 1
        assert rows[0]["change_type"] == "ceo_departure"
        assert rows[0]["severity"] == "critical"
        assert rows[0]["performed_by"] == "test-user"

    def test_store_changes_batch(self, tmp_db: Database, sample_company: dict[str, Any]) -> None:
        repo = self._make_repo(tmp_db)
        events = [
            self._sample_event(sample_company["id"], "ceo_departure"),
            self._sample_event(sample_company["id"], "new_ceo"),
        ]
        inserted = repo.store_changes(events)
        assert inserted == 2
        assert len(repo.get_changes_for_company(sample_company["id"])) == 2

    def test_store_changes_empty_list_is_noop(
        self, tmp_db: Database, sample_company: dict[str, Any]
    ) -> None:
        repo = self._make_repo(tmp_db)
        assert repo.store_changes([]) == 0
        assert repo.get_changes_for_company(sample_company["id"]) == []

    def test_get_recent_changes_joins_company_name(
        self, tmp_db: Database, sample_company: dict[str, Any]
    ) -> None:
        repo = self._make_repo(tmp_db)
        repo.store_change(self._sample_event(sample_company["id"]))

        recent = repo.get_recent_changes(days=90)
        assert len(recent) == 1
        assert recent[0]["company_name"] == sample_company["name"]

    def test_get_recent_changes_severity_filter(
        self, tmp_db: Database, sample_company: dict[str, Any]
    ) -> None:
        repo = self._make_repo(tmp_db)
        critical = self._sample_event(sample_company["id"])
        notable = self._sample_event(sample_company["id"], "new_ceo")
        notable["severity"] = "notable"
        repo.store_changes([critical, notable])

        critical_only = repo.get_recent_changes(days=90, severity="critical")
        assert len(critical_only) == 1
        assert critical_only[0]["change_type"] == "ceo_departure"

    def test_get_critical_changes_for_company(
        self, tmp_db: Database, sample_company: dict[str, Any]
    ) -> None:
        repo = self._make_repo(tmp_db)
        critical = self._sample_event(sample_company["id"])
        notable = self._sample_event(sample_company["id"], "executive_departure")
        notable["severity"] = "notable"
        repo.store_changes([critical, notable])

        results = repo.get_critical_changes_for_company(sample_company["id"])
        assert len(results) == 1
        assert results[0]["severity"] == "critical"

    def test_cascade_delete_when_company_removed(
        self, tmp_db: Database, sample_company: dict[str, Any]
    ) -> None:
        repo = self._make_repo(tmp_db)
        repo.store_change(self._sample_event(sample_company["id"]))
        assert len(repo.get_changes_for_company(sample_company["id"])) == 1

        tmp_db.execute("DELETE FROM companies WHERE id = ?", (sample_company["id"],))
        tmp_db.connection.commit()

        assert repo.get_changes_for_company(sample_company["id"]) == []


class TestLeadershipChangeModel:
    def test_valid_change(self) -> None:
        from src.models.leadership_change import LeadershipChange

        change = LeadershipChange(
            company_id=1,
            change_type="ceo_departure",
            person_name="Alice",
            title="CEO",
            linkedin_profile_url="https://www.linkedin.com/in/alice",
            severity="critical",
            detected_at=datetime.now(UTC),
            confidence=0.95,
            discovery_method="cdp_scrape",
        )
        assert change.severity == "critical"

    def test_empty_person_name_rejected(self) -> None:
        from pydantic import ValidationError

        from src.models.leadership_change import LeadershipChange

        with pytest.raises(ValidationError):
            LeadershipChange(
                company_id=1,
                change_type="ceo_departure",
                person_name="",
                severity="critical",
                detected_at=datetime.now(UTC),
            )

    def test_confidence_out_of_range_rejected(self) -> None:
        from pydantic import ValidationError

        from src.models.leadership_change import LeadershipChange

        with pytest.raises(ValidationError):
            LeadershipChange(
                company_id=1,
                change_type="ceo_departure",
                person_name="Alice",
                severity="critical",
                detected_at=datetime.now(UTC),
                confidence=1.5,
            )


class TestLeadershipManagerPersistsEvents:
    """End-to-end: LeadershipManager writes events to the change log on departures."""

    def test_departure_records_event(self, tmp_db: Database) -> None:
        from src.domains.discovery.repositories.social_media_link_repository import (
            SocialMediaLinkRepository,
        )
        from src.domains.leadership.repositories.leadership_change_repository import (
            LeadershipChangeRepository,
        )
        from src.domains.leadership.repositories.leadership_repository import (
            LeadershipRepository,
        )
        from src.domains.leadership.services.leadership_manager import (
            LeadershipManager,
        )
        from src.repositories.company_repository import CompanyRepository

        now = datetime.now(UTC).isoformat()

        cursor = tmp_db.execute(
            """INSERT INTO companies (name, homepage_url, source_sheet, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("EventCo", "https://eventco.com", "Sheet1", now, now),
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
                "https://www.linkedin.com/company/eventco",
                "page_footer",
                "unverified",
                now,
            ),
        )
        tmp_db.connection.commit()

        leadership_repo = LeadershipRepository(tmp_db, "test-user")
        change_repo = LeadershipChangeRepository(tmp_db, "test-user")
        social_repo = SocialMediaLinkRepository(tmp_db, "test-user")
        company_repo = CompanyRepository(tmp_db, "test-user")

        # Seed a previous CEO so the next run will detect a departure
        leadership_repo.store_leadership(
            {
                "company_id": company_id,
                "person_name": "Outgoing Alice",
                "title": "CEO",
                "linkedin_profile_url": "https://www.linkedin.com/in/outgoing-alice",
                "discovery_method": "cdp_scrape",
                "confidence": 0.8,
                "is_current": True,
                "discovered_at": now,
                "last_verified_at": now,
            }
        )

        # New run returns a different CEO
        mock_browser = MagicMock()
        mock_browser.extract_people.return_value = [
            {
                "name": "New Bob",
                "title": "CEO",
                "profile_url": "https://linkedin.com/in/new-bob",
            },
        ]
        mock_browser.get_page_html.return_value = "<html></html>"
        mock_browser.capture_people_screenshots.return_value = []
        mock_browser.delay_between_pages.return_value = None

        manager = LeadershipManager(
            cdp_browser=mock_browser,
            leadership_search=MagicMock(),
            leadership_repo=leadership_repo,
            social_link_repo=social_repo,
            company_repo=company_repo,
            leadership_change_repo=change_repo,
        )

        manager.extract_company_leadership(company_id)

        events = change_repo.get_changes_for_company(company_id)
        change_types = {e["change_type"] for e in events}
        assert "ceo_departure" in change_types
        assert "new_ceo" in change_types

        critical = change_repo.get_critical_changes_for_company(company_id)
        assert any(e["person_name"] == "Outgoing Alice" for e in critical)

    def test_bootstrap_run_does_not_record_events(self, tmp_db: Database) -> None:
        """First-ever extraction (no previous leaders) should not emit events."""
        from src.domains.discovery.repositories.social_media_link_repository import (
            SocialMediaLinkRepository,
        )
        from src.domains.leadership.repositories.leadership_change_repository import (
            LeadershipChangeRepository,
        )
        from src.domains.leadership.repositories.leadership_repository import (
            LeadershipRepository,
        )
        from src.domains.leadership.services.leadership_manager import (
            LeadershipManager,
        )
        from src.repositories.company_repository import CompanyRepository

        now = datetime.now(UTC).isoformat()
        cursor = tmp_db.execute(
            """INSERT INTO companies (name, homepage_url, source_sheet, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("BootCo", "https://bootco.com", "Sheet1", now, now),
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
                "https://www.linkedin.com/company/bootco",
                "page_footer",
                "unverified",
                now,
            ),
        )
        tmp_db.connection.commit()

        mock_browser = MagicMock()
        mock_browser.extract_people.return_value = [
            {
                "name": "First Carol",
                "title": "CEO",
                "profile_url": "https://linkedin.com/in/first-carol",
            },
        ]
        mock_browser.get_page_html.return_value = "<html></html>"
        mock_browser.capture_people_screenshots.return_value = []
        mock_browser.delay_between_pages.return_value = None

        leadership_repo = LeadershipRepository(tmp_db, "test-user")
        change_repo = LeadershipChangeRepository(tmp_db, "test-user")
        social_repo = SocialMediaLinkRepository(tmp_db, "test-user")
        company_repo = CompanyRepository(tmp_db, "test-user")

        manager = LeadershipManager(
            cdp_browser=mock_browser,
            leadership_search=MagicMock(),
            leadership_repo=leadership_repo,
            social_link_repo=social_repo,
            company_repo=company_repo,
            leadership_change_repo=change_repo,
        )

        manager.extract_company_leadership(company_id)

        # No events on bootstrap run
        assert change_repo.get_changes_for_company(company_id) == []
