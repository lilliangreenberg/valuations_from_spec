"""Batch social media discovery with parallel processing."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

import structlog

from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from src.domains.discovery.services.full_site_social_discovery import (
        FullSiteSocialDiscovery,
    )

logger = structlog.get_logger(__name__)


class BatchSocialDiscovery:
    """Batch social media discovery using parallel full-site crawls."""

    def __init__(self, discovery_service: FullSiteSocialDiscovery) -> None:
        self.discovery = discovery_service

    def discover_batch(
        self,
        company_ids: list[int],
        max_workers: int = 5,
    ) -> dict[str, Any]:
        """Run full-site discovery for multiple companies in parallel.

        Returns summary stats.
        """
        tracker = ProgressTracker(total=len(company_ids))
        total_links = 0
        total_blogs = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.discovery.discover_for_company, cid): cid
                for cid in company_ids
            }

            for future in as_completed(futures):
                company_id = futures[future]
                try:
                    result = future.result()
                    if result.get("error"):
                        tracker.record_failure(f"Company {company_id}: {result['error']}")
                    else:
                        total_links += result.get("links_found", 0)
                        total_blogs += result.get("blogs_found", 0)
                        tracker.record_success()
                except Exception as exc:
                    logger.error(
                        "batch_discovery_failed",
                        company_id=company_id,
                        error=str(exc),
                    )
                    tracker.record_failure(f"Company {company_id}: {exc}")

                tracker.log_progress(every_n=5)

        summary = tracker.summary()
        summary["total_links_found"] = total_links
        summary["total_blogs_found"] = total_blogs
        return summary
