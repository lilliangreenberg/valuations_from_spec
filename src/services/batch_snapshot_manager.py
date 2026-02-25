"""Batch snapshot capture using Firecrawl batch API."""

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


class BatchSnapshotManager:
    """Manages batch snapshot capture using Firecrawl batch API."""

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
        self._baseline_analyzer = BaselineAnalyzer(snapshot_repo)
        self._logo_processor = logo_processor

    def capture_batch_snapshots(
        self,
        batch_size: int = 20,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Capture snapshots for all companies using batch API.

        Returns summary stats dict.
        """
        companies = self.company_repo.get_companies_with_homepage()
        tracker = ProgressTracker(total=len(companies))

        # Build URL -> company_id mapping
        url_to_company: dict[str, int] = {}
        urls: list[str] = []
        for company in companies:
            url = company.get("homepage_url")
            if url:
                url_to_company[url] = company["id"]
                urls.append(url)
            else:
                tracker.record_skip()

        # Process in batches
        for i in range(0, len(urls), batch_size):
            batch_urls = urls[i : i + batch_size]
            logger.info(
                "processing_batch",
                batch_number=i // batch_size + 1,
                batch_size=len(batch_urls),
                total_urls=len(urls),
            )

            try:
                result = self.firecrawl.batch_capture_snapshots(batch_urls, timeout=timeout)

                if result["success"]:
                    for doc in result.get("documents", []):
                        doc_url = doc.get("url", "")
                        company_id = url_to_company.get(doc_url)

                        if company_id is None:
                            # Try matching by URL prefix
                            for orig_url, cid in url_to_company.items():
                                if doc_url and orig_url in doc_url:
                                    company_id = cid
                                    break

                        if company_id is not None:
                            snapshot_data = prepare_snapshot_data(company_id, doc_url, doc)
                            snapshot_id = self.snapshot_repo.store_snapshot(snapshot_data)

                            # Auto-run baseline on first scrape
                            if self.snapshot_repo.count_snapshots_for_company(company_id) == 1:
                                self._baseline_analyzer.analyze_baseline_for_snapshot(snapshot_id)

                            # Process branding logo if available and company has no logo
                            branding = doc.get("branding")
                            if (
                                branding
                                and self._logo_processor
                                and not self._logo_processor.company_has_logo(company_id)
                            ):
                                self._logo_processor.process_branding_logo(
                                    company_id,
                                    branding,
                                )

                            tracker.record_success()
                        else:
                            tracker.record_failure(f"No company match for URL: {doc_url}")
                else:
                    for _url in batch_urls:
                        tracker.record_failure(f"Batch failed: {result.get('errors', [])}")
            except Exception as exc:
                logger.error("batch_processing_failed", error=str(exc))
                for _url in batch_urls:
                    tracker.record_failure(str(exc))

            tracker.log_progress(every_n=1)

        return tracker.summary()
