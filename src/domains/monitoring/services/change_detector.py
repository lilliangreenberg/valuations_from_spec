"""Change detection service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.domains.monitoring.core.change_detection import detect_content_change
from src.domains.monitoring.core.significance_analysis import (
    analyze_content_significance,
)
from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from src.domains.monitoring.repositories.change_record_repository import (
        ChangeRecordRepository,
    )
    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.repositories.company_repository import CompanyRepository

logger = structlog.get_logger(__name__)


class ChangeDetector:
    """Orchestrates change detection between snapshots."""

    def __init__(
        self,
        snapshot_repo: SnapshotRepository,
        change_record_repo: ChangeRecordRepository,
        company_repo: CompanyRepository,
    ) -> None:
        self.snapshot_repo = snapshot_repo
        self.change_record_repo = change_record_repo
        self.company_repo = company_repo

    def detect_all_changes(self) -> dict[str, Any]:
        """Detect changes for all companies with 2+ snapshots.

        Returns summary stats.
        """
        company_ids = self.snapshot_repo.get_companies_with_multiple_snapshots()
        tracker = ProgressTracker(total=len(company_ids))
        changes_found = 0

        for company_id in company_ids:
            try:
                snapshots = self.snapshot_repo.get_latest_snapshots(company_id, limit=2)
                if len(snapshots) < 2:
                    tracker.record_skip()
                    continue

                new_snap = snapshots[0]  # Most recent
                old_snap = snapshots[1]  # Previous

                old_checksum = old_snap.get("content_checksum", "") or ""
                new_checksum = new_snap.get("content_checksum", "") or ""

                has_changed, magnitude, similarity = detect_content_change(
                    old_checksum,
                    new_checksum,
                    old_snap.get("content_markdown"),
                    new_snap.get("content_markdown"),
                )

                now = datetime.now(UTC).isoformat()

                record_data: dict[str, Any] = {
                    "company_id": company_id,
                    "snapshot_id_old": old_snap["id"],
                    "snapshot_id_new": new_snap["id"],
                    "checksum_old": old_checksum,
                    "checksum_new": new_checksum,
                    "has_changed": has_changed,
                    "change_magnitude": magnitude.value,
                    "detected_at": now,
                }

                # Run significance analysis if changed
                if has_changed and new_snap.get("content_markdown"):
                    sig_result = analyze_content_significance(
                        new_snap["content_markdown"],
                        magnitude=magnitude.value,
                    )
                    record_data.update(
                        {
                            "significance_classification": sig_result.classification,
                            "significance_sentiment": sig_result.sentiment,
                            "significance_confidence": sig_result.confidence,
                            "matched_keywords": sig_result.matched_keywords,
                            "matched_categories": sig_result.matched_categories,
                            "significance_notes": sig_result.notes,
                            "evidence_snippets": sig_result.evidence_snippets,
                        }
                    )

                self.change_record_repo.store_change_record(record_data)

                if has_changed:
                    changes_found += 1

                tracker.record_success()
            except Exception as exc:
                logger.error(
                    "change_detection_failed",
                    company_id=company_id,
                    error=str(exc),
                )
                tracker.record_failure(f"Company {company_id}: {exc}")

            tracker.log_progress(every_n=10)

        summary = tracker.summary()
        summary["changes_found"] = changes_found
        return summary
