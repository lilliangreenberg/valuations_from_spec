"""Contract tests for widget-specific QueryService methods.

Tests with a temp database to verify SQL correctness.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta

import pytest

from src.domains.dashboard.services.query_service import QueryService
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


def _insert_company(db: Database, name: str = "TestCo", flagged: bool = False) -> int:
    """Insert a test company and return its ID."""
    now = datetime.now(UTC).isoformat()
    cursor = db.execute(
        "INSERT INTO companies "
        "(name, homepage_url, source_sheet, flagged_for_review, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, f"https://{name.lower().replace(' ', '')}.com", "Sheet1", int(flagged), now, now),
    )
    db.connection.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def _insert_snapshot(db: Database, company_id: int, captured_at: str | None = None) -> int:
    """Insert a test snapshot and return its ID."""
    if captured_at is None:
        captured_at = datetime.now(UTC).isoformat()
    cursor = db.execute(
        "INSERT INTO snapshots (company_id, url, content_markdown, captured_at, content_checksum) "
        "VALUES (?, ?, ?, ?, ?)",
        (company_id, "https://example.com", "content", captured_at, "a" * 32),
    )
    db.connection.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def _insert_change_record(
    db: Database,
    company_id: int,
    snap_old: int,
    snap_new: int,
    magnitude: str = "minor",
    classification: str | None = None,
    sentiment: str | None = None,
    detected_at: str | None = None,
) -> int:
    """Insert a test change record and return its ID."""
    if detected_at is None:
        detected_at = datetime.now(UTC).isoformat()
    cursor = db.execute(
        """INSERT INTO change_records
           (company_id, snapshot_id_old, snapshot_id_new, checksum_old, checksum_new,
            has_changed, change_magnitude, detected_at,
            significance_classification, significance_sentiment)
           VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
        (
            company_id,
            snap_old,
            snap_new,
            "a" * 32,
            "b" * 32,
            magnitude,
            detected_at,
            classification,
            sentiment,
        ),
    )
    db.connection.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def _insert_status(
    db: Database,
    company_id: int,
    status: str = "operational",
    is_manual_override: int = 0,
) -> None:
    """Insert a company status."""
    db.execute(
        "INSERT INTO company_statuses "
        "(company_id, status, confidence, indicators, last_checked, is_manual_override) "
        "VALUES (?, ?, 0.9, '[]', ?, ?)",
        (company_id, status, datetime.now(UTC).isoformat(), is_manual_override),
    )
    db.connection.commit()


class TestGetChangesSinceLastScan:
    def test_empty_db_returns_zeros(self, query_service: QueryService) -> None:
        result = query_service.get_changes_since_last_scan()
        assert result["total_changes"] == 0
        assert result["scan_date"] is None

    def test_returns_expected_keys(self, query_service: QueryService) -> None:
        result = query_service.get_changes_since_last_scan()
        assert "total_changes" in result
        assert "scan_date" in result
        assert "by_magnitude" in result
        assert "by_significance" in result

    def test_with_data(self, temp_db: Database, query_service: QueryService) -> None:
        cid = _insert_company(temp_db)
        yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        today = datetime.now(UTC).isoformat()
        s1 = _insert_snapshot(temp_db, cid, captured_at=yesterday)
        s2 = _insert_snapshot(temp_db, cid, captured_at=today)
        _insert_change_record(
            temp_db,
            cid,
            s1,
            s2,
            magnitude="major",
            classification="significant",
            detected_at=today,
        )

        result = query_service.get_changes_since_last_scan()
        assert result["total_changes"] >= 1
        assert result["by_magnitude"]["major"] >= 1
        assert result["by_significance"]["significant"] >= 1

    def test_magnitude_breakdown_has_all_keys(self, query_service: QueryService) -> None:
        result = query_service.get_changes_since_last_scan()
        for key in ("minor", "moderate", "major"):
            assert key in result["by_magnitude"]

    def test_significance_breakdown_has_all_keys(self, query_service: QueryService) -> None:
        result = query_service.get_changes_since_last_scan()
        for key in ("significant", "insignificant", "uncertain"):
            assert key in result["by_significance"]


