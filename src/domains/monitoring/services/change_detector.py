"""Change detection service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.domains.monitoring.core.change_detection import (
    detect_content_change,
    extract_content_diff,
)
from src.domains.monitoring.core.significance_analysis import (
    HOMEPAGE_EXCLUDED_CATEGORIES,
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

_LLM_CONTENT_LIMIT = 2000


class ChangeDetector:
    """Orchestrates change detection between snapshots."""

    def __init__(
        self,
        snapshot_repo: SnapshotRepository,
        change_record_repo: ChangeRecordRepository,
        company_repo: CompanyRepository,
        llm_client: Any | None = None,
        llm_enabled: bool = False,
    ) -> None:
        self.snapshot_repo = snapshot_repo
        self.change_record_repo = change_record_repo
        self.company_repo = company_repo
        self.llm_client = llm_client
        self.llm_enabled = llm_enabled

    def detect_all_changes(self, limit: int | None = None) -> dict[str, Any]:
        """Detect changes for companies with 2+ snapshots.

        Args:
            limit: Maximum number of companies to process. None for all.

        Returns summary stats.
        """
        company_ids = self.snapshot_repo.get_companies_with_multiple_snapshots()
        if limit is not None:
            company_ids = company_ids[:limit]
        tracker = ProgressTracker(total=len(company_ids))
        changes_found = 0

        for company_id in company_ids:
            try:
                company = self.company_repo.get_company_by_id(company_id)
                company_name = company["name"] if company else f"Company {company_id}"
                company_url = company.get("homepage_url", "") if company else ""

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

                # Run significance analysis on diff content only
                if has_changed:
                    diff_text = extract_content_diff(
                        old_snap.get("content_markdown") or "",
                        new_snap.get("content_markdown") or "",
                    )
                    if diff_text.strip():
                        sig_result = analyze_content_significance(
                            diff_text,
                            magnitude=magnitude.value,
                            exclude_categories=HOMEPAGE_EXCLUDED_CATEGORIES,
                        )

                        # LLM as primary classifier — keywords passed as hints
                        if self.llm_enabled and self.llm_client:
                            try:
                                llm_result = self.llm_client.classify_significance(
                                    content_excerpt=diff_text[:_LLM_CONTENT_LIMIT],
                                    keywords=sig_result.matched_keywords,
                                    categories=sig_result.matched_categories,
                                    magnitude=magnitude.value,
                                    company_name=company_name,
                                    homepage_url=company_url,
                                )
                                if not llm_result.get("error"):
                                    sig_result.classification = llm_result.get(
                                        "classification", sig_result.classification
                                    )
                                    sig_result.sentiment = llm_result.get(
                                        "sentiment", sig_result.sentiment
                                    )
                                    sig_result.confidence = llm_result.get(
                                        "confidence", sig_result.confidence
                                    )
                                    if llm_result.get("reasoning"):
                                        sig_result.notes = llm_result["reasoning"]
                            except Exception as exc:
                                logger.warning(
                                    "llm_classification_failed",
                                    company_id=company_id,
                                    error=str(exc),
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
