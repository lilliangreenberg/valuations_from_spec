"""Contract tests for SocialChangeDetector.

Uses a real temp SQLite DB. No external API calls.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from src.domains.monitoring.repositories.social_change_record_repository import (
    SocialChangeRecordRepository,
)
from src.domains.monitoring.repositories.social_snapshot_repository import (
    SocialSnapshotRepository,
)
from src.domains.monitoring.services.social_change_detector import (
    SocialChangeDetector,
)
from src.repositories.company_repository import CompanyRepository

if TYPE_CHECKING:
    from src.services.database import Database


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _past_iso(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _insert_company(db: Database, name: str, url: str) -> int:
    now = _now_iso()
    cursor = db.execute(
        """INSERT INTO companies
           (name, homepage_url, source_sheet, flagged_for_review, created_at, updated_at)
           VALUES (?, ?, 'Test', 0, ?, ?)""",
        (name, url, now, now),
    )
    db.connection.commit()
    return cursor.lastrowid or 0


def _insert_social_snapshot(
    db: Database,
    company_id: int,
    source_url: str,
    source_type: str,
    content: str,
    captured_at: str,
) -> int:
    checksum = _md5(content)
    repo = SocialSnapshotRepository(db)
    return repo.store_snapshot(
        {
            "company_id": company_id,
            "source_url": source_url,
            "source_type": source_type,
            "content_markdown": content,
            "content_html": f"<p>{content}</p>",
            "status_code": 200,
            "captured_at": captured_at,
            "content_checksum": checksum,
        }
    )


class TestSocialChangeDetector:
    """Contract tests for SocialChangeDetector."""

    def test_detects_change_between_snapshots(self, db: Database) -> None:
        company_id = _insert_company(db, "TestCo", "https://testco.com")

        _insert_social_snapshot(
            db,
            company_id,
            "https://medium.com/@testco",
            "medium",
            "# Old Post\n\nSome old content about widgets.",
            _past_iso(2),
        )
        _insert_social_snapshot(
            db,
            company_id,
            "https://medium.com/@testco",
            "medium",
            "# New Post\n\nWe just raised $10M in funding!",
            _past_iso(1),
        )

        detector = SocialChangeDetector(
            social_snapshot_repo=SocialSnapshotRepository(db),
            social_change_record_repo=SocialChangeRecordRepository(db),
            company_repo=CompanyRepository(db),
        )

        result = detector.detect_all_changes()
        assert result["changes_found"] == 1

        # Verify record stored
        change_repo = SocialChangeRecordRepository(db)
        changes = change_repo.get_changes_for_company(company_id)
        assert len(changes) == 1
        assert changes[0]["has_changed"] == 1
        assert changes[0]["source_url"] == "https://medium.com/@testco"

    def test_no_change_when_identical(self, db: Database) -> None:
        company_id = _insert_company(db, "TestCo", "https://testco.com")
        content = "# Same content\n\nNothing changed."

        _insert_social_snapshot(
            db,
            company_id,
            "https://medium.com/@testco",
            "medium",
            content,
            _past_iso(2),
        )
        _insert_social_snapshot(
            db,
            company_id,
            "https://medium.com/@testco",
            "medium",
            content,
            _past_iso(1),
        )

        detector = SocialChangeDetector(
            social_snapshot_repo=SocialSnapshotRepository(db),
            social_change_record_repo=SocialChangeRecordRepository(db),
            company_repo=CompanyRepository(db),
        )

        result = detector.detect_all_changes()
        assert result["changes_found"] == 0

        # Record is still stored (with has_changed=0)
        changes = SocialChangeRecordRepository(db).get_changes_for_company(company_id)
        assert len(changes) == 1
        assert changes[0]["has_changed"] == 0

    def test_skips_sources_with_single_snapshot(self, db: Database) -> None:
        company_id = _insert_company(db, "TestCo", "https://testco.com")

        _insert_social_snapshot(
            db,
            company_id,
            "https://medium.com/@testco",
            "medium",
            "# Only one snapshot",
            _now_iso(),
        )

        detector = SocialChangeDetector(
            social_snapshot_repo=SocialSnapshotRepository(db),
            social_change_record_repo=SocialChangeRecordRepository(db),
            company_repo=CompanyRepository(db),
        )

        result = detector.detect_all_changes()
        assert result["changes_found"] == 0

    def test_significance_analysis_runs_on_changed_content(self, db: Database) -> None:
        company_id = _insert_company(db, "TestCo", "https://testco.com")

        _insert_social_snapshot(
            db,
            company_id,
            "https://testco.com/blog",
            "blog",
            "# Blog\n\nRegular update.",
            _past_iso(2),
        )
        _insert_social_snapshot(
            db,
            company_id,
            "https://testco.com/blog",
            "blog",
            "# Blog\n\nWe have raised a Series B funding round of $50M!",
            _past_iso(1),
        )

        detector = SocialChangeDetector(
            social_snapshot_repo=SocialSnapshotRepository(db),
            social_change_record_repo=SocialChangeRecordRepository(db),
            company_repo=CompanyRepository(db),
        )

        detector.detect_all_changes()

        changes = SocialChangeRecordRepository(db).get_changes_for_company(company_id)
        assert len(changes) == 1
        assert changes[0]["significance_classification"] is not None
        # "funding" should be detected
        assert any(
            "funding" in kw or "raised" in kw or "series b" in kw
            for kw in changes[0].get("matched_keywords", [])
        )

    def test_limit_restricts_pairs(self, db: Database) -> None:
        co1 = _insert_company(db, "Co1", "https://co1.com")
        co2 = _insert_company(db, "Co2", "https://co2.com")

        for co in [co1, co2]:
            _insert_social_snapshot(
                db,
                co,
                "https://medium.com/@co",
                "medium",
                f"Old content for {co}",
                _past_iso(2),
            )
            _insert_social_snapshot(
                db,
                co,
                "https://medium.com/@co",
                "medium",
                f"New content for {co}",
                _past_iso(1),
            )

        detector = SocialChangeDetector(
            social_snapshot_repo=SocialSnapshotRepository(db),
            social_change_record_repo=SocialChangeRecordRepository(db),
            company_repo=CompanyRepository(db),
        )

        result = detector.detect_all_changes(limit=1)
        assert result["successful"] == 1

    def test_multiple_sources_per_company(self, db: Database) -> None:
        company_id = _insert_company(db, "TestCo", "https://testco.com")

        # Medium source -- changed
        _insert_social_snapshot(
            db,
            company_id,
            "https://medium.com/@testco",
            "medium",
            "Old medium content",
            _past_iso(3),
        )
        _insert_social_snapshot(
            db,
            company_id,
            "https://medium.com/@testco",
            "medium",
            "New medium content with updates",
            _past_iso(1),
        )

        # Blog source -- identical
        _insert_social_snapshot(
            db,
            company_id,
            "https://testco.com/blog",
            "blog",
            "Static blog content",
            _past_iso(3),
        )
        _insert_social_snapshot(
            db,
            company_id,
            "https://testco.com/blog",
            "blog",
            "Static blog content",
            _past_iso(1),
        )

        detector = SocialChangeDetector(
            social_snapshot_repo=SocialSnapshotRepository(db),
            social_change_record_repo=SocialChangeRecordRepository(db),
            company_repo=CompanyRepository(db),
        )

        result = detector.detect_all_changes()
        assert result["changes_found"] == 1  # Only medium changed
        assert result["successful"] == 2  # Both pairs processed
