"""Change detection service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.core.data_access import parse_datetime
from src.domains.monitoring.core.change_detection import (
    detect_content_change,
    detect_error_state_transition,
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
        linkedin_snapshot_repo: Any | None = None,
        leadership_repo: Any | None = None,
    ) -> None:
        self.snapshot_repo = snapshot_repo
        self.change_record_repo = change_record_repo
        self.company_repo = company_repo
        self.llm_client = llm_client
        self.llm_enabled = llm_enabled
        self.social_snapshot_repo = social_snapshot_repo
        self.status_repo = status_repo
        self.linkedin_snapshot_repo = linkedin_snapshot_repo
        self.leadership_repo = leadership_repo

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
            post_date = parse_datetime(snap.get("latest_post_date"))
            is_inactive, days = check_posting_inactivity(post_date, reference_date=now)
            inactivity_results.append((snap.get("source_url", ""), is_inactive, days))

        return prepare_social_context(snapshots, inactivity_results)

    def _build_linkedin_context(self, company_id: int) -> str:
        """Build LinkedIn verification context string for a company.

        Pulls latest leadership records and LinkedIn snapshot data
        to provide employment verification signals to the LLM.
        """
        if not self.leadership_repo:
            return ""

        from src.domains.leadership.core.change_detection import (
            build_linkedin_verification_context,
        )

        leadership_records = self.leadership_repo.get_current_leadership(company_id)
        if not leadership_records:
            return ""

        # Check the most recent LinkedIn snapshots for verification data.
        # Only the newest few rows per company matter for the LLM context;
        # older snapshots are historical noise.
        verification_results: list[dict[str, str]] = []
        if self.linkedin_snapshot_repo:
            snapshots = self.linkedin_snapshot_repo.get_snapshots_for_company(company_id, limit=10)
            for snap in snapshots:
                if snap.get("url_type") == "person" and snap.get("vision_data_json"):
                    try:
                        import json

                        vision_data = json.loads(snap["vision_data_json"])
                        verification_results.append(
                            {
                                "person_name": snap.get("person_name", ""),
                                "status": "departed"
                                if not vision_data.get("is_employed", True)
                                else "employed",
                                "confidence": str(vision_data.get("confidence", 0.0)),
                                "evidence": vision_data.get("evidence", ""),
                                "change_detected": str(not vision_data.get("is_employed", True)),
                            }
                        )
                    except (json.JSONDecodeError, TypeError):
                        pass

        return build_linkedin_verification_context(verification_results, leadership_records)

    def detect_all_changes(
        self,
        limit: int | None = None,
        company_ids: list[int] | None = None,
        exclude_company_ids: set[int] | None = None,
    ) -> dict[str, Any]:
        """Detect changes for companies with 2+ snapshots.

        Args:
            limit: Maximum number of companies to process. None for all.
            company_ids: Explicit list of company IDs to process. When provided,
                overrides the full-portfolio query and ignores limit.
            exclude_company_ids: Company IDs to exclude (e.g. manually closed).

        Returns summary stats with report_details for report generation.
        """
        if company_ids is not None:
            all_ids = company_ids
        else:
            all_ids = self.snapshot_repo.get_companies_with_multiple_snapshots()
            if limit is not None:
                all_ids = all_ids[:limit]
        if exclude_company_ids:
            pre = len(all_ids)
            all_ids = [cid for cid in all_ids if cid not in exclude_company_ids]
            excluded = pre - len(all_ids)
            if excluded:
                logger.info(
                    "excluded_manually_closed",
                    total=pre,
                    excluded=excluded,
                    remaining=len(all_ids),
                )
        company_ids = all_ids
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
                company_notes = company.get("notes") or "" if company else ""

                snapshots = self.snapshot_repo.get_latest_snapshots(company_id, limit=2)
                if len(snapshots) < 2:
                    tracker.record_skip()
                    skipped_details.append(
                        {
                            "company_id": company_id,
                            "name": company_name,
                            "reason": "fewer_than_2_snapshots",
                        }
                    )
                    continue

                new_snap = snapshots[0]  # Most recent
                old_snap = snapshots[1]  # Previous

                # None = failed capture (no content). Empty strings from the
                # DB are coerced to None so the comparison logic treats them
                # as missing rather than as an equal empty checksum, which
                # would mask two failed snapshots as "unchanged".
                raw_old = old_snap.get("content_checksum")
                raw_new = new_snap.get("content_checksum")
                old_checksum: str | None = raw_old if raw_old else None
                new_checksum: str | None = raw_new if raw_new else None

                has_changed, magnitude, similarity = detect_content_change(
                    old_checksum,
                    new_checksum,
                    old_snap.get("content_markdown"),
                    new_snap.get("content_markdown"),
                )

                # Detect transitions in and out of error states even when
                # detect_content_change reports no content-level change
                # (e.g., two consecutive failures with different error
                # messages should still surface as a change).
                error_transition, error_description = detect_error_state_transition(
                    old_snap.get("error_message"),
                    new_snap.get("error_message"),
                    old_checksum,
                    new_checksum,
                )
                if error_transition and not has_changed:
                    # Two consecutive error captures with different messages:
                    # force has_changed so the error is surfaced. The
                    # downstream "new_snap_error" branch classifies it as
                    # uncertain and stores the error text.
                    has_changed = True
                    logger.info(
                        "error_state_transition_detected",
                        company_id=company_id,
                        description=error_description,
                    )

                now = datetime.now(UTC).isoformat()

                record_data: dict[str, Any] = {
                    "company_id": company_id,
                    "snapshot_id_old": old_snap["id"],
                    "snapshot_id_new": new_snap["id"],
                    # Schema requires NOT NULL; store empty string for
                    # failed captures. The in-memory logic above uses None.
                    "checksum_old": old_checksum or "",
                    "checksum_new": new_checksum or "",
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

                # Run significance analysis on diff content.
                # If the new snapshot has a scrape error we can't trust the
                # change, so mark it uncertain immediately and skip LLM.
                # Otherwise fall back to new-then-old content when the additions
                # diff is empty (content removed/replaced rather than added).
                new_snap_error = (new_snap.get("error_message") or "").strip()
                if has_changed and new_snap_error:
                    note = f"Snapshot capture failed: {new_snap_error[:300]}"
                    sig_classification = "uncertain"
                    sig_sentiment = "neutral"
                    sig_notes = note
                    record_data.update(
                        {
                            "significance_classification": "uncertain",
                            "significance_sentiment": "neutral",
                            "significance_confidence": 0.0,
                            "matched_keywords": [],
                            "matched_categories": [],
                            "significance_notes": note,
                            "evidence_snippets": [],
                        }
                    )
                elif has_changed:
                    diff_text = extract_content_diff(
                        old_snap.get("content_markdown") or "",
                        new_snap.get("content_markdown") or "",
                    )
                    analysis_text = (
                        diff_text.strip()
                        or (new_snap.get("content_markdown") or "").strip()
                        or (old_snap.get("content_markdown") or "").strip()
                    )
                    if not analysis_text:
                        # No content to analyze but change was detected
                        record_data.update(
                            {
                                "significance_classification": "insignificant",
                                "significance_sentiment": "neutral",
                                "significance_confidence": 0.5,
                                "matched_keywords": [],
                                "matched_categories": [],
                                "significance_notes": ("No analyzable content in diff."),
                                "evidence_snippets": [],
                            }
                        )
                        sig_classification = "insignificant"
                        sig_sentiment = "neutral"
                        sig_confidence = 0.5
                        sig_notes = "No analyzable content in diff."
                    if analysis_text:
                        sig_result = analyze_content_significance(
                            analysis_text,
                            magnitude=magnitude.value,
                            exclude_categories=HOMEPAGE_EXCLUDED_CATEGORIES,
                        )

                        # Build social context if available
                        social_context = ""
                        if self.social_snapshot_repo is not None:
                            social_context = self._build_social_context(company_id)

                        # Append LinkedIn verification context
                        linkedin_context = self._build_linkedin_context(company_id)
                        if linkedin_context:
                            social_context = (
                                f"{social_context}\n\n{linkedin_context}"
                                if social_context
                                else linkedin_context
                            )

                        # Append current status context so LLM can factor it in
                        if self.status_repo is not None:
                            current_status = self.status_repo.get_latest_status(company_id)
                            if current_status:
                                status_str = current_status.get("status", "unknown")
                                status_conf = current_status.get("confidence", 0.0)
                                status_reason = current_status.get("status_reason", "") or ""
                                is_manual = current_status.get("is_manual_override", False)
                                manual_note = " (manually set)" if is_manual else ""
                                status_context = (
                                    f"\nCurrent company status: "
                                    f"{status_str}{manual_note} "
                                    f"(confidence: {status_conf:.0%})"
                                )
                                if status_reason:
                                    status_context += f"\nStatus reason: {status_reason}"
                                social_context = (
                                    f"{social_context}\n{status_context}"
                                    if social_context
                                    else status_context
                                )

                        # Short-circuit: skip the LLM entirely when the
                        # keyword engine is already highly confident about
                        # an obvious case. Saves one LLM call per company
                        # in the common "copyright/styling tweak" scenario.
                        skip_llm = _should_skip_llm(sig_result, magnitude.value)
                        if skip_llm:
                            logger.debug(
                                "llm_skipped_obvious_case",
                                company_id=company_id,
                                classification=sig_result.classification,
                                confidence=sig_result.confidence,
                            )

                        # LLM as primary classifier -- keywords passed as hints
                        if not skip_llm and self.llm_enabled and self.llm_client:
                            try:
                                llm_result = self.llm_client.classify_significance_with_status(
                                    content_excerpt=analysis_text[:_LLM_CONTENT_LIMIT],
                                    keywords=sig_result.matched_keywords,
                                    categories=sig_result.matched_categories,
                                    magnitude=magnitude.value,
                                    company_name=company_name,
                                    homepage_url=company_url,
                                    social_context=social_context,
                                    company_notes=company_notes,
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
                                        if self.status_repo.has_manual_override(company_id):
                                            logger.info(
                                                "status_update_skipped_manual_override",
                                                company_id=company_id,
                                            )
                                        else:
                                            prev = self.status_repo.get_latest_status(company_id)
                                            prev_status = prev["status"] if prev else None
                                            self.status_repo.store_status(
                                                {
                                                    "company_id": company_id,
                                                    "status": llm_status,
                                                    "confidence": llm_result.get("confidence", 0.5),
                                                    "indicators": [],
                                                    "last_checked": now,
                                                    "is_manual_override": False,
                                                    "status_reason": llm_result.get(
                                                        "status_reason", ""
                                                    ),
                                                }
                                            )
                                            if prev_status != llm_status:
                                                status_change_details.append(
                                                    {
                                                        "company_id": company_id,
                                                        "name": company_name,
                                                        "previous_status": prev_status or "unknown",
                                                        "new_status": llm_status,
                                                        "status_reason": llm_result.get(
                                                            "status_reason", ""
                                                        ),
                                                    }
                                                )
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
                else:
                    # No change detected -- mark as insignificant
                    record_data.update(
                        {
                            "significance_classification": "insignificant",
                            "significance_sentiment": "neutral",
                            "significance_confidence": 1.0,
                            "matched_keywords": [],
                            "matched_categories": [],
                            "significance_notes": "No content change detected.",
                            "evidence_snippets": [],
                        }
                    )

                self.change_record_repo.store_change_record(record_data)

                if has_changed:
                    changes_found += 1
                    changed_details.append(
                        {
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
                        }
                    )

                tracker.record_success()
            except Exception as exc:
                logger.error(
                    "change_detection_failed",
                    company_id=company_id,
                    error=str(exc),
                )
                tracker.record_failure(f"Company {company_id}: {exc}")
                failed_details.append(
                    {
                        "company_id": company_id,
                        "name": (self.company_repo.get_company_by_id(company_id) or {}).get(
                            "name", f"Company {company_id}"
                        ),
                        "error": f"Company {company_id}: {exc}",
                    }
                )

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


# Category names from significance_analysis.NEGATIVE_KEYWORDS/POSITIVE_KEYWORDS
# that count as "concrete business signals". Used below to decide when the
# keyword engine is confident enough that the LLM cannot realistically flip
# the answer.
_DECISIVE_SIGNIFICANT_CATEGORIES: frozenset[str] = frozenset(
    {
        "funding",
        "product_launch",
        "partnerships",
        "expansion",
        "closure",
        "financial_distress",
        "acquisition",
        "layoffs_downsizing",
    }
)


def _should_skip_llm(sig_result: Any, magnitude: str) -> bool:
    """Return True when the keyword engine is confident enough to skip the LLM.

    Two cases:
      1. Obvious noise -- classification=insignificant, minor magnitude,
         confidence >= 0.85. These are copyright/CSS tweaks that the LLM
         would unanimously agree are insignificant; the LLM call is pure cost.
      2. Obvious real event -- classification=significant, confidence >= 0.90,
         at least one matched category is a decisive business signal
         (funding, acquisition, closure, etc.). The LLM's role here is
         verification; at this confidence it won't flip a correct answer.
    """
    classification = getattr(sig_result, "classification", "") or ""
    confidence = float(getattr(sig_result, "confidence", 0.0) or 0.0)
    matched_categories = getattr(sig_result, "matched_categories", None) or []

    if classification == "insignificant" and magnitude == "minor" and confidence >= 0.85:
        return True

    return (
        classification == "significant"
        and confidence >= 0.90
        and bool(set(matched_categories) & _DECISIVE_SIGNIFICANT_CATEGORIES)
    )