class TestGetAlertsSummary:
    def test_empty_db_returns_zeros(self, query_service: QueryService) -> None:
        result = query_service.get_alerts_summary()
        assert result["negative_significant_count"] == 0
        assert result["uncertain_count"] == 0
        assert result["total_alerts"] == 0
        assert result["flagged_companies"] == []

    def test_returns_expected_keys(self, query_service: QueryService) -> None:
        result = query_service.get_alerts_summary()
        assert "negative_significant_count" in result
        assert "uncertain_count" in result
        assert "flagged_companies" in result
        assert "total_alerts" in result

    def test_counts_negative_significant(
        self, temp_db: Database, query_service: QueryService
    ) -> None:
        cid = _insert_company(temp_db)
        s1 = _insert_snapshot(temp_db, cid)
        s2 = _insert_snapshot(temp_db, cid)
        _insert_change_record(
            temp_db,
            cid,
            s1,
            s2,
            classification="significant",
            sentiment="negative",
        )
        result = query_service.get_alerts_summary()
        assert result["negative_significant_count"] == 1

    def test_counts_uncertain(self, temp_db: Database, query_service: QueryService) -> None:
        cid = _insert_company(temp_db)
        s1 = _insert_snapshot(temp_db, cid)
        s2 = _insert_snapshot(temp_db, cid)
        _insert_change_record(temp_db, cid, s1, s2, classification="uncertain")
        result = query_service.get_alerts_summary()
        assert result["uncertain_count"] == 1

    def test_includes_flagged_companies(
        self, temp_db: Database, query_service: QueryService
    ) -> None:
        _insert_company(temp_db, name="Flagged Corp", flagged=True)
        result = query_service.get_alerts_summary()
        assert len(result["flagged_companies"]) == 1
        assert result["flagged_companies"][0]["name"] == "Flagged Corp"

    def test_total_alerts_is_sum(self, temp_db: Database, query_service: QueryService) -> None:
        cid = _insert_company(temp_db, name="TestCo1", flagged=True)
        s1 = _insert_snapshot(temp_db, cid)
        s2 = _insert_snapshot(temp_db, cid)
        s3 = _insert_snapshot(temp_db, cid)
        _insert_change_record(
            temp_db,
            cid,
            s1,
            s2,
            classification="significant",
            sentiment="negative",
        )
        _insert_change_record(
            temp_db,
            cid,
            s2,
            s3,
            classification="uncertain",
        )
        result = query_service.get_alerts_summary()
        expected = (
            result["negative_significant_count"]
            + result["uncertain_count"]
            + len(result["flagged_companies"])
        )
        assert result["total_alerts"] == expected


class TestGetTrendingData:
    def test_empty_db_returns_empty_lists(self, query_service: QueryService) -> None:
        result = query_service.get_trending_data(weeks=4)
        assert len(result["labels"]) == 4
        assert len(result["significant_changes"]) == 4
        assert len(result["news_articles"]) == 4
        assert len(result["leadership_discoveries"]) == 4

    def test_returns_expected_keys(self, query_service: QueryService) -> None:
        result = query_service.get_trending_data()
        assert "labels" in result
        assert "significant_changes" in result
        assert "news_articles" in result
        assert "leadership_discoveries" in result

    def test_default_weeks_is_12(self, query_service: QueryService) -> None:
        result = query_service.get_trending_data()
        assert len(result["labels"]) == 12

    def test_all_zeros_with_no_data(self, query_service: QueryService) -> None:
        result = query_service.get_trending_data(weeks=4)
        assert all(v == 0 for v in result["significant_changes"])
        assert all(v == 0 for v in result["news_articles"])
        assert all(v == 0 for v in result["leadership_discoveries"])


