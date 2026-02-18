"""Full-site social media discovery using Firecrawl crawl API."""

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

if TYPE_CHECKING:
    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.repositories.company_repository import CompanyRepository
    from src.services.firecrawl_client import FirecrawlClient

logger = structlog.get_logger(__name__)


class FullSiteSocialDiscovery:
    """Full-site social media discovery using Firecrawl crawl API."""

    def __init__(
        self,
        firecrawl_client: FirecrawlClient,
        social_link_repo: SocialMediaLinkRepository,
        company_repo: CompanyRepository,
    ) -> None:
        self.firecrawl = firecrawl_client
        self.social_link_repo = social_link_repo
        self.company_repo = company_repo

    def discover_for_company(
        self,
        company_id: int,
        max_depth: int = 3,
        max_pages: int = 50,
        include_subdomains: bool = True,
    ) -> dict[str, Any]:
        """Run full-site discovery for a single company.

        Returns summary dict.
        """
        company = self.company_repo.get_company_by_id(company_id)
        if not company:
            return {"error": f"Company {company_id} not found"}

        url = company.get("homepage_url")
        if not url:
            return {"error": f"Company {company_id} has no homepage URL"}

        logger.info(
            "starting_full_site_discovery",
            company_id=company_id,
            company_name=company["name"],
            url=url,
        )

        crawl_result = self.firecrawl.crawl_website(
            url,
            max_depth=max_depth,
            max_pages=max_pages,
            include_subdomains=include_subdomains,
        )

        if not crawl_result["success"]:
            return {"error": crawl_result.get("error", "Crawl failed")}

        now = datetime.now(UTC).isoformat()
        links_stored = 0
        blogs_stored = 0
        pages_processed = 0

        for page in crawl_result.get("pages", []):
            pages_processed += 1
            all_urls = extract_all_social_links(
                html=page.get("html"),
                markdown=page.get("markdown"),
                base_url=url,
            )

            for found_url in all_urls:
                is_blog, blog_type = detect_blog_url(found_url)
                if is_blog and blog_type:
                    normalized_blog = normalize_blog_url(found_url)
                    self.social_link_repo.store_blog_link(
                        {
                            "company_id": company_id,
                            "blog_type": blog_type.value,
                            "blog_url": normalized_blog,
                            "discovery_method": "full_site_crawl",
                            "is_active": True,
                            "discovered_at": now,
                        }
                    )
                    blogs_stored += 1
                    continue

                platform = detect_platform(found_url)
                if platform is None:
                    continue

                normalized_url = normalize_social_url(found_url)
                self.social_link_repo.store_social_link(
                    {
                        "company_id": company_id,
                        "platform": platform.value,
                        "profile_url": normalized_url,
                        "discovery_method": "full_site_crawl",
                        "verification_status": "unverified",
                        "discovered_at": now,
                    }
                )
                links_stored += 1

        return {
            "company_id": company_id,
            "company_name": company["name"],
            "pages_crawled": pages_processed,
            "links_found": links_stored,
            "blogs_found": blogs_stored,
        }
