"""Contract tests for manually-closed company filtering.

Tests the get_manually_closed_company_ids() repository method and
the exclude_company_ids filtering in service methods.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.domains.monitoring.repositories.company_status_repository import (
    CompanyStatusRepository,
)
from src.services.database import Database


@pytest.fixture()
def db(tmp_path: object) -> Database:
    """Create a fresh database with test companies."""
    import pathlib

    db_path = str(pathlib.Path(str(tmp_path)) / "test.db")
    database = Database(db_path=db_path)
    database.init_db()

    now = datetime.now(UTC).isoformat()
    for i in range(1, 6):
        database.execute(
            "INSERT INTO companies (id, name, homepage_url, source_sheet, created_at, updated_at)"
            " VALUES (?, ?, ?, 'sheet1', ?, ?)",
            (i, f"Company{i}", f"https://company{i}.com", now, now),
        )
    database.connection.commit()
    return database


@pytest.fixture()
def repo(db: Database) -> CompanyStatusRepository:
    return CompanyStatusRepository(db, "test-user")


def _store_status(
    repo: CompanyStatusRepository,
    company_id: int,
    status: str,
    is_manual: bool,
) -> int:
    """Helper to store a status record."""
    return repo.store_status(
        {
            "company_id": company_id,
            "status": status,
            "confidence": 0.9,
            "indicators": [],
            "last_checked": datetime.now(UTC).isoformat(),
            "is_manual_override": is_manual,
        }
    )


class TestGetManuallyClosed:
    """Tests for get_manually_closed_company_ids()."""

    def test_empty_table_returns_empty_set(self, repo: CompanyStatusRepository) -> None:
        result = repo.get_manually_closed_company_ids()
        assert result == set()

    def test_manual_likely_closed_returned(self, repo: CompanyStatusRepository) -> None:
        _store_status(repo, 1, "likely_closed", is_manual=True)
        _store_status(repo, 2, "operational", is_manual=False)

        result = repo.get_manually_closed_company_ids()
        assert result == {1}

    def test_auto_likely_closed_not_returned(self, repo: CompanyStatusRepository) -> None:
        """Auto-detected likely_closed should NOT be excluded."""
        _store_status(repo, 1, "likely_closed", is_manual=False)

        result = repo.get_manually_closed_company_ids()
        assert result == set()

    def test_manual_operational_not_returned(self, repo: CompanyStatusRepository) -> None:
        """Manual override to operational should NOT be excluded."""
        _store_status(repo, 1, "operational", is_manual=True)

        result = repo.get_manually_closed_company_ids()
        assert result == set()

    def test_manual_uncertain_not_returned(self, repo: CompanyStatusRepository) -> None:
        """Manual override to uncertain should NOT be excluded."""
        _store_status(repo, 1, "uncertain", is_manual=True)

        result = repo.get_manually_closed_company_ids()
        assert result == set()

    def test_latest_status_wins(self, repo: CompanyStatusRepository) -> None:
        """If company was manually closed then set to operational, NOT excluded."""
        _store_status(repo, 1, "likely_closed", is_manual=True)
        _store_status(repo, 1, "operational", is_manual=False)

        result = repo.get_manually_closed_company_ids()
        assert result == set()

    def test_latest_status_wins_reverse(self, repo: CompanyStatusRepository) -> None:
        """If company was operational then manually closed, IS excluded."""
        _store_status(repo, 1, "operational", is_manual=False)
        _store_status(repo, 1, "likely_closed", is_manual=True)

        result = repo.get_manually_closed_company_ids()
        assert result == {1}

    def test_multiple_companies_mixed(self, repo: CompanyStatusRepository) -> None:
        """Multiple companies with various statuses."""
        _store_status(repo, 1, "likely_closed", is_manual=True)
        _store_status(repo, 2, "likely_closed", is_manual=False)
        _store_status(repo, 3, "operational", is_manual=True)
        _store_status(repo, 4, "likely_closed", is_manual=True)
        _store_status(repo, 5, "uncertain", is_manual=False)

        result = repo.get_manually_closed_company_ids()
        assert result == {1, 4}


class TestExcludeCompanyIdsFiltering:
    """Tests that service-level exclude_company_ids filtering works correctly."""

    def test_change_detector_excludes_companies(self) -> None:
        """ChangeDetector.detect_all_changes filters out excluded IDs."""
        from unittest.mock import MagicMock

        from src.domains.monitoring.services.change_detector import ChangeDetector

        snapshot_repo = MagicMock()
        snapshot_repo.get_companies_with_multiple_snapshots.return_value = [1, 2, 3, 4, 5]
        snapshot_repo.get_latest_snapshots.return_value = []  # Will cause skip

        change_repo = MagicMock()
        company_repo = MagicMock()
        company_repo.get_company_by_id.return_value = {"id": 1, "name": "Test", "homepage_url": ""}

        detector = ChangeDetector(snapshot_repo, change_repo, company_repo)
        _result = detector.detect_all_changes(exclude_company_ids={2, 4})

        # Companies 2 and 4 should not have been processed
        processed_ids = [call.args[0] for call in snapshot_repo.get_latest_snapshots.call_args_list]
        assert 2 not in processed_ids
        assert 4 not in processed_ids
        assert 1 in processed_ids
        assert 3 in processed_ids
        assert 5 in processed_ids

    def test_social_media_discovery_excludes_companies(self) -> None:
        """SocialMediaDiscovery.discover_all filters out excluded IDs."""
        from unittest.mock import MagicMock

        from src.domains.discovery.services.social_media_discovery import SocialMediaDiscovery

        firecrawl = MagicMock()
        firecrawl.batch_capture_snapshots.return_value = []
        social_repo = MagicMock()
        company_repo = MagicMock()
        company_repo.get_companies_with_homepage.return_value = [
            {"id": 1, "name": "Co1", "homepage_url": "https://co1.com"},
            {"id": 2, "name": "Co2", "homepage_url": "https://co2.com"},
            {"id": 3, "name": "Co3", "homepage_url": "https://co3.com"},
        ]

        discovery = SocialMediaDiscovery(firecrawl, social_repo, company_repo)
        _result = discovery.discover_all(exclude_company_ids={2})

        # The batch should not include company 2's URL
        if firecrawl.batch_capture_snapshots.called:
            urls_arg = firecrawl.batch_capture_snapshots.call_args[0][0]
            assert "https://co2.com" not in urls_arg

    def test_news_monitor_excludes_companies(self) -> None:
        """NewsMonitorManager.search_all_companies filters out excluded IDs."""
        from unittest.mock import MagicMock

        from src.domains.news.services.news_monitor_manager import NewsMonitorManager

        kagi = MagicMock()
        kagi.search.return_value = {"data": []}
        news_repo = MagicMock()
        news_repo.check_duplicate_news_url.return_value = False
        company_repo = MagicMock()
        company_repo.get_all_companies.return_value = [
            {"id": 1, "name": "Co1", "homepage_url": "https://co1.com"},
            {"id": 2, "name": "Co2", "homepage_url": "https://co2.com"},
        ]
        snapshot_repo = MagicMock()
        snapshot_repo.get_latest_snapshots.return_value = []

        manager = NewsMonitorManager(kagi, news_repo, company_repo, snapshot_repo)
        result = manager.search_all_companies(exclude_company_ids={2})

        # Only 1 company should have been processed (company 2 excluded)
        assert result["processed"] == 1

    def test_social_change_detector_excludes_companies(self) -> None:
        """SocialChangeDetector.detect_all_changes filters out excluded IDs."""
        from unittest.mock import MagicMock

        from src.domains.monitoring.services.social_change_detector import SocialChangeDetector

        social_snapshot_repo = MagicMock()
        social_snapshot_repo.get_companies_with_multiple_snapshots.return_value = [
            (1, "https://medium.com/@co1"),
            (2, "https://medium.com/@co2"),
            (3, "https://medium.com/@co3"),
        ]
        social_snapshot_repo.get_latest_snapshots.return_value = []

        social_change_repo = MagicMock()
        company_repo = MagicMock()
        company_repo.get_company_by_id.return_value = {"id": 1, "name": "Test"}

        detector = SocialChangeDetector(social_snapshot_repo, social_change_repo, company_repo)
        _result = detector.detect_all_changes(exclude_company_ids={2})

        # Company 2 should not have been processed
        processed_ids = [
            call.args[0] for call in social_snapshot_repo.get_latest_snapshots.call_args_list
        ]
        assert 2 not in processed_ids

    def test_empty_exclude_set_processes_all(self) -> None:
        """Empty exclude set should not filter anything."""
        from unittest.mock import MagicMock

        from src.domains.monitoring.services.change_detector import ChangeDetector

        snapshot_repo = MagicMock()
        snapshot_repo.get_companies_with_multiple_snapshots.return_value = [1, 2, 3]
        snapshot_repo.get_latest_snapshots.return_value = []

        change_repo = MagicMock()
        company_repo = MagicMock()
        company_repo.get_company_by_id.return_value = {"id": 1, "name": "Test", "homepage_url": ""}

        detector = ChangeDetector(snapshot_repo, change_repo, company_repo)
        _result = detector.detect_all_changes(exclude_company_ids=set())

        assert snapshot_repo.get_latest_snapshots.call_count == 3

    def test_none_exclude_set_processes_all(self) -> None:
        """None exclude set should not filter anything."""
        from unittest.mock import MagicMock

        from src.domains.monitoring.services.change_detector import ChangeDetector

        snapshot_repo = MagicMock()
        snapshot_repo.get_companies_with_multiple_snapshots.return_value = [1, 2, 3]
        snapshot_repo.get_latest_snapshots.return_value = []

        change_repo = MagicMock()
        company_repo = MagicMock()
        company_repo.get_company_by_id.return_value = {"id": 1, "name": "Test", "homepage_url": ""}

        detector = ChangeDetector(snapshot_repo, change_repo, company_repo)
        _result = detector.detect_all_changes(exclude_company_ids=None)

        assert snapshot_repo.get_latest_snapshots.call_count == 3
