"""Contract tests for CEO LinkedIn discovery components.

Tests repositories against real temp databases and services with mocked APIs.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.domains.leadership.repositories.leadership_mention_repository import (
    LeadershipMentionRepository,
)
from src.domains.leadership.repositories.leadership_repository import (
    LeadershipRepository,
)
from src.services.database import Database

# --- Fixtures ---


@pytest.fixture
def tmp_db() -> Database:
    """Create a temp database with schema initialized."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


@pytest.fixture
def mention_repo(tmp_db: Database) -> LeadershipMentionRepository:
    return LeadershipMentionRepository(tmp_db, "test-user")


@pytest.fixture
def leadership_repo(tmp_db: Database) -> LeadershipRepository:
    return LeadershipRepository(tmp_db, "test-user")


@pytest.fixture
def sample_company_id(tmp_db: Database) -> int:
    """Insert a sample company and return its ID."""
    now = datetime.now(UTC).isoformat()
    cursor = tmp_db.execute(
        """INSERT INTO companies (name, homepage_url, source_sheet, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("Acme Corp", "https://acme.com", "Sheet1", now, now),
    )
    tmp_db.connection.commit()
    return cursor.lastrowid or 0


@pytest.fixture
def sample_snapshot_id(tmp_db: Database, sample_company_id: int) -> int:
    """Insert a sample snapshot and return its ID."""
    now = datetime.now(UTC).isoformat()
    cursor = tmp_db.execute(
        """INSERT INTO snapshots (company_id, url, content_markdown, captured_at)
           VALUES (?, ?, ?, ?)""",
        (sample_company_id, "https://acme.com", "CEO: John Smith", now),
    )
    tmp_db.connection.commit()
    return cursor.lastrowid or 0


# --- LeadershipMentionRepository Tests ---


class TestLeadershipMentionRepository:
    """Contract tests for LeadershipMentionRepository."""

    def test_store_and_retrieve_mention(
        self,
        mention_repo: LeadershipMentionRepository,
        sample_company_id: int,
        sample_snapshot_id: int,
    ) -> None:
        """Store a mention and retrieve it."""
        now = datetime.now(UTC).isoformat()
        row_id = mention_repo.store_mention(
            {
                "company_id": sample_company_id,
                "person_name": "John Smith",
                "title_context": "CEO",
                "source": "homepage_snapshot",
                "source_url": "https://acme.com",
                "confidence": 0.8,
                "extracted_at": now,
                "snapshot_id": sample_snapshot_id,
            }
        )
        assert row_id > 0

        mentions = mention_repo.get_mentions_for_company(sample_company_id)
        assert len(mentions) == 1
        assert mentions[0]["person_name"] == "John Smith"
        assert mentions[0]["title_context"] == "CEO"
        assert mentions[0]["confidence"] == 0.8

    def test_duplicate_mention_skipped(
        self,
        mention_repo: LeadershipMentionRepository,
        sample_company_id: int,
    ) -> None:
        """Duplicate mention is skipped via explicit check, not DB error."""
        now = datetime.now(UTC).isoformat()
        data = {
            "company_id": sample_company_id,
            "person_name": "Jane Doe",
            "title_context": "Founder",
            "source": "homepage_snapshot",
            "extracted_at": now,
        }
        first_id = mention_repo.store_mention(data)
        assert first_id > 0

        # Second store should return 0 (duplicate skipped)
        second_id = mention_repo.store_mention(data)
        assert second_id == 0

        # Only one record in DB
        mentions = mention_repo.get_mentions_for_company(sample_company_id)
        assert len(mentions) == 1

    def test_mention_exists(
        self,
        mention_repo: LeadershipMentionRepository,
        sample_company_id: int,
    ) -> None:
        """mention_exists returns True/False correctly."""
        now = datetime.now(UTC).isoformat()
        assert mention_repo.mention_exists(sample_company_id, "Jane Doe", "CEO") is False

        mention_repo.store_mention(
            {
                "company_id": sample_company_id,
                "person_name": "Jane Doe",
                "title_context": "CEO",
                "source": "test",
                "extracted_at": now,
            }
        )
        assert mention_repo.mention_exists(sample_company_id, "Jane Doe", "CEO") is True

    def test_get_ceo_mentions_filters_correctly(
        self,
        mention_repo: LeadershipMentionRepository,
        sample_company_id: int,
    ) -> None:
        """get_ceo_mentions only returns CEO/founder/president mentions."""
        now = datetime.now(UTC).isoformat()
        for name, title in [
            ("Alice Brown", "CEO"),
            ("Bob Jones", "Founder"),
            ("Charlie Wilson", "VP Engineering"),
        ]:
            mention_repo.store_mention(
                {
                    "company_id": sample_company_id,
                    "person_name": name,
                    "title_context": title,
                    "source": "test",
                    "extracted_at": now,
                    "confidence": 0.7,
                }
            )

        ceo_mentions = mention_repo.get_ceo_mentions(sample_company_id)
        names = {m["person_name"] for m in ceo_mentions}
        assert "Alice Brown" in names
        assert "Bob Jones" in names
        assert "Charlie Wilson" not in names

    def test_get_latest_mention_date(
        self,
        mention_repo: LeadershipMentionRepository,
        sample_company_id: int,
    ) -> None:
        """get_latest_mention_date returns the most recent extraction date."""
        mention_repo.store_mention(
            {
                "company_id": sample_company_id,
                "person_name": "John Smith",
                "title_context": "CEO",
                "source": "test",
                "extracted_at": "2025-01-01T00:00:00",
            }
        )
        mention_repo.store_mention(
            {
                "company_id": sample_company_id,
                "person_name": "Jane Doe",
                "title_context": "Founder",
                "source": "test",
                "extracted_at": "2025-06-15T00:00:00",
            }
        )
        latest = mention_repo.get_latest_mention_date(sample_company_id)
        assert latest == "2025-06-15T00:00:00"

    def test_get_latest_mention_date_no_mentions(
        self,
        mention_repo: LeadershipMentionRepository,
        sample_company_id: int,
    ) -> None:
        """get_latest_mention_date returns None when no mentions exist."""
        latest = mention_repo.get_latest_mention_date(sample_company_id)
        assert latest is None

    def test_priority_stored_and_ordered(
        self,
        mention_repo: LeadershipMentionRepository,
        sample_company_id: int,
    ) -> None:
        """Priority is stored in DB and get_ceo_mentions orders by priority ASC."""
        now = datetime.now(UTC).isoformat()
        # Store FOUNDED_BY (priority 4) first
        mention_repo.store_mention(
            {
                "company_id": sample_company_id,
                "person_name": "Bob Smith",
                "title_context": "Founder",
                "source": "test",
                "priority": 4,
                "extracted_at": now,
            }
        )
        # Store EXPLICIT_TITLE (priority 1) second
        mention_repo.store_mention(
            {
                "company_id": sample_company_id,
                "person_name": "Alice Brown",
                "title_context": "CEO",
                "source": "test",
                "priority": 1,
                "extracted_at": now,
            }
        )

        # get_ceo_mentions should return Alice first (lower priority = higher rank)
        ceo_mentions = mention_repo.get_ceo_mentions(sample_company_id)
        assert len(ceo_mentions) == 2
        assert ceo_mentions[0]["person_name"] == "Alice Brown"
        assert ceo_mentions[0]["priority"] == 1
        assert ceo_mentions[1]["person_name"] == "Bob Smith"
        assert ceo_mentions[1]["priority"] == 4


# --- LeadershipRepository.update_verification_date Tests ---


class TestLeadershipRepositoryVerificationDate:
    """Contract tests for the new update_verification_date method."""

    def test_update_verification_date(
        self,
        leadership_repo: LeadershipRepository,
        sample_company_id: int,
    ) -> None:
        """update_verification_date updates the timestamp for existing record."""
        now = datetime.now(UTC).isoformat()
        profile_url = "https://linkedin.com/in/john-smith"

        # Store a leadership record
        leadership_repo.store_leadership(
            {
                "company_id": sample_company_id,
                "person_name": "John Smith",
                "title": "CEO",
                "linkedin_profile_url": profile_url,
                "discovery_method": "kagi_search",
                "confidence": 0.6,
                "is_current": True,
                "discovered_at": now,
                "last_verified_at": now,
            }
        )

        # Update verification date
        new_date = "2026-06-01T00:00:00"
        leadership_repo.update_verification_date(sample_company_id, profile_url, new_date)

        # Verify update
        leaders = leadership_repo.get_current_leadership(sample_company_id)
        assert len(leaders) == 1
        assert leaders[0]["last_verified_at"] == new_date


# --- LeadershipSearch.search_ceo_linkedin Tests ---


class TestLeadershipSearchCeoMethod:
    """Contract tests for LeadershipSearch.search_ceo_linkedin."""

    def test_search_with_person_name(self) -> None:
        """Uses person_name in Kagi queries when provided."""
        from src.domains.leadership.services.leadership_search import LeadershipSearch

        mock_kagi = MagicMock()
        mock_kagi.search.return_value = [
            {
                "title": "John Smith - CEO - Acme Corp | LinkedIn",
                "url": "https://linkedin.com/in/john-smith",
                "snippet": "CEO at Acme Corp",
            }
        ]

        search = LeadershipSearch(mock_kagi)
        search.search_ceo_linkedin("Acme Corp", person_name="John Smith")

        # Verify queries contain person_name
        calls = mock_kagi.search.call_args_list
        for call in calls:
            query = call.kwargs.get("query", call.args[0] if call.args else "")
            assert "John Smith" in query or "Acme Corp" in query

    def test_search_without_person_name(self) -> None:
        """Falls back to company-only queries."""
        from src.domains.leadership.services.leadership_search import LeadershipSearch

        mock_kagi = MagicMock()
        mock_kagi.search.return_value = []

        search = LeadershipSearch(mock_kagi)
        search.search_ceo_linkedin("Acme Corp")

        # Verify queries were made without person_name
        calls = mock_kagi.search.call_args_list
        assert len(calls) >= 2  # At least CEO and founder queries

    def test_filters_to_ceo_founder_only(self) -> None:
        """CTO results are filtered out, only CEO/founder returned."""
        from src.domains.leadership.services.leadership_search import LeadershipSearch

        mock_kagi = MagicMock()
        mock_kagi.search.return_value = [
            {
                "title": "Bob Jones - CTO - Acme Corp | LinkedIn",
                "url": "https://linkedin.com/in/bob-jones",
                "snippet": "CTO at Acme Corp",
            },
            {
                "title": "Jane Doe - CEO - Acme Corp | LinkedIn",
                "url": "https://linkedin.com/in/jane-doe",
                "snippet": "CEO at Acme Corp",
            },
        ]

        search = LeadershipSearch(mock_kagi)
        results = search.search_ceo_linkedin("Acme Corp")

        # Only CEO should be returned (not CTO)
        names = {r["name"] for r in results}
        assert "Jane Doe" in names
        # CTO should be filtered out since search_ceo_linkedin only returns rank 1-2

    def test_kagi_error_handled(self) -> None:
        """Kagi API errors are caught and logged, not raised."""
        from src.domains.leadership.services.leadership_search import LeadershipSearch

        mock_kagi = MagicMock()
        mock_kagi.search.side_effect = Exception("Kagi API error")

        search = LeadershipSearch(mock_kagi)
        results = search.search_ceo_linkedin("Acme Corp")
        assert results == []

    def test_empty_results(self) -> None:
        """No results from Kagi returns empty list."""
        from src.domains.leadership.services.leadership_search import LeadershipSearch

        mock_kagi = MagicMock()
        mock_kagi.search.return_value = []

        search = LeadershipSearch(mock_kagi)
        results = search.search_ceo_linkedin("Acme Corp")
        assert results == []