class TestGetSnapshotFreshness:
    def test_empty_db_returns_empty(self, query_service: QueryService) -> None:
        result = query_service.get_snapshot_freshness()
        assert "summary" in result
        assert "companies_by_tier" in result
        # No companies -> all counts should be 0
        assert sum(result["summary"].values()) == 0

    def test_returns_all_tiers(self, query_service: QueryService) -> None:
        result = query_service.get_snapshot_freshness()
        for tier in ("fresh", "recent", "stale", "very_stale", "never_scanned", "manually_closed"):
            assert tier in result["summary"]
            assert tier in result["companies_by_tier"]

    def test_company_with_no_snapshot_is_never_scanned(
        self, temp_db: Database, query_service: QueryService
    ) -> None:
        _insert_company(temp_db)
        result = query_service.get_snapshot_freshness()
        assert result["summary"]["never_scanned"] == 1

    def test_company_with_recent_snapshot_is_fresh(
        self, temp_db: Database, query_service: QueryService
    ) -> None:
        cid = _insert_company(temp_db)
        _insert_snapshot(temp_db, cid, captured_at=datetime.now(UTC).isoformat())
        result = query_service.get_snapshot_freshness()
        assert result["summary"]["fresh"] == 1

    def test_company_in_companies_by_tier(
        self, temp_db: Database, query_service: QueryService
    ) -> None:
        cid = _insert_company(temp_db, name="FreshCo")
        _insert_snapshot(temp_db, cid, captured_at=datetime.now(UTC).isoformat())
        result = query_service.get_snapshot_freshness()
        fresh_companies = result["companies_by_tier"]["fresh"]
        assert any(c["name"] == "FreshCo" for c in fresh_companies)

    def test_manually_closed_company_excluded_from_regular_tiers(
        self, temp_db: Database, query_service: QueryService
    ) -> None:
        cid = _insert_company(temp_db, name="ClosedCo")
        _insert_snapshot(temp_db, cid, captured_at=datetime.now(UTC).isoformat())
        _insert_status(temp_db, cid, status="likely_closed", is_manual_override=1)
        result = query_service.get_snapshot_freshness()
        assert result["summary"]["manually_closed"] == 1
        assert result["summary"]["fresh"] == 0
        assert any(c["name"] == "ClosedCo" for c in result["companies_by_tier"]["manually_closed"])

    def test_auto_likely_closed_stays_in_regular_tiers(
        self, temp_db: Database, query_service: QueryService
    ) -> None:
        cid = _insert_company(temp_db, name="AutoClosedCo")
        _insert_snapshot(temp_db, cid, captured_at=datetime.now(UTC).isoformat())
        _insert_status(temp_db, cid, status="likely_closed", is_manual_override=0)
        result = query_service.get_snapshot_freshness()
        assert result["summary"]["fresh"] == 1
        assert result["summary"]["manually_closed"] == 0


class TestGetCompanyHealthGrid:
    def test_empty_db_returns_empty_list(self, query_service: QueryService) -> None:
        result = query_service.get_company_health_grid()
        assert result == []

    def test_returns_list_of_dicts(self, temp_db: Database, query_service: QueryService) -> None:
        _insert_company(temp_db)
        result = query_service.get_company_health_grid()
        assert isinstance(result, list)
        assert len(result) == 1
        assert "id" in result[0]
        assert "name" in result[0]
        assert "status" in result[0]

    def test_company_without_status_is_unknown(
        self, temp_db: Database, query_service: QueryService
    ) -> None:
        _insert_company(temp_db)
        result = query_service.get_company_health_grid()
        assert result[0]["status"] == "unknown"

    def test_company_with_status(self, temp_db: Database, query_service: QueryService) -> None:
        cid = _insert_company(temp_db)
        _insert_status(temp_db, cid, "operational")
        result = query_service.get_company_health_grid()
        assert result[0]["status"] == "operational"

    def test_sorted_by_name(self, temp_db: Database, query_service: QueryService) -> None:
        _insert_company(temp_db, name="Zeta Corp")
        _insert_company(temp_db, name="Alpha Inc")
        result = query_service.get_company_health_grid()
        names = [r["name"] for r in result]
        assert names == sorted(names)
