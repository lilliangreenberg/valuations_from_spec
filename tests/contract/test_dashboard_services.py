"""Contract tests for dashboard services.

Tests QueryService with a temp database, and TaskRunner basics.
"""

from __future__ import annotations

import tempfile

import pytest

from src.domains.dashboard.services.query_service import QueryService
from src.domains.dashboard.services.task_runner import (
    ALLOWED_COMMANDS,
    TaskRunner,
)
from src.services.database import Database


@pytest.fixture()
def temp_db() -> Database:
    """Create a temporary database with schema initialized."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = Database(db_path=db_path)
    db.init_db()
    return db


@pytest.fixture()
def query_service(temp_db: Database) -> QueryService:
    return QueryService(temp_db)


@pytest.fixture()
def task_runner() -> TaskRunner:
    return TaskRunner(max_concurrent=2)


class TestQueryServiceOverviewStats:
    def test_returns_dict_with_expected_keys(self, query_service: QueryService) -> None:
        stats = query_service.get_overview_stats()
        assert "total_companies" in stats
        assert "last_scan_date" in stats
        assert "recent_changes" in stats
        assert "significant_changes" in stats

    def test_empty_db_returns_zeros(self, query_service: QueryService) -> None:
        stats = query_service.get_overview_stats()
        assert stats["total_companies"] == 0
        assert stats["recent_changes"] == 0
        assert stats["significant_changes"] == 0

    def test_status_counts_present(self, query_service: QueryService) -> None:
        stats = query_service.get_overview_stats()
        assert "status_counts" in stats
        assert isinstance(stats["status_counts"], dict)


class TestQueryServiceActivityFeed:
    def test_returns_list(self, query_service: QueryService) -> None:
        activity = query_service.get_activity_feed()
        assert isinstance(activity, list)

    def test_empty_db_returns_empty_list(self, query_service: QueryService) -> None:
        activity = query_service.get_activity_feed()
        assert activity == []

    def test_respects_limit(self, query_service: QueryService) -> None:
        activity = query_service.get_activity_feed(limit=5)
        assert len(activity) <= 5


class TestQueryServiceCompaniesList:
    def test_returns_dict_with_pagination(self, query_service: QueryService) -> None:
        result = query_service.get_companies_list()
        assert "items" in result
        assert "total" in result
        assert "page" in result
        assert "per_page" in result
        assert "total_pages" in result

    def test_empty_db_returns_empty_items(self, query_service: QueryService) -> None:
        result = query_service.get_companies_list()
        assert result["items"] == []
        assert result["total"] == 0

    def test_pagination_defaults(self, query_service: QueryService) -> None:
        result = query_service.get_companies_list()
        assert result["page"] == 1
        assert result["per_page"] == 50


class TestQueryServiceCompanySummary:
    def test_nonexistent_company_returns_none(self, query_service: QueryService) -> None:
        result = query_service.get_company_summary(99999)
        assert result is None


class TestQueryServiceSourceSheets:
    def test_returns_list(self, query_service: QueryService) -> None:
        sheets = query_service.get_source_sheets()
        assert isinstance(sheets, list)


class TestQueryServiceChangesFiltered:
    def test_returns_paginated_dict(self, query_service: QueryService) -> None:
        result = query_service.get_changes_filtered()
        assert "items" in result
        assert "total" in result
        assert "page" in result

    def test_empty_db(self, query_service: QueryService) -> None:
        result = query_service.get_changes_filtered()
        assert result["items"] == []
        assert result["total"] == 0


class TestQueryServiceNewsFiltered:
    def test_returns_paginated_dict(self, query_service: QueryService) -> None:
        result = query_service.get_news_filtered()
        assert "items" in result
        assert "total" in result

    def test_empty_db(self, query_service: QueryService) -> None:
        result = query_service.get_news_filtered()
        assert result["items"] == []


class TestQueryServiceLeadershipOverview:
    def test_returns_paginated_dict(self, query_service: QueryService) -> None:
        result = query_service.get_leadership_overview()
        assert "items" in result
        assert "total" in result

    def test_empty_db(self, query_service: QueryService) -> None:
        result = query_service.get_leadership_overview()
        assert result["items"] == []


class TestTaskRunnerAllowedCommands:
    def test_all_commands_have_description(self) -> None:
        for cmd_name, cmd_def in ALLOWED_COMMANDS.items():
            assert "description" in cmd_def, f"{cmd_name} missing description"

    def test_all_commands_have_group(self) -> None:
        for cmd_name, cmd_def in ALLOWED_COMMANDS.items():
            assert "group" in cmd_def, f"{cmd_name} missing group"

    def test_all_commands_have_args(self) -> None:
        for cmd_name, cmd_def in ALLOWED_COMMANDS.items():
            assert "args" in cmd_def, f"{cmd_name} missing args"
            assert isinstance(cmd_def["args"], list)


class TestTaskRunnerBasics:
    def test_init(self, task_runner: TaskRunner) -> None:
        assert task_runner.max_concurrent == 2

    def test_get_running_count_initially_zero(self, task_runner: TaskRunner) -> None:
        assert task_runner.get_running_count() == 0

    def test_get_task_history_initially_empty(self, task_runner: TaskRunner) -> None:
        assert task_runner.get_task_history() == []

    def test_get_nonexistent_task_returns_none(self, task_runner: TaskRunner) -> None:
        assert task_runner.get_task("nonexistent") is None
