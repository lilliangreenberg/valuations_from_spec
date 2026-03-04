"""Baseline signal analysis service.

Computes one-time baseline signals for a company's first snapshot by running
keyword-based significance analysis on the full page content, then using LLM
classification to validate/override the keyword results. This captures
pre-existing positive/negative signals (e.g., a company already shut down
before the first snapshot was taken).

After baseline exists, all future signals come from diff-based change detection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from src.domains.monitoring.core.significance_analysis import (
    HOMEPAGE_EXCLUDED_CATEGORIES,
    analyze_content_significance,
)
from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.repositories.company_repository import CompanyRepository

logger = structlog.get_logger(__name__)

_LLM_CONTENT_LIMIT = 2000


class BaselineAnalyzer:
    """Computes baseline signal analysis for company snapshots."""

    def __init__(
        self,
        snapshot_repo: SnapshotRepository,
        company_repo: CompanyRepository,
        llm_client: Any | None = None,
        llm_enabled: bool = False,
    ) -> None:
        self.snapshot_repo = snapshot_repo
        self.company_repo = company_repo
        self.llm_client = llm_client
        self.llm_enabled = llm_enabled

    def analyze_baseline_for_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        """Run baseline analysis on a single snapshot.

        Returns the baseline data dict, or None if snapshot not found or has no content.
        """
        snapshot = self.snapshot_repo.get_snapshot_by_id(snapshot_id)
        if not snapshot or not snapshot.get("content_markdown"):
            return None

        company_id = snapshot["company_id"]
        company = self.company_repo.get_company_by_id(company_id)
        company_name = company["name"] if company else f"Company {company_id}"
        company_url = company.get("homepage_url", "") if company else ""

        content = snapshot["content_markdown"]

        result = analyze_content_significance(
            content,
            magnitude="minor",
            exclude_categories=HOMEPAGE_EXCLUDED_CATEGORIES,
        )

        # LLM as primary classifier for baseline -- keywords passed as hints
        if self.llm_enabled and self.llm_client:
            try:
                llm_result = self.llm_client.classify_baseline(
                    content_excerpt=content[:_LLM_CONTENT_LIMIT],
                    keywords=result.matched_keywords,
                    categories=result.matched_categories,
                    company_name=company_name,
                    homepage_url=company_url,
                )
                if not llm_result.get("error"):
                    result.classification = llm_result.get("classification", result.classification)
                    result.sentiment = llm_result.get("sentiment", result.sentiment)
                    result.confidence = llm_result.get("confidence", result.confidence)
                    if llm_result.get("reasoning"):
                        result.notes = llm_result["reasoning"]
            except Exception as exc:
                logger.warning(
                    "llm_baseline_classification_failed",
                    snapshot_id=snapshot_id,
                    error=str(exc),
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
                company_id = snapshot["company_id"]
                if self.snapshot_repo.has_baseline_for_company(company_id):
                    tracker.record_skip()
                    continue

                content = snapshot.get("content_markdown")
                if not content:
                    tracker.record_skip()
                    continue

                company = self.company_repo.get_company_by_id(company_id)
                company_name = company["name"] if company else f"Company {company_id}"
                company_url = company.get("homepage_url", "") if company else ""

                result = analyze_content_significance(
                    content,
                    magnitude="minor",
                    exclude_categories=HOMEPAGE_EXCLUDED_CATEGORIES,
                )

                # LLM as primary classifier for baseline -- keywords passed as hints
                if self.llm_enabled and self.llm_client:
                    try:
                        llm_result = self.llm_client.classify_baseline(
                            content_excerpt=content[:_LLM_CONTENT_LIMIT],
                            keywords=result.matched_keywords,
                            categories=result.matched_categories,
                            company_name=company_name,
                            homepage_url=company_url,
                        )
                        if not llm_result.get("error"):
                            result.classification = llm_result.get(
                                "classification", result.classification
                            )
                            result.sentiment = llm_result.get("sentiment", result.sentiment)
                            result.confidence = llm_result.get("confidence", result.confidence)
                            if llm_result.get("reasoning"):
                                result.notes = llm_result["reasoning"]
                    except Exception as exc:
                        logger.warning(
                            "llm_baseline_classification_failed",
                            snapshot_id=snapshot["id"],
                            error=str(exc),
                        )

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
