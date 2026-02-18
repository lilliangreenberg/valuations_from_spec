"""Baseline signal analysis service.

Computes one-time baseline signals for a company's first snapshot by running
keyword-based significance analysis on the full page content. This captures
pre-existing positive/negative signals (e.g., a company already shut down
before the first snapshot was taken).

After baseline exists, all future signals come from diff-based change detection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from src.domains.monitoring.core.significance_analysis import (
    analyze_content_significance,
)
from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository

logger = structlog.get_logger(__name__)


class BaselineAnalyzer:
    """Computes baseline signal analysis for company snapshots."""

    def __init__(self, snapshot_repo: SnapshotRepository) -> None:
        self.snapshot_repo = snapshot_repo

    def analyze_baseline_for_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        """Run baseline analysis on a single snapshot.

        Returns the baseline data dict, or None if snapshot not found or has no content.
        """
        snapshot = self.snapshot_repo.get_snapshot_by_id(snapshot_id)
        if not snapshot or not snapshot.get("content_markdown"):
            return None

        result = analyze_content_significance(
            snapshot["content_markdown"],
            magnitude="minor",
        )

        baseline_data: dict[str, Any] = {
            "baseline_classification": result.classification,
            "baseline_sentiment": result.sentiment,
            "baseline_confidence": result.confidence,
            "baseline_keywords": result.matched_keywords,
            "baseline_categories": result.matched_categories,
            "baseline_notes": result.notes,
        }

        self.snapshot_repo.update_baseline(snapshot_id, baseline_data)

        logger.debug(
            "baseline_analyzed",
            snapshot_id=snapshot_id,
            company_id=snapshot["company_id"],
            classification=result.classification,
            sentiment=result.sentiment,
        )

        return baseline_data

    def analyze_baseline_for_company(self, company_id: int) -> dict[str, Any] | None:
        """Run baseline analysis for a company if no baseline exists yet.

        Returns the baseline data dict, or None if baseline already exists or no snapshot.
        """
        if self.snapshot_repo.has_baseline_for_company(company_id):
            return None

        snapshots = self.snapshot_repo.get_snapshots_without_baseline(company_id=company_id)
        if not snapshots:
            return None

        return self.analyze_baseline_for_snapshot(snapshots[0]["id"])

    def backfill_baselines(
        self,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Batch baseline analysis for companies missing baselines.

        Returns summary stats.
        """
        snapshots = self.snapshot_repo.get_snapshots_without_baseline()

        if limit is not None:
            snapshots = snapshots[:limit]

        tracker = ProgressTracker(total=len(snapshots))

        for snapshot in snapshots:
            try:
                if self.snapshot_repo.has_baseline_for_company(snapshot["company_id"]):
                    tracker.record_skip()
                    continue

                content = snapshot.get("content_markdown")
                if not content:
                    tracker.record_skip()
                    continue

                result = analyze_content_significance(content, magnitude="minor")

                if not dry_run:
                    baseline_data: dict[str, Any] = {
                        "baseline_classification": result.classification,
                        "baseline_sentiment": result.sentiment,
                        "baseline_confidence": result.confidence,
                        "baseline_keywords": result.matched_keywords,
                        "baseline_categories": result.matched_categories,
                        "baseline_notes": result.notes,
                    }
                    self.snapshot_repo.update_baseline(snapshot["id"], baseline_data)

                tracker.record_success()
            except Exception as exc:
                logger.error(
                    "baseline_analysis_failed",
                    snapshot_id=snapshot["id"],
                    company_id=snapshot["company_id"],
                    error=str(exc),
                )
                tracker.record_failure(str(exc))

            tracker.log_progress(every_n=10)

        return tracker.summary()
