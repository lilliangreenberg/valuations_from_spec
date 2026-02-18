"""Significance analysis service for backfilling existing records."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from src.domains.monitoring.core.change_detection import extract_content_diff
from src.domains.monitoring.core.significance_analysis import (
    analyze_content_significance,
)
from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from src.domains.monitoring.repositories.change_record_repository import (
        ChangeRecordRepository,
    )
    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository

logger = structlog.get_logger(__name__)


class SignificanceAnalyzer:
    """Orchestrates significance analysis for change records."""

    def __init__(
        self,
        change_record_repo: ChangeRecordRepository,
        snapshot_repo: SnapshotRepository,
        llm_client: Any | None = None,
        llm_enabled: bool = False,
    ) -> None:
        self.change_record_repo = change_record_repo
        self.snapshot_repo = snapshot_repo
        self.llm_client = llm_client
        self.llm_enabled = llm_enabled

    def backfill_significance(self, dry_run: bool = False) -> dict[str, Any]:
        """Backfill significance for records missing analysis.

        Uses diff-based analysis: compares old and new snapshot content,
        then runs keyword analysis only on the changed (added) lines.

        Returns summary stats.
        """
        records = self.change_record_repo.get_records_without_significance()
        tracker = ProgressTracker(total=len(records))

        for record in records:
            try:
                old_snapshot = self.snapshot_repo.get_snapshot_by_id(record["snapshot_id_old"])
                new_snapshot = self.snapshot_repo.get_snapshot_by_id(record["snapshot_id_new"])

                if not new_snapshot or not new_snapshot.get("content_markdown"):
                    tracker.record_skip()
                    continue

                old_content = old_snapshot.get("content_markdown", "") if old_snapshot else ""
                new_content = new_snapshot.get("content_markdown", "") or ""

                diff_text = extract_content_diff(old_content or "", new_content)

                if not diff_text.strip():
                    tracker.record_skip()
                    continue

                result = analyze_content_significance(
                    diff_text,
                    magnitude=record.get("change_magnitude", "minor"),
                )

                # Optional LLM validation
                if self.llm_enabled and self.llm_client:
                    try:
                        llm_result = self.llm_client.validate_significance(
                            content_excerpt=diff_text[:2000],
                            keywords=result.matched_keywords,
                            categories=result.matched_categories,
                            initial_classification=result.classification,
                            magnitude=record.get("change_magnitude", "minor"),
                        )
                        if not llm_result.get("error"):
                            result.classification = llm_result.get(
                                "classification", result.classification
                            )
                            result.sentiment = llm_result.get("sentiment", result.sentiment)
                            result.confidence = llm_result.get("confidence", result.confidence)
                    except Exception as exc:
                        logger.warning("llm_validation_failed", error=str(exc))

                if not dry_run:
                    self.change_record_repo.update_significance(
                        record["id"],
                        {
                            "significance_classification": result.classification,
                            "significance_sentiment": result.sentiment,
                            "significance_confidence": result.confidence,
                            "matched_keywords": result.matched_keywords,
                            "matched_categories": result.matched_categories,
                            "significance_notes": result.notes,
                            "evidence_snippets": result.evidence_snippets,
                        },
                    )

                tracker.record_success()
            except Exception as exc:
                logger.error(
                    "significance_backfill_failed",
                    record_id=record["id"],
                    error=str(exc),
                )
                tracker.record_failure(str(exc))

            tracker.log_progress(every_n=10)

        return tracker.summary()
