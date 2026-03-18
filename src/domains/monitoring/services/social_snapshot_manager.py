"""Social media snapshot capture service.

Collects Medium + blog URLs from existing discovery data,
batch-scrapes them via FirecrawlClient, and stores snapshots.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.domains.monitoring.core.checksum import compute_content_checksum
from src.domains.monitoring.core.social_content_analysis import extract_latest_post_date
from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.domains.monitoring.repositories.social_snapshot_repository import (
        SocialSnapshotRepository,
    )
    from src.repositories.company_repository import CompanyRepository
    from src.services.firecrawl_client import FirecrawlClient

logger = structlog.get_logger(__name__)


class SocialSnapshotManager:
    """Orchestrates social media snapshot capture.

    Collects scrapable URLs (Medium profiles + blog links) from existing
    discovery data, batch-scrapes via FirecrawlClient, and stores snapshots
    with computed checksums and extracted posting dates.
    """

    def __init__(
        self,
        social_snapshot_repo: SocialSnapshotRepository,
        social_link_repo: SocialMediaLinkRepository,
        company_repo: CompanyRepository,
        firecrawl_client: FirecrawlClient,
    ) -> None:
        self.social_snapshot_repo = social_snapshot_repo
        self.social_link_repo = social_link_repo
        self.company_repo = company_repo
        self.firecrawl_client = firecrawl_client

    def collect_social_urls(self, company_id: int | None = None) -> list[dict[str, Any]]:
        """Get Medium + blog URLs from existing discovery data.

        Returns list of {company_id, source_url, source_type}.
        """
        urls: list[dict[str, Any]] = []

        # Collect Medium links (get_links_by_platform returns all companies)
        medium_links = self.social_link_repo.get_links_by_platform("medium")
        for link in medium_links:
            if company_id is not None and link["company_id"] != company_id:
                continue
            urls.append(
                {
                    "company_id": link["company_id"],
                    "source_url": link["profile_url"],
                    "source_type": "medium",
                }
            )

        # Collect blog links (single query for all, or filtered by company)
        if company_id is not None:
            blog_links = self.social_link_repo.get_blogs_for_company(company_id)
        else:
            blog_links = self.social_link_repo.get_all_blog_links()

        for blog in blog_links:
            urls.append(
                {
                    "company_id": blog["company_id"],
                    "source_url": blog["blog_url"],
                    "source_type": "blog",
                }
            )

        logger.info(
            "social_urls_collected",
            total=len(urls),
            medium=sum(1 for u in urls if u["source_type"] == "medium"),
            blog=sum(1 for u in urls if u["source_type"] == "blog"),
        )
        return urls

    def capture_social_snapshots(
        self,
        batch_size: int = 50,
        limit: int | None = None,
        company_id: int | None = None,
        exclude_company_ids: set[int] | None = None,
    ) -> dict[str, Any]:
        """Batch-capture social media snapshots.

        Uses FirecrawlClient.batch_capture_snapshots() for cost efficiency.
        Inherits the critical only_main_content=False invariant automatically.

        Args:
            batch_size: URLs per Firecrawl batch.
            limit: Max URLs to capture.
            company_id: Process single company only.
            exclude_company_ids: Company IDs to exclude (e.g. manually closed).

        Returns summary dict with report_details for report generation.
        """
        social_urls = self.collect_social_urls(company_id=company_id)
        if exclude_company_ids:
            pre = len(social_urls)
            social_urls = [u for u in social_urls if u["company_id"] not in exclude_company_ids]
            excluded = pre - len(social_urls)
            if excluded:
                logger.info(
                    "excluded_manually_closed",
                    total=pre,
                    excluded=excluded,
                    remaining=len(social_urls),
                )
        if limit is not None:
            social_urls = social_urls[:limit]

        if not social_urls:
            logger.info("no_social_urls_to_capture")
            return {
                "total": 0,
                "captured": 0,
                "failed": 0,
                "skipped": 0,
                "errors": [],
                "duration_seconds": 0.0,
                "report_details": {"captured": [], "failed": [], "skipped": []},
            }

        tracker = ProgressTracker(total=len(social_urls))
        now = datetime.now(UTC)

        # Report detail accumulators -- keyed by company_id
        captured_by_company: dict[int, dict[str, Any]] = {}
        failed_details: list[dict[str, Any]] = []
        skipped_details: list[dict[str, Any]] = []

        # Build URL-to-metadata mapping
        url_to_meta: dict[str, dict[str, Any]] = {}
        for item in social_urls:
            url_to_meta[item["source_url"]] = item

        # Process in batches
        all_urls = [item["source_url"] for item in social_urls]
        for batch_start in range(0, len(all_urls), batch_size):
            batch_urls = all_urls[batch_start : batch_start + batch_size]

            logger.info(
                "capturing_social_batch",
                batch_start=batch_start,
                batch_size=len(batch_urls),
                total=len(all_urls),
            )

            try:
                result = self.firecrawl_client.batch_capture_snapshots(batch_urls)
            except Exception as exc:
                for url in batch_urls:
                    tracker.record_failure(f"Batch failed for {url}: {exc}")
                    meta = url_to_meta.get(url, {})
                    company_name = self._resolve_company_name(meta.get("company_id"))
                    failed_details.append(
                        {
                            "company_id": meta.get("company_id"),
                            "name": company_name,
                            "source_url": url,
                            "error": str(exc),
                        }
                    )
                continue

            documents = result.get("documents", [])

            # Map documents back to URLs via their source_url metadata
            for doc in documents:
                doc_url = doc.get("source_url") or doc.get("url", "")
                meta = url_to_meta.get(doc_url)
                if meta is None:
                    # Try to match by checking if any source URL is in the doc URL
                    for source_url, source_meta in url_to_meta.items():
                        if source_url in doc_url or doc_url in source_url:
                            meta = source_meta
                            break
                if meta is None:
                    tracker.record_skip()
                    continue

                try:
                    markdown = doc.get("markdown") or ""
                    html = doc.get("html") or ""
                    checksum = compute_content_checksum(markdown) if markdown else None
                    post_date = extract_latest_post_date(markdown, reference_date=now)

                    self.social_snapshot_repo.store_snapshot(
                        {
                            "company_id": meta["company_id"],
                            "source_url": meta["source_url"],
                            "source_type": meta["source_type"],
                            "content_markdown": markdown,
                            "content_html": html,
                            "status_code": doc.get("statusCode") or doc.get("status_code"),
                            "captured_at": now.isoformat(),
                            "error_message": doc.get("error"),
                            "content_checksum": checksum,
                            "latest_post_date": post_date.isoformat() if post_date else None,
                        }
                    )
                    tracker.record_success()

                    # Track captured source for source_type_breakdown
                    cid = meta["company_id"]
                    if cid not in captured_by_company:
                        captured_by_company[cid] = {
                            "company_id": cid,
                            "name": self._resolve_company_name(cid),
                            "sources": [],
                        }
                    captured_by_company[cid]["sources"].append(
                        {
                            "source_url": meta["source_url"],
                            "source_type": meta["source_type"],
                        }
                    )
                except Exception as exc:
                    tracker.record_failure(
                        f"Failed to store snapshot for {meta['source_url']}: {exc}"
                    )
                    company_name = self._resolve_company_name(meta.get("company_id"))
                    failed_details.append(
                        {
                            "company_id": meta.get("company_id"),
                            "name": company_name,
                            "source_url": meta["source_url"],
                            "error": str(exc),
                        }
                    )

            # Track URLs that had no corresponding document
            captured_urls = {doc.get("source_url") or doc.get("url", "") for doc in documents}
            for url in batch_urls:
                if url not in captured_urls and not any(
                    url in cu or cu in url for cu in captured_urls
                ):
                    tracker.record_failure(f"No document returned for {url}")
                    meta = url_to_meta.get(url, {})
                    company_name = self._resolve_company_name(meta.get("company_id"))
                    failed_details.append(
                        {
                            "company_id": meta.get("company_id"),
                            "name": company_name,
                            "source_url": url,
                            "error": f"No document returned for {url}",
                        }
                    )

        summary: dict[str, Any] = {
            "total": tracker.total,
            "captured": tracker.successful,
            "failed": tracker.failed,
            "skipped": tracker.skipped,
            "errors": tracker.errors,
            "duration_seconds": round(tracker.elapsed_seconds, 2),
            "report_details": {
                "captured": list(captured_by_company.values()),
                "failed": failed_details,
                "skipped": skipped_details,
            },
        }
        logger.info(
            "social_snapshot_capture_complete",
            total=summary["total"],
            captured=summary["captured"],
            failed=summary["failed"],
            skipped=summary["skipped"],
        )
        return summary

    def _resolve_company_name(self, company_id: int | None) -> str:
        """Look up company name by ID. Returns empty string if not found."""
        if company_id is None:
            return ""
        company = self.company_repo.get_company_by_id(company_id)
        return company.get("name", "") if company else ""
