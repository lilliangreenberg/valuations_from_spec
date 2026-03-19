"""Contract tests for SocialSnapshotRepository and SocialChangeRecordRepository.

Uses a REAL temporary SQLite database (no mocking the DB), but does not call
external APIs. Tests verify the repository layer against the actual schema.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.domains.monitoring.repositories.social_change_record_repository import (
    SocialChangeRecordRepository,
)
from src.domains.monitoring.repositories.social_snapshot_repository import (
    SocialSnapshotRepository,
)
from src.services.database import Database

# Type alias
DbWithCompany = tuple[Database, int]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _past_iso(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _make_social_snapshot(
    company_id: int,
    source_url: str = "https://medium.com/@testco",
    source_type: str = "medium",
    captured_at: str | None = None,
    content: str = "# Blog Post\n\nSome content.",
    checksum: str = "abc123def456",
    latest_post_date: str | None = None,
) -> dict[str, Any]:
    return {
        "company_id": company_id,
        "source_url": source_url,
        "source_type": source_type,
        "content_markdown": content,
        "content_html": "<h1>Blog Post</h1><p>Some content.</p>",
        "status_code": 200,
        "captured_at": captured_at or _now_iso(),
        "error_message": None,
        "content_checksum": checksum,
        "latest_post_date": latest_post_date,
    }


# ---------------------------------------------------------------------------
# SocialSnapshotRepository tests
# ---------------------------------------------------------------------------


class TestSocialSnapshotRepository:
    """Contract tests for SocialSnapshotRepository."""

    def test_store_and_retrieve_snapshot(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SocialSnapshotRepository(db, "test-user")

        data = _make_social_snapshot(company_id, latest_post_date="2025-06-01")
        snapshot_id = repo.store_snapshot(data)

        assert snapshot_id > 0
        rows = repo.get_latest_snapshots(company_id, "https://medium.com/@testco")
        assert len(rows) == 1
        assert rows[0]["source_type"] == "medium"
        assert rows[0]["content_checksum"] == "abc123def456"
        assert rows[0]["latest_post_date"] == "2025-06-01"

    def test_accumulates_history(self, db_with_company: DbWithCompany) -> None:
        """Multiple snapshots for the same source URL accumulate (no unique constraint)."""
        db, company_id = db_with_company
        repo = SocialSnapshotRepository(db, "test-user")

        snap1 = _make_social_snapshot(company_id, captured_at=_past_iso(2), checksum="aaa")
        snap2 = _make_social_snapshot(company_id, captured_at=_past_iso(1), checksum="bbb")
        snap3 = _make_social_snapshot(company_id, captured_at=_now_iso(), checksum="ccc")
        repo.store_snapshot(snap1)
        repo.store_snapshot(snap2)
        repo.store_snapshot(snap3)

        rows = repo.get_latest_snapshots(company_id, "https://medium.com/@testco", limit=2)
        assert len(rows) == 2
        # Most recent first
        assert rows[0]["content_checksum"] == "ccc"
        assert rows[1]["content_checksum"] == "bbb"

    def test_get_latest_snapshots_filters_by_source_url(
        self, db_with_company: DbWithCompany
    ) -> None:
        db, company_id = db_with_company
        repo = SocialSnapshotRepository(db, "test-user")

        repo.store_snapshot(_make_social_snapshot(company_id, source_url="https://medium.com/@co"))
        repo.store_snapshot(
            _make_social_snapshot(company_id, source_url="https://co.com/blog", source_type="blog")
        )

        medium_rows = repo.get_latest_snapshots(company_id, "https://medium.com/@co")
        blog_rows = repo.get_latest_snapshots(company_id, "https://co.com/blog")
        assert len(medium_rows) == 1
        assert len(blog_rows) == 1

    def test_get_all_sources_for_company(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SocialSnapshotRepository(db, "test-user")

        # Two sources, each with 2 snapshots
        repo.store_snapshot(
            _make_social_snapshot(
                company_id,
                source_url="https://medium.com/@co",
                captured_at=_past_iso(2),
                checksum="old_m",
            )
        )
        repo.store_snapshot(
            _make_social_snapshot(
                company_id,
                source_url="https://medium.com/@co",
                captured_at=_now_iso(),
                checksum="new_m",
            )
        )
        repo.store_snapshot(
            _make_social_snapshot(
                company_id,
                source_url="https://co.com/blog",
                source_type="blog",
                captured_at=_past_iso(1),
                checksum="old_b",
            )
        )
        repo.store_snapshot(
            _make_social_snapshot(
                company_id,
                source_url="https://co.com/blog",
                source_type="blog",
                captured_at=_now_iso(),
                checksum="new_b",
            )
        )

        sources = repo.get_all_sources_for_company(company_id)
        assert len(sources) == 2
        # Should return only the latest snapshot per source
        checksums = {s["content_checksum"] for s in sources}
        assert "new_m" in checksums
        assert "new_b" in checksums

    def test_get_companies_with_multiple_snapshots(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SocialSnapshotRepository(db, "test-user")

        # Only one snapshot -- should NOT appear
        repo.store_snapshot(
            _make_social_snapshot(
                company_id,
                source_url="https://medium.com/@single",
                checksum="only",
            )
        )

        # Two snapshots -- should appear
        repo.store_snapshot(
            _make_social_snapshot(
                company_id,
                source_url="https://co.com/blog",
                source_type="blog",
                captured_at=_past_iso(1),
                checksum="first",
            )
        )
        repo.store_snapshot(
            _make_social_snapshot(
                company_id,
                source_url="https://co.com/blog",
                source_type="blog",
                captured_at=_now_iso(),
                checksum="second",
            )
        )

        pairs = repo.get_companies_with_multiple_snapshots()
        assert len(pairs) == 1
        assert pairs[0] == (company_id, "https://co.com/blog")

    def test_error_snapshot(self, db_with_company: DbWithCompany) -> None:
        """Snapshots with errors can be stored."""
        db, company_id = db_with_company
        repo = SocialSnapshotRepository(db, "test-user")

        data = _make_social_snapshot(company_id)
        data["status_code"] = 500
        data["error_message"] = "Internal server error"
        data["content_markdown"] = None
        data["content_html"] = None
        data["content_checksum"] = None

        snapshot_id = repo.store_snapshot(data)
        assert snapshot_id > 0

        rows = repo.get_latest_snapshots(company_id, "https://medium.com/@testco")
        assert rows[0]["error_message"] == "Internal server error"
        assert rows[0]["content_markdown"] is None


# ---------------------------------------------------------------------------
# SocialChangeRecordRepository tests
# ---------------------------------------------------------------------------


class TestSocialChangeRecordRepository:
    """Contract tests for SocialChangeRecordRepository."""

    def _insert_two_snapshots(self, db: Database, company_id: int) -> tuple[int, int]:
        """Insert two social snapshots and return their IDs."""
        snap_repo = SocialSnapshotRepository(db, "test-user")
        id_old = snap_repo.store_snapshot(
            _make_social_snapshot(company_id, captured_at=_past_iso(1), checksum="old_hash")
        )
        id_new = snap_repo.store_snapshot(
            _make_social_snapshot(company_id, captured_at=_now_iso(), checksum="new_hash")
        )
        return id_old, id_new

    def test_store_and_retrieve_change_record(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SocialChangeRecordRepository(db, "test-user")
        snap_old, snap_new = self._insert_two_snapshots(db, company_id)

        record_id = repo.store_change_record(
            {
                "company_id": company_id,
                "source_url": "https://medium.com/@testco",
                "source_type": "medium",
                "snapshot_id_old": snap_old,
                "snapshot_id_new": snap_new,
                "checksum_old": "old_hash",
                "checksum_new": "new_hash",
                "has_changed": True,
                "change_magnitude": "moderate",
                "detected_at": _now_iso(),
                "significance_classification": "significant",
                "significance_sentiment": "positive",
                "significance_confidence": 0.85,
                "matched_keywords": ["funding", "growth"],
                "matched_categories": ["funding_investment"],
                "significance_notes": "Funding round detected",
                "evidence_snippets": ["raised $10M"],
            }
        )

        assert record_id > 0
        changes = repo.get_changes_for_company(company_id)
        assert len(changes) == 1
        assert changes[0]["source_url"] == "https://medium.com/@testco"
        assert changes[0]["significance_classification"] == "significant"
        assert changes[0]["matched_keywords"] == ["funding", "growth"]
        assert changes[0]["evidence_snippets"] == ["raised $10M"]

    def test_get_significant_changes(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SocialChangeRecordRepository(db, "test-user")
        snap_old, snap_new = self._insert_two_snapshots(db, company_id)

        # Significant change
        repo.store_change_record(
            {
                "company_id": company_id,
                "source_url": "https://medium.com/@testco",
                "source_type": "medium",
                "snapshot_id_old": snap_old,
                "snapshot_id_new": snap_new,
                "checksum_old": "old_hash",
                "checksum_new": "new_hash",
                "has_changed": True,
                "change_magnitude": "moderate",
                "detected_at": _now_iso(),
                "significance_classification": "significant",
                "significance_sentiment": "negative",
                "significance_confidence": 0.90,
                "matched_keywords": ["layoffs"],
                "matched_categories": ["layoffs_downsizing"],
            }
        )

        # Insignificant change (should not appear)
        snap_old2 = SocialSnapshotRepository(db, "test-user").store_snapshot(
            _make_social_snapshot(
                company_id,
                source_url="https://co.com/blog",
                source_type="blog",
                captured_at=_past_iso(3),
                checksum="aaa",
            )
        )
        snap_new2 = SocialSnapshotRepository(db, "test-user").store_snapshot(
            _make_social_snapshot(
                company_id,
                source_url="https://co.com/blog",
                source_type="blog",
                captured_at=_past_iso(2),
                checksum="bbb",
            )
        )
        repo.store_change_record(
            {
                "company_id": company_id,
                "source_url": "https://co.com/blog",
                "source_type": "blog",
                "snapshot_id_old": snap_old2,
                "snapshot_id_new": snap_new2,
                "checksum_old": "aaa",
                "checksum_new": "bbb",
                "has_changed": True,
                "change_magnitude": "minor",
                "detected_at": _now_iso(),
                "significance_classification": "insignificant",
                "significance_sentiment": "neutral",
                "significance_confidence": 0.80,
            }
        )

        results = repo.get_significant_changes(days=30)
        assert len(results) == 1
        assert results[0]["significance_classification"] == "significant"
        assert results[0]["company_name"] == "Test Corp"

    def test_get_significant_changes_sentiment_filter(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SocialChangeRecordRepository(db, "test-user")
        snap_old, snap_new = self._insert_two_snapshots(db, company_id)

        repo.store_change_record(
            {
                "company_id": company_id,
                "source_url": "https://medium.com/@testco",
                "source_type": "medium",
                "snapshot_id_old": snap_old,
                "snapshot_id_new": snap_new,
                "checksum_old": "old_hash",
                "checksum_new": "new_hash",
                "has_changed": True,
                "change_magnitude": "moderate",
                "detected_at": _now_iso(),
                "significance_classification": "significant",
                "significance_sentiment": "positive",
                "significance_confidence": 0.85,
            }
        )

        pos = repo.get_significant_changes(days=30, sentiment="positive")
        neg = repo.get_significant_changes(days=30, sentiment="negative")
        assert len(pos) == 1
        assert len(neg) == 0

    def test_json_deserialization(self, db_with_company: DbWithCompany) -> None:
        """JSON fields are properly deserialized from the database."""
        db, company_id = db_with_company
        repo = SocialChangeRecordRepository(db, "test-user")
        snap_old, snap_new = self._insert_two_snapshots(db, company_id)

        repo.store_change_record(
            {
                "company_id": company_id,
                "source_url": "https://medium.com/@testco",
                "source_type": "medium",
                "snapshot_id_old": snap_old,
                "snapshot_id_new": snap_new,
                "checksum_old": "old_hash",
                "checksum_new": "new_hash",
                "has_changed": True,
                "change_magnitude": "minor",
                "detected_at": _now_iso(),
                "matched_keywords": ["keyword1", "keyword2"],
                "matched_categories": ["cat1"],
                "evidence_snippets": ["snippet1"],
            }
        )

        changes = repo.get_changes_for_company(company_id)
        assert isinstance(changes[0]["matched_keywords"], list)
        assert changes[0]["matched_keywords"] == ["keyword1", "keyword2"]
        assert isinstance(changes[0]["evidence_snippets"], list)

    def test_empty_json_fields_default_to_empty_list(self, db_with_company: DbWithCompany) -> None:
        db, company_id = db_with_company
        repo = SocialChangeRecordRepository(db, "test-user")
        snap_old, snap_new = self._insert_two_snapshots(db, company_id)

        repo.store_change_record(
            {
                "company_id": company_id,
                "source_url": "https://medium.com/@testco",
                "source_type": "medium",
                "snapshot_id_old": snap_old,
                "snapshot_id_new": snap_new,
                "checksum_old": "old_hash",
                "checksum_new": "new_hash",
                "has_changed": False,
                "change_magnitude": "minor",
                "detected_at": _now_iso(),
            }
        )

        changes = repo.get_changes_for_company(company_id)
        assert changes[0]["matched_keywords"] == []
        assert changes[0]["matched_categories"] == []
        assert changes[0]["evidence_snippets"] == []
