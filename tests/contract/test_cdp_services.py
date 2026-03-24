"""Contract tests for CDP browser services.

Tests service boundaries with mocked Chrome/WebSocket/LLM.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.domains.leadership.repositories.linkedin_snapshot_repository import (
    LinkedInSnapshotRepository,
)
from src.services.database import Database

# --- LinkedIn Snapshot Repository Tests ---


class TestLinkedInSnapshotRepository:
    @pytest.fixture
    def db(self, tmp_path: Any) -> Database:
        db = Database(db_path=str(tmp_path / "test.db"))
        db.init_db()
        # Insert a test company
        now = datetime.now(UTC).isoformat()
        db.execute(
            """INSERT INTO companies
               (name, homepage_url, source_sheet, flagged_for_review, created_at, updated_at)
               VALUES (?, ?, ?, 0, ?, ?)""",
            ("Test Corp", "https://testcorp.com", "Online Presence", now, now),
        )
        db.connection.commit()
        return db

    @pytest.fixture
    def repo(self, db: Database) -> LinkedInSnapshotRepository:
        return LinkedInSnapshotRepository(db, "test_operator")

    def test_store_snapshot(self, repo: LinkedInSnapshotRepository) -> None:
        row_id = repo.store_snapshot({
            "company_id": 1,
            "linkedin_url": "https://www.linkedin.com/company/testcorp",
            "url_type": "company",
            "content_html": "<html>test</html>",
            "content_json": '{"employees": []}',
            "vision_data_json": '{}',
            "screenshot_path": "docs/screenshots/test.png",
            "captured_at": datetime.now(UTC).isoformat(),
        })
        assert row_id > 0

    def test_get_latest_snapshot(self, repo: LinkedInSnapshotRepository) -> None:
        url = "https://www.linkedin.com/company/testcorp"

        repo.store_snapshot({
            "company_id": 1,
            "linkedin_url": url,
            "url_type": "company",
            "content_html": "<html>old</html>",
            "captured_at": "2026-01-01T00:00:00",
        })
        repo.store_snapshot({
            "company_id": 1,
            "linkedin_url": url,
            "url_type": "company",
            "content_html": "<html>new</html>",
            "captured_at": "2026-03-01T00:00:00",
        })

        latest = repo.get_latest_snapshot(1, url)
        assert latest is not None
        assert latest["content_html"] == "<html>new</html>"

    def test_get_snapshots_for_company(self, repo: LinkedInSnapshotRepository) -> None:
        url = "https://www.linkedin.com/company/testcorp"
        repo.store_snapshot({
            "company_id": 1,
            "linkedin_url": url,
            "url_type": "company",
            "content_html": "<html>test</html>",
            "captured_at": datetime.now(UTC).isoformat(),
        })

        snapshots = repo.get_snapshots_for_company(1)
        assert len(snapshots) == 1

    def test_get_person_snapshots(self, repo: LinkedInSnapshotRepository) -> None:
        repo.store_snapshot({
            "company_id": 1,
            "linkedin_url": "https://www.linkedin.com/in/janedoe",
            "url_type": "person",
            "person_name": "Jane Doe",
            "content_html": "<html>profile</html>",
            "captured_at": datetime.now(UTC).isoformat(),
        })

        snapshots = repo.get_person_snapshots(1, "Jane Doe")
        assert len(snapshots) == 1
        assert snapshots[0]["person_name"] == "Jane Doe"

    def test_content_checksum_computed(self, repo: LinkedInSnapshotRepository) -> None:
        repo.store_snapshot({
            "company_id": 1,
            "linkedin_url": "https://www.linkedin.com/company/test",
            "url_type": "company",
            "content_html": "<html>test content</html>",
            "captured_at": datetime.now(UTC).isoformat(),
        })

        latest = repo.get_latest_snapshot(1, "https://www.linkedin.com/company/test")
        assert latest is not None
        assert latest["content_checksum"] is not None
        assert len(latest["content_checksum"]) == 32  # MD5 hex length

    def test_get_latest_company_snapshot(self, repo: LinkedInSnapshotRepository) -> None:
        repo.store_snapshot({
            "company_id": 1,
            "linkedin_url": "https://www.linkedin.com/company/test",
            "url_type": "company",
            "content_html": "<html>company</html>",
            "captured_at": datetime.now(UTC).isoformat(),
        })
        repo.store_snapshot({
            "company_id": 1,
            "linkedin_url": "https://www.linkedin.com/in/person",
            "url_type": "person",
            "person_name": "Person",
            "content_html": "<html>person</html>",
            "captured_at": datetime.now(UTC).isoformat(),
        })

        latest = repo.get_latest_company_snapshot(1)
        assert latest is not None
        assert latest["url_type"] == "company"

    def test_returns_none_when_no_snapshots(
        self, repo: LinkedInSnapshotRepository
    ) -> None:
        assert repo.get_latest_snapshot(999, "https://example.com") is None
        assert repo.get_latest_company_snapshot(999) is None


# --- Employment Verifier Contract Tests ---


class TestEmploymentVerifierContract:
    """Tests the verifier with mocked CDP browser and LLM client."""

    def test_verify_leader_employed(self, tmp_path: Any) -> None:
        from src.domains.leadership.services.employment_verifier import EmploymentVerifier

        db = Database(db_path=str(tmp_path / "test.db"))
        db.init_db()
        now = datetime.now(UTC).isoformat()
        db.execute(
            """INSERT INTO companies
               (name, homepage_url, source_sheet, flagged_for_review, created_at, updated_at)
               VALUES (?, ?, ?, 0, ?, ?)""",
            ("Test Corp", "https://testcorp.com", "Online Presence", now, now),
        )
        db.connection.commit()

        # Store a leadership record
        from src.domains.leadership.repositories.leadership_repository import (
            LeadershipRepository,
        )

        leadership_repo = LeadershipRepository(db, "test")
        leadership_repo.store_leadership({
            "company_id": 1,
            "person_name": "Jane Smith",
            "title": "CEO",
            "linkedin_profile_url": "https://www.linkedin.com/in/janesmith",
            "discovery_method": "cdp_scrape",
            "confidence": 0.8,
            "is_current": True,
            "discovered_at": now,
            "last_verified_at": now,
        })

        snapshot_repo = LinkedInSnapshotRepository(db, "test")

        # Mock CDP browser
        mock_browser = MagicMock()
        mock_browser.extract_person_profile.return_value = {
            "name": "Jane Smith",
            "headline": "CEO at Test Corp",
            "experience": [
                {"title": "CEO", "company": "Test Corp", "dates": "2020 - Present"},
            ],
        }
        mock_browser.get_page_html.return_value = "<html>profile</html>"
        mock_browser.capture_screenshot.return_value = b"\x89PNG"
        mock_browser.capture_profile_screenshot.return_value = "/tmp/screenshot.png"

        # Mock LLM client
        mock_llm = MagicMock()
        mock_llm.analyze_screenshot.return_value = {
            "person_name": "Jane Smith",
            "current_title": "CEO",
            "current_employer": "Test Corp",
            "is_employed": True,
            "never_employed": False,
            "evidence": "Currently CEO at Test Corp",
        }

        verifier = EmploymentVerifier(
            cdp_browser=mock_browser,
            llm_client=mock_llm,
            leadership_repo=leadership_repo,
            snapshot_repo=snapshot_repo,
        )

        result = verifier.verify_leader(
            company_id=1,
            company_name="Test Corp",
            leader_record={
                "person_name": "Jane Smith",
                "title": "CEO",
                "linkedin_profile_url": "https://www.linkedin.com/in/janesmith",
            },
        )

        assert result["status"] == "employed"
        assert result["change_detected"] is False

    def test_verify_leader_departed(self, tmp_path: Any) -> None:
        from src.domains.leadership.services.employment_verifier import EmploymentVerifier

        db = Database(db_path=str(tmp_path / "test.db"))
        db.init_db()
        now = datetime.now(UTC).isoformat()
        db.execute(
            """INSERT INTO companies
               (name, homepage_url, source_sheet, flagged_for_review, created_at, updated_at)
               VALUES (?, ?, ?, 0, ?, ?)""",
            ("Test Corp", "https://testcorp.com", "Online Presence", now, now),
        )
        db.connection.commit()

        from src.domains.leadership.repositories.leadership_repository import (
            LeadershipRepository,
        )

        leadership_repo = LeadershipRepository(db, "test")
        leadership_repo.store_leadership({
            "company_id": 1,
            "person_name": "Bob Jones",
            "title": "CTO",
            "linkedin_profile_url": "https://www.linkedin.com/in/bobjones",
            "discovery_method": "cdp_scrape",
            "confidence": 0.8,
            "is_current": True,
            "discovered_at": now,
            "last_verified_at": now,
        })

        snapshot_repo = LinkedInSnapshotRepository(db, "test")

        mock_browser = MagicMock()
        mock_browser.extract_person_profile.return_value = {
            "name": "Bob Jones",
            "headline": "VP at Other Co",
            "experience": [],
        }
        mock_browser.get_page_html.return_value = "<html>profile</html>"
        mock_browser.capture_screenshot.return_value = b"\x89PNG"
        mock_browser.capture_profile_screenshot.return_value = "/tmp/screenshot.png"

        mock_llm = MagicMock()
        mock_llm.analyze_screenshot.return_value = {
            "person_name": "Bob Jones",
            "current_title": "VP Engineering",
            "current_employer": "Other Co",
            "is_employed": False,
            "never_employed": False,
            "evidence": "Now VP at Other Co",
        }

        verifier = EmploymentVerifier(
            cdp_browser=mock_browser,
            llm_client=mock_llm,
            leadership_repo=leadership_repo,
            snapshot_repo=snapshot_repo,
        )

        result = verifier.verify_leader(
            company_id=1,
            company_name="Test Corp",
            leader_record={
                "person_name": "Bob Jones",
                "title": "CTO",
                "linkedin_profile_url": "https://www.linkedin.com/in/bobjones",
            },
        )

        assert result["status"] == "departed"
        assert result["change_detected"] is True

        # Verify leader was marked as not current
        leaders = leadership_repo.get_current_leadership(1)
        assert len(leaders) == 0


# --- Leadership Manager Contract Tests ---


class TestLeadershipManagerCDPContract:
    """Tests the LeadershipManager with mocked CDP browser."""

    def test_extract_via_cdp_with_vision(self, tmp_path: Any) -> None:
        from src.domains.leadership.services.leadership_manager import LeadershipManager

        db = Database(db_path=str(tmp_path / "test.db"))
        db.init_db()
        now = datetime.now(UTC).isoformat()
        db.execute(
            """INSERT INTO companies
               (name, homepage_url, source_sheet, flagged_for_review, created_at, updated_at)
               VALUES (?, ?, ?, 0, ?, ?)""",
            ("Test Corp", "https://testcorp.com", "Online Presence", now, now),
        )
        # Insert LinkedIn company link
        db.execute(
            """INSERT INTO social_media_links
               (company_id, platform, profile_url, account_type,
                discovery_method, verification_status, discovered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (1, "linkedin", "https://www.linkedin.com/company/testcorp",
             "company", "homepage_scrape", "unverified", now),
        )
        db.connection.commit()

        from src.domains.discovery.repositories.social_media_link_repository import (
            SocialMediaLinkRepository,
        )
        from src.domains.leadership.repositories.leadership_repository import (
            LeadershipRepository,
        )

        leadership_repo = LeadershipRepository(db, "test")
        social_repo = SocialMediaLinkRepository(db, "test")
        snapshot_repo = LinkedInSnapshotRepository(db, "test")

        from src.repositories.company_repository import CompanyRepository

        company_repo = CompanyRepository(db, "test")

        # Mock browser
        mock_browser = MagicMock()
        mock_browser.extract_people.return_value = [
            {"name": "Jane Smith", "title": "CEO", "profile_url": "https://www.linkedin.com/in/janesmith"},
        ]
        mock_browser.get_page_html.return_value = "<html>people page</html>"
        mock_browser.capture_people_screenshots.return_value = ["/tmp/screenshot.png"]
        mock_browser.delay_between_pages.return_value = None

        # Mock LLM -- returns an additional person from Vision
        mock_llm = MagicMock()
        mock_llm.analyze_screenshot.return_value = {
            "employees": [
                {"name": "Jane Smith", "title": "CEO", "profile_url": "https://www.linkedin.com/in/janesmith"},
                {"name": "Bob Jones", "title": "CTO", "profile_url": "https://www.linkedin.com/in/bobjones"},
            ]
        }

        # Stub search
        mock_search = MagicMock()

        manager = LeadershipManager(
            cdp_browser=mock_browser,
            leadership_search=mock_search,
            leadership_repo=leadership_repo,
            social_link_repo=social_repo,
            company_repo=company_repo,
            llm_client=mock_llm,
            snapshot_repo=snapshot_repo,
        )

        result = manager.extract_company_leadership(1)

        assert result["method_used"] == "cdp_scrape"
        assert result["leaders_found"] >= 1
        assert not result.get("error")
