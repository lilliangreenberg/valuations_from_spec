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


def _insert_company(db: Database, name: str = "TestCo", url: str = "https://test.com") -> int:
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    cursor = db.execute(
        "INSERT INTO companies "
        "(name, homepage_url, source_sheet, created_at, updated_at, performed_by) "
        "VALUES (?, ?, 'test', ?, ?, 'test')",
        (name, url, now, now),
    )
    db.connection.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def _insert_snapshot(db: Database, company_id: int, captured_at: str) -> None:
    db.execute(
        "INSERT INTO snapshots "
        "(company_id, url, content_markdown, content_checksum, captured_at, performed_by) "
        "VALUES (?, 'https://example.com', 'md', ?, ?, 'test')",
        (company_id, "a" * 32, captured_at),
    )
    db.connection.commit()


def _insert_status(
    db: Database,
    company_id: int,
    status: str = "operational",
    is_manual_override: int = 0,
) -> None:
    from datetime import UTC, datetime

    db.execute(
        "INSERT INTO company_statuses "
        "(company_id, status, confidence, indicators, last_checked, "
        "is_manual_override, performed_by) "
        "VALUES (?, ?, 0.9, '[]', ?, ?, 'test')",
        (company_id, status, datetime.now(UTC).isoformat(), is_manual_override),
    )
    db.connection.commit()


class TestCompaniesListFreshnessManuallyClosedFilter:
    def test_manually_closed_freshness_returns_only_manual_closed(
        self, temp_db: Database, query_service: QueryService
    ) -> None:
        from datetime import UTC, datetime

        cid1 = _insert_company(temp_db, name="ManualCo", url="https://manual.com")
        _insert_snapshot(temp_db, cid1, datetime.now(UTC).isoformat())
        _insert_status(temp_db, cid1, status="likely_closed", is_manual_override=1)

        cid2 = _insert_company(temp_db, name="FreshCo", url="https://fresh.com")
        _insert_snapshot(temp_db, cid2, datetime.now(UTC).isoformat())

        result = query_service.get_companies_list(freshness="manually_closed")
        assert result["total"] == 1
        assert result["items"][0]["name"] == "ManualCo"

    def test_auto_likely_closed_not_in_manually_closed(
        self, temp_db: Database, query_service: QueryService
    ) -> None:
        from datetime import UTC, datetime

        cid = _insert_company(temp_db, name="AutoClosed")
        _insert_snapshot(temp_db, cid, datetime.now(UTC).isoformat())
        _insert_status(temp_db, cid, status="likely_closed", is_manual_override=0)

        result = query_service.get_companies_list(freshness="manually_closed")
        assert result["total"] == 0

    def test_recent_freshness_excludes_manually_closed(
        self, temp_db: Database, query_service: QueryService
    ) -> None:
        from datetime import UTC, datetime, timedelta

        # Company with 10-day-old snapshot, manually closed
        cid = _insert_company(temp_db, name="ClosedRecent")
        ten_days_ago = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        _insert_snapshot(temp_db, cid, ten_days_ago)
        _insert_status(temp_db, cid, status="likely_closed", is_manual_override=1)

        # This company would be "recent" by age but is manually closed
        result = query_service.get_companies_list(freshness="recent")
        assert result["total"] == 0


class TestCompaniesListManualOverrideFilter:
    def test_manual_override_yes_returns_only_overrides(
        self, temp_db: Database, query_service: QueryService
    ) -> None:
        cid1 = _insert_company(temp_db, name="ManualOp", url="https://m.com")
        _insert_status(temp_db, cid1, status="operational", is_manual_override=1)

        cid2 = _insert_company(temp_db, name="AutoOp", url="https://a.com")
        _insert_status(temp_db, cid2, status="operational", is_manual_override=0)

        result = query_service.get_companies_list(manual_override="yes")
        assert result["total"] == 1
        assert result["items"][0]["name"] == "ManualOp"

    def test_manual_override_no_returns_auto_detected(
        self, temp_db: Database, query_service: QueryService
    ) -> None:
        cid1 = _insert_company(temp_db, name="ManualOp", url="https://m.com")
        _insert_status(temp_db, cid1, status="operational", is_manual_override=1)

        cid2 = _insert_company(temp_db, name="AutoOp", url="https://a.com")
        _insert_status(temp_db, cid2, status="operational", is_manual_override=0)

        _insert_company(temp_db, name="NoStatus", url="https://n.com")

        result = query_service.get_companies_list(manual_override="no")
        names = [item["name"] for item in result["items"]]
        assert "AutoOp" in names
        assert "NoStatus" in names
        assert "ManualOp" not in names


