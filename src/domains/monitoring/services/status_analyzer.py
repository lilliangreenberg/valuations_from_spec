"""Company status analysis service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.core.data_access import parse_datetime
from src.domains.monitoring.core.status_rules import analyze_snapshot_status
from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from src.domains.monitoring.repositories.company_status_repository import (
        CompanyStatusRepository,
    )
    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.repositories.company_repository import CompanyRepository

logger = structlog.get_logger(__name__)


class StatusAnalyzer:
    """Orchestrates company status analysis from snapshots."""

    def __init__(
        self,
        snapshot_repo: SnapshotRepository,
        status_repo: CompanyStatusRepository,
        company_repo: CompanyRepository,
    ) -> None:
        self.snapshot_repo = snapshot_repo
        self.status_repo = status_repo
        self.company_repo = company_repo

    def analyze_all_statuses(self) -> dict[str, Any]:
        """Analyze status for all companies with snapshots.

        Returns summary stats.
        """
        companies = self.company_repo.get_all_companies()
        tracker = ProgressTracker(total=len(companies))

        for company in companies:
            company_id = company["id"]
            try:
                snapshots = self.snapshot_repo.get_latest_snapshots(company_id, limit=1)
                if not snapshots:
                    tracker.record_skip()
                    continue

                snapshot = snapshots[0]
                content = snapshot.get("content_markdown") or ""
                if not content:
                    tracker.record_skip()
                    continue

                # Parse HTTP Last-Modified if present
                http_last_modified = parse_datetime(snapshot.get("http_last_modified"))

                status, confidence, indicators = analyze_snapshot_status(
                    content, http_last_modified
                )

                now = datetime.now(UTC).isoformat()

                self.status_repo.store_status(
                    {
                        "company_id": company_id,
                        "status": status.value,
                        "confidence": confidence,
                        "indicators": [
                            {
                                "type": ind[0],
                                "value": ind[1],
                                "signal": ind[2].value,
                            }
                            for ind in indicators
                        ],
                        "last_checked": now,
                        "http_last_modified": snapshot.get("http_last_modified"),
                    }
                )

                tracker.record_success()
            except Exception as exc:
                logger.error(
                    "status_analysis_failed",
                    company_id=company_id,
                    error=str(exc),
                )
                tracker.record_failure(f"Company {company_id}: {exc}")

            tracker.log_progress(every_n=10)

        return tracker.summary()
