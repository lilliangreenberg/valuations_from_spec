"""Change detection service."""

from __future__ import annotations

import contextlib
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
from src.domains.monitoring.core.social_content_analysis import (
    check_posting_inactivity,
    prepare_social_context,
)
from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from src.domains.monitoring.repositories.change_record_repository import (
        ChangeRecordRepository,
    )
    from src.domains.monitoring.repositories.company_status_repository import (
        CompanyStatusRepository,
    )
    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.domains.monitoring.repositories.social_snapshot_repository import (
        SocialSnapshotRepository,
    )
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
        social_snapshot_repo: SocialSnapshotRepository | None = None,
        status_repo: CompanyStatusRepository | None = None,
    ) -> None:
        self.snapshot_repo = snapshot_repo
        self.change_record_repo = change_record_repo
        self.company_repo = company_repo
        self.llm_client = llm_client
        self.llm_enabled = llm_enabled
        self.social_snapshot_repo = social_snapshot_repo
        self.status_repo = status_repo

    def _build_social_context(self, company_id: int) -> str:
        """Build social media context string for a company.

        Fetches latest social snapshots, checks posting inactivity,
        and formats for LLM consumption.
        """
        if self.social_snapshot_repo is None:
            return ""

        snapshots = self.social_snapshot_repo.get_all_sources_for_company(company_id)
        if not snapshots:
            return ""

        now = datetime.now(UTC)
        inactivity_results: list[tuple[str, bool, int | None]] = []

        for snap in snapshots:
            post_date_str = snap.get("latest_post_date")
            post_date = None
            if post_date_str:
                with contextlib.suppress(ValueError, TypeError):
                    post_date = datetime.fromisoformat(post_date_str)

            is_inactive, days = check_posting_inactivity(post_date, reference_date=now)
            inactivity_results.append((snap.get("source_url", ""), is_inactive, days))

        return prepare_social_context(snapshots, inactivity_results)

    def detect_all_changes(self, limit: int | None = None) -> dict[str, Any]:
        """Detect changes for companies with 2+ snapshots.

        Args:
            limit: Maximum number of companies to process. None for all.

        Returns summary stats with report_details for report generation.
        """
        company_ids = self.snapshot_repo.get_companies_with_multiple_snapshots()
        if limit is not None:
            company_ids = company_ids[:limit]
        tracker = ProgressTracker(total=len(company_ids))
        changes_found = 0

        changed_details: list[dict[str, Any]] = []
        failed_details: list[dict[str, Any]] = []
        skipped_details: list[dict[str, Any]] = []
        status_change_details: list[dict[str, Any]] = []

        for company_id in company_ids:
            try:
                company = self.company_repo.get_company_by_id(company_id)
                company_name = company["name"] if company else f"Company {company_id}"
                company_url = company.get("homepage_url", "") if company else ""

                snapshots = self.snapshot_repo.get_latest_snapshots(company_id, limit=2)
                if len(snapshots) < 2:
                    tracker.record_skip()
                    skipped_details.append({
                        "company_id": company_id,
                        "name": company_name,
                        "reason": "fewer_than_2_snapshots",
                    })
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

                # Significance fields for report detail
                sig_classification = ""
                sig_sentiment = ""
                sig_confidence = 0.0
                sig_keywords: list[str] = []
                sig_categories: list[str] = []
                sig_notes = ""

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

                        # Build social context if available
                        social_context = ""
                        if self.social_snapshot_repo is not None:
                            social_context = self._build_social_context(company_id)

                        # LLM as primary classifier -- keywords passed as hints
                        if self.llm_enabled and self.llm_client:
                            try:
                                llm_result = (
                                    self.llm_client.classify_significance_with_status(
                                        content_excerpt=diff_text[:_LLM_CONTENT_LIMIT],
                                        keywords=sig_result.matched_keywords,
                                        categories=sig_result.matched_categories,
                                        magnitude=magnitude.value,
                                        company_name=company_name,
                                        homepage_url=company_url,
                                        social_context=social_context,
                                    )
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

                                    # Write LLM-determined status unless manually overridden
                                    llm_status = llm_result.get("company_status", "")
                                    _valid_statuses = {
                                        "operational",
                                        "likely_closed",
                                        "uncertain",
                                    }
                                    if (
                                        self.status_repo is not None
                                        and llm_status in _valid_statuses
                                    ):
                                        if self.status_repo.has_manual_override(
                                            company_id
                                        ):
                                            logger.info(
                                                "status_update_skipped_manual_override",
                                                company_id=company_id,
                                            )
                                        else:
                                            prev = self.status_repo.get_latest_status(
                                                company_id
                                            )
                                            prev_status = (
                                                prev["status"] if prev else None
                                            )
                                            self.status_repo.store_status({
                                                "company_id": company_id,
                                                "status": llm_status,
                                                "confidence": llm_result.get(
                                                    "confidence", 0.5
                                                ),
                                                "indicators": [],
                                                "last_checked": now,
                                                "is_manual_override": False,
                                                "status_reason": llm_result.get(
                                                    "status_reason", ""
                                                ),
                                            })
                                            if prev_status != llm_status:
                                                status_change_details.append({
                                                    "company_id": company_id,
                                                    "name": company_name,
                                                    "previous_status": prev_status or "unknown",
                                                    "new_status": llm_status,
                                                    "status_reason": llm_result.get(
                                                        "status_reason", ""
                                                    ),
                                                })
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

                        sig_classification = sig_result.classification
                        sig_sentiment = sig_result.sentiment
                        sig_confidence = sig_result.confidence
                        sig_keywords = sig_result.matched_keywords
                        sig_categories = sig_result.matched_categories
                        sig_notes = sig_result.notes

                self.change_record_repo.store_change_record(record_data)

                if has_changed:
                    changes_found += 1
                    changed_details.append({
                        "company_id": company_id,
                        "name": company_name,
                        "homepage_url": company_url,
                        "change_magnitude": magnitude.value,
                        "significance": sig_classification,
                        "sentiment": sig_sentiment,
                        "confidence": sig_confidence,
                        "matched_keywords": sig_keywords,
                        "matched_categories": sig_categories,
                        "significance_notes": sig_notes,
                    })

                tracker.record_success()
            except Exception as exc:
                logger.error(
                    "change_detection_failed",
                    company_id=company_id,
                    error=str(exc),
                )
                tracker.record_failure(f"Company {company_id}: {exc}")
                failed_details.append({
                    "company_id": company_id,
                    "name": (
                        self.company_repo.get_company_by_id(company_id) or {}
                    ).get("name", f"Company {company_id}"),
                    "error": f"Company {company_id}: {exc}",
                })

            tracker.log_progress(every_n=10)

        summary = tracker.summary()
        summary["changes_found"] = changes_found
        summary["report_details"] = {
            "changed": changed_details,
            "failed": failed_details,
            "skipped": skipped_details,
            "status_changes": status_change_details,
        }
        return summary