class TestQueryServiceCompanySummary:
    def test_nonexistent_company_returns_none(self, query_service: QueryService) -> None:
        result = query_service.get_company_summary(99999)
        assert result is None


class TestQueryServiceSourceSheets:
    def test_returns_list(self, query_service: QueryService) -> None:
        sheets = query_service.get_source_sheets()
        assert isinstance(sheets, list)


def _insert_change_record(
    db: Database,
    company_id: int,
    detected_at: str | None = None,
    classification: str = "significant",
    sentiment: str = "negative",
) -> int:
    from datetime import UTC, datetime

    if detected_at is None:
        detected_at = datetime.now(UTC).isoformat()
    # Create two snapshots to satisfy FK constraints
    snap1 = db.execute(
        "INSERT INTO snapshots "
        "(company_id, url, content_markdown, content_checksum, captured_at, performed_by) "
        "VALUES (?, 'https://example.com', 'old', ?, ?, 'test')",
        (company_id, "a" * 32, detected_at),
    ).lastrowid
    snap2 = db.execute(
        "INSERT INTO snapshots "
        "(company_id, url, content_markdown, content_checksum, captured_at, performed_by) "
        "VALUES (?, 'https://example.com', 'new', ?, ?, 'test')",
        (company_id, "b" * 32, detected_at),
    ).lastrowid
    cursor = db.execute(
        "INSERT INTO change_records "
        "(company_id, snapshot_id_old, snapshot_id_new, checksum_old, checksum_new, "
        "has_changed, change_magnitude, detected_at, "
        "significance_classification, significance_sentiment, performed_by) "
        "VALUES (?, ?, ?, ?, ?, 1, 'MAJOR', ?, ?, ?, 'test')",
        (company_id, snap1, snap2, "a" * 32, "b" * 32, detected_at, classification, sentiment),
    )
    db.connection.commit()
    return cursor.lastrowid  # type: ignore[return-value]


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

    def test_groups_by_company(self, temp_db: Database, query_service: QueryService) -> None:
        cid = _insert_company(temp_db, name="GroupCo")
        _insert_change_record(temp_db, cid)
        _insert_change_record(temp_db, cid)

        result = query_service.get_changes_filtered(days=7)
        assert result["total"] == 1  # 1 company, not 2 records
        assert len(result["items"]) == 1
        group = result["items"][0]
        assert group["company_id"] == cid
        assert group["company_name"] == "GroupCo"
        assert group["change_count"] == 2
        assert len(group["changes"]) == 2

    def test_multiple_companies_separate_groups(
        self, temp_db: Database, query_service: QueryService
    ) -> None:
        cid1 = _insert_company(temp_db, name="AlphaCo", url="https://a.com")
        cid2 = _insert_company(temp_db, name="BetaCo", url="https://b.com")
        _insert_change_record(temp_db, cid1)
        _insert_change_record(temp_db, cid2)
        _insert_change_record(temp_db, cid2)

        result = query_service.get_changes_filtered(days=7)
        assert result["total"] == 2
        assert len(result["items"]) == 2
        names = {g["company_name"] for g in result["items"]}
        assert names == {"AlphaCo", "BetaCo"}

    def test_total_reflects_company_count_not_records(
        self, temp_db: Database, query_service: QueryService
    ) -> None:
        cid = _insert_company(temp_db, name="ManyChanges")
        for _ in range(5):
            _insert_change_record(temp_db, cid)

        result = query_service.get_changes_filtered(days=7)
        assert result["total"] == 1
        assert result["items"][0]["change_count"] == 5


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
