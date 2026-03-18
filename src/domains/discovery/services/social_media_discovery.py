"""Homepage-based social media discovery service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.domains.discovery.core.blog_detection import (
    detect_blog_url,
    normalize_blog_url,
)
from src.domains.discovery.core.link_extraction import extract_all_social_links
from src.domains.discovery.core.platform_detection import detect_platform
from src.domains.discovery.core.url_normalization import normalize_social_url
from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.repositories.company_repository import CompanyRepository
    from src.services.firecrawl_client import FirecrawlClient

logger = structlog.get_logger(__name__)


class SocialMediaDiscovery:
    """Homepage-based social media discovery using Firecrawl batch API."""

    def __init__(
        self,
        firecrawl_client: FirecrawlClient,
        social_link_repo: SocialMediaLinkRepository,
        company_repo: CompanyRepository,
    ) -> None:
        self.firecrawl = firecrawl_client
        self.social_link_repo = social_link_repo
        self.company_repo = company_repo

    def discover_all(
        self,
        batch_size: int = 50,
        limit: int | None = None,
        company_id: int | None = None,
        exclude_company_ids: set[int] | None = None,
    ) -> dict[str, Any]:
        """Discover social media for all companies.

        Returns summary stats with report_details for report generation.
        """
        if company_id is not None:
            company = self.company_repo.get_company_by_id(company_id)
            if not company:
                return {"error": f"Company {company_id} not found"}
            companies = [company]
        else:
            companies = self.company_repo.get_companies_with_homepage()

        if exclude_company_ids:
            pre = len(companies)
            companies = [c for c in companies if c["id"] not in exclude_company_ids]
            excluded = pre - len(companies)
            if excluded:
                logger.info(
                    "excluded_manually_closed",
                    total=pre,
                    excluded=excluded,
                    remaining=len(companies),
                )

        if limit is not None:
            companies = companies[:limit]

        tracker = ProgressTracker(total=len(companies))
        total_links = 0
        total_blogs = 0

        discovered_details: list[dict[str, Any]] = []
        no_links_found_details: list[dict[str, Any]] = []
        failed_details: list[dict[str, Any]] = []
        skipped_details: list[dict[str, Any]] = []

        # Build URL -> company mapping
        url_to_company: dict[str, dict[str, Any]] = {}
        urls: list[str] = []
        for company in companies:
            url = company.get("homepage_url")
            if url:
                url_to_company[url] = company
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

            try:
                if len(batch_urls) == 1:
                    # Single URL -- use direct scrape
                    result = self.firecrawl.capture_snapshot(batch_urls[0])
                    documents = (
                        [
                            {
                                "url": batch_urls[0],
                                "markdown": result.get("markdown", ""),
                                "html": result.get("html", ""),
                            }
                        ]
                        if result.get("success")
                        else []
                    )
                else:
                    batch_result = self.firecrawl.batch_capture_snapshots(batch_urls)
                    documents = batch_result.get("documents", [])

                for doc in documents:
                    doc_url = doc.get("url", "")
                    matched_company = url_to_company.get(doc_url)

                    if not matched_company:
                        # Try matching by prefix
                        for orig_url, comp in url_to_company.items():
                            if doc_url and orig_url in doc_url:
                                matched_company = comp
                                break

                    if not matched_company:
                        tracker.record_failure(f"No company match for {doc_url}")
                        failed_details.append(
                            {
                                "company_id": None,
                                "name": "",
                                "homepage_url": doc_url,
                                "error": f"No company match for {doc_url}",
                            }
                        )
                        continue

                    links_count, blogs_count, link_details, blog_details = (
                        self._process_company_page(matched_company, doc)
                    )
                    total_links += links_count
                    total_blogs += blogs_count
                    tracker.record_success()

                    if links_count > 0 or blogs_count > 0:
                        discovered_details.append(
                            {
                                "company_id": matched_company["id"],
                                "name": matched_company.get("name", ""),
                                "homepage_url": matched_company.get("homepage_url", ""),
                                "social_links": link_details,
                                "blogs": blog_details,
                            }
                        )
                    else:
                        no_links_found_details.append(
                            {
                                "company_id": matched_company["id"],
                                "name": matched_company.get("name", ""),
                                "homepage_url": matched_company.get("homepage_url", ""),
                            }
                        )
            except Exception as exc:
                logger.error("batch_discovery_failed", error=str(exc))
                for url in batch_urls:
                    tracker.record_failure(str(exc))
                    company_info = url_to_company.get(url, {})
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
        summary["total_links_found"] = total_links
        summary["total_blogs_found"] = total_blogs
        summary["report_details"] = {
            "discovered": discovered_details,
            "no_links_found": no_links_found_details,
            "failed": failed_details,
            "skipped": skipped_details,
        }
        return summary

    def _process_company_page(
        self,
        company: dict[str, Any],
        doc: dict[str, Any],
    ) -> tuple[int, int, list[dict[str, str]], list[dict[str, str]]]:
        """Process a scraped page to extract social links and blogs.

        Returns (links_count, blogs_count, link_details, blog_details).
        """
        company_id = company["id"]
        now = datetime.now(UTC).isoformat()

        # Extract all URLs
        all_urls = extract_all_social_links(
            html=doc.get("html"),
            markdown=doc.get("markdown"),
            base_url=company.get("homepage_url"),
        )

        links_stored = 0
        blogs_stored = 0
        link_details: list[dict[str, str]] = []
        blog_details: list[dict[str, str]] = []

        for url in all_urls:
            # Check if it's a blog
            is_blog, blog_type = detect_blog_url(url)
            if is_blog and blog_type:
                normalized_blog = normalize_blog_url(url)
                self.social_link_repo.store_blog_link(
                    {
                        "company_id": company_id,
                        "blog_type": blog_type.value,
                        "blog_url": normalized_blog,
                        "discovery_method": "page_footer",
                        "is_active": True,
                        "discovered_at": now,
                    }
                )
                blogs_stored += 1
                blog_details.append(
                    {
                        "blog_type": blog_type.value,
                        "blog_url": normalized_blog,
                    }
                )
                continue

            # Check if it's a social media URL
            platform = detect_platform(url)
            if platform is None:
                continue

            normalized_url = normalize_social_url(url)

            self.social_link_repo.store_social_link(
                {
                    "company_id": company_id,
                    "platform": platform.value,
                    "profile_url": normalized_url,
                    "discovery_method": "page_footer",
                    "verification_status": "unverified",
                    "discovered_at": now,
                }
            )
            links_stored += 1
            link_details.append(
                {
                    "platform": platform.value,
                    "profile_url": normalized_url,
                }
            )

        return links_stored, blogs_stored, link_details, blog_details
