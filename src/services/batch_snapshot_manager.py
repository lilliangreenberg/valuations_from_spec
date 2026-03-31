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
        self._baseline_analyzer = BaselineAnalyzer(snapshot_repo, company_repo)
        self._logo_processor = logo_processor

    def capture_batch_snapshots(
        self,
        batch_size: int = 20,
        timeout: int = 300,
        exclude_company_ids: set[int] | None = None,
    ) -> dict[str, Any]:
        """Capture snapshots for all companies using batch API.

        Args:
            batch_size: Number of URLs per batch.
            timeout: Timeout per batch in seconds.
            exclude_company_ids: Company IDs to skip.

        Returns summary stats dict with report_details for report generation.
        """
        companies = self.company_repo.get_companies_with_homepage()
        if exclude_company_ids:
            pre_filter_count = len(companies)
            companies = [c for c in companies if c["id"] not in exclude_company_ids]
            logger.info(
                "filtered_companies",
                total=pre_filter_count,
                excluded=pre_filter_count - len(companies),
                remaining=len(companies),
            )
        tracker = ProgressTracker(total=len(companies))

        failed_details: list[dict[str, Any]] = []
        skipped_details: list[dict[str, Any]] = []

        # Build URL -> company mapping (full company dict for report details)
        url_to_company: dict[str, int] = {}
        url_to_company_info: dict[str, dict[str, Any]] = {}
        urls: list[str] = []
        for company in companies:
            url = company.get("homepage_url")
            if url:
                url_to_company[url] = company["id"]
                url_to_company_info[url] = company
                urls.append(url)
            else:
                tracker.record_skip()
                skipped_details.append(
                    {
                        "company_id": company["id"],
                        "name": company.get("name", ""),
                        "reason": "no_homepage_url",
                    }
                )

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
                    returned_urls: set[str] = set()

                    for doc in result.get("documents", []):
                        doc_url = doc.get("url", "")
                        company_id = url_to_company.get(doc_url)

                        if company_id is None:
                            # Try matching by URL prefix
                            for orig_url, cid in url_to_company.items():
                                if doc_url and orig_url in doc_url:
                                    company_id = cid
                                    returned_urls.add(orig_url)
                                    break

                        if company_id is not None:
                            returned_urls.add(doc_url)
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
                            error_msg = f"No company match for URL: {doc_url}"
                            tracker.record_failure(error_msg)
                            failed_details.append(
                                {
                                    "company_id": None,
                                    "name": "",
                                    "homepage_url": doc_url,
                                    "error": error_msg,
                                }
                            )

                    # Record failures for URLs that Firecrawl silently dropped
                    for batch_url in batch_urls:
                        if batch_url not in returned_urls:
                            company_info = url_to_company_info.get(batch_url, {})
                            company_id = url_to_company.get(batch_url)
                            error_msg = (
                                "Firecrawl batch returned no data for this URL "
                                "(DNS error, timeout, or scrape failure)"
                            )
                            tracker.record_failure(error_msg)
                            failed_details.append(
                                {
                                    "company_id": company_info.get("id"),
                                    "name": company_info.get("name", ""),
                                    "homepage_url": batch_url,
                                    "error": error_msg,
                                }
                            )
                            # Log to processing_errors for traceability
                            if company_id is not None:
                                self.company_repo.store_processing_error(
                                    entity_type="snapshot",
                                    entity_id=company_id,
                                    error_type="BatchSilentFailure",
                                    error_message=error_msg,
                                )
                            logger.warning(
                                "batch_url_missing_from_results",
                                url=batch_url,
                                company_id=company_id,
                                company_name=company_info.get("name", ""),
                            )
                else:
                    batch_error = f"Batch failed: {result.get('errors', [])}"
                    for url in batch_urls:
                        tracker.record_failure(batch_error)
                        company_info = url_to_company_info.get(url, {})
                        failed_details.append(
                            {
                                "company_id": company_info.get("id"),
                                "name": company_info.get("name", ""),
                                "homepage_url": url,
                                "error": batch_error,
                            }
                        )
            except Exception as exc:
                logger.error("batch_processing_failed", error=str(exc))
                for url in batch_urls:
                    tracker.record_failure(str(exc))
                    company_info = url_to_company_info.get(url, {})
                    failed_details.append(
                        {
                            "company_id": company_info.get("id"),
                            "name": company_info.get("name", ""),
                            "homepage_url": url,
                            "error": str(exc),
                        }
                    )

            tracker.log_progress(every_n=1)

        summary = tracker.summary()
        summary["report_details"] = {
            "failed": failed_details,
            "skipped": skipped_details,
        }
        return summary
