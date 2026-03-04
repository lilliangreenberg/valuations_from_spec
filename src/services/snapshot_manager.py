"""Sequential snapshot capture manager."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from src.core.transformers import prepare_snapshot_data
from src.domains.monitoring.services.baseline_analyzer import BaselineAnalyzer
from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from src.domains.discovery.services.branding_logo_processor import BrandingLogoProcessor
    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.repositories.company_repository import CompanyRepository
    from src.services.firecrawl_client import FirecrawlClient

logger = structlog.get_logger(__name__)


class SnapshotManager:
    """Manages sequential snapshot capture for all companies."""

    def __init__(
        self,
        firecrawl_client: FirecrawlClient,
        snapshot_repo: SnapshotRepository,
        company_repo: CompanyRepository,
        logo_processor: BrandingLogoProcessor | None = None,
    ) -> None:
        self.firecrawl = firecrawl_client
        self.snapshot_repo = snapshot_repo
        self.company_repo = company_repo
        self._baseline_analyzer = BaselineAnalyzer(snapshot_repo, company_repo)
        self._logo_processor = logo_processor

    def capture_snapshot_for_company(self, company_id: int) -> dict[str, Any]:
        """Capture a snapshot for a single company by ID.

        Returns summary stats dict.

        Raises:
            ValueError: If company not found or has no homepage URL.
        """
        company = self.company_repo.get_company_by_id(company_id)
        if not company:
            raise ValueError(f"Company with id {company_id} not found")

        url = company["homepage_url"]
        if not url:
            raise ValueError(f"Company {company_id} ({company['name']}) has no homepage URL")

        tracker = ProgressTracker(total=1)

        try:
            result = self.firecrawl.capture_snapshot(url)
            snapshot_data = prepare_snapshot_data(company_id, url, result)
            snapshot_id = self.snapshot_repo.store_snapshot(snapshot_data)

            if self.snapshot_repo.count_snapshots_for_company(company_id) == 1:
                self._baseline_analyzer.analyze_baseline_for_snapshot(snapshot_id)

            tracker.record_success()
            logger.info(
                "snapshot_captured",
                company_id=company_id,
                company_name=company["name"],
                url=url,
            )
        except Exception as exc:
            logger.error(
                "snapshot_capture_failed",
                company_id=company_id,
                url=url,
                error=str(exc),
            )
            tracker.record_failure(f"Company {company_id}: {exc}")
            self.company_repo.store_processing_error(
                entity_type="snapshot",
                entity_id=company_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        return tracker.summary()

    def capture_all_snapshots(self) -> dict[str, Any]:
        """Capture snapshots for all companies with homepage URLs.

        Returns summary stats dict.
        """
        companies = self.company_repo.get_companies_with_homepage()
        tracker = ProgressTracker(total=len(companies))

        for company in companies:
            company_id = company["id"]
            url = company["homepage_url"]

            if not url:
                tracker.record_skip()
                continue

            try:
                result = self.firecrawl.capture_snapshot(url)
                snapshot_data = prepare_snapshot_data(company_id, url, result)
                snapshot_id = self.snapshot_repo.store_snapshot(snapshot_data)

                # Auto-run baseline on first scrape for this company
                if self.snapshot_repo.count_snapshots_for_company(company_id) == 1:
                    self._baseline_analyzer.analyze_baseline_for_snapshot(snapshot_id)

                # Process branding logo if available and company has no logo
                branding = result.get("branding")
                if (
                    branding
                    and self._logo_processor
                    and not self._logo_processor.company_has_logo(company_id)
                ):
                    self._logo_processor.process_branding_logo(company_id, branding)

                tracker.record_success()
            except Exception as exc:
                logger.error(
                    "snapshot_capture_failed",
                    company_id=company_id,
                    url=url,
                    error=str(exc),
                )
                tracker.record_failure(f"Company {company_id}: {exc}")
                self.company_repo.store_processing_error(
                    entity_type="snapshot",
                    entity_id=company_id,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )

            tracker.log_progress(every_n=10)

        return tracker.summary()
