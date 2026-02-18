"""Firecrawl API client for web scraping."""

from __future__ import annotations

from typing import Any

import structlog
from firecrawl import Firecrawl

logger = structlog.get_logger(__name__)

# CRITICAL INVARIANT: only_main_content must ALWAYS be False.
# Social media links are in headers/footers (90%+ of cases).
# With False: 75 links across 21 companies
# With True: 33 links across 9 companies (127% fewer)
_ONLY_MAIN_CONTENT = False


class FirecrawlClient:
    """Client for Firecrawl web scraping API v2."""

    def __init__(self, api_key: str) -> None:
        self.client = Firecrawl(api_key=api_key)

    def capture_snapshot(self, url: str) -> dict[str, Any]:
        """Scrape a single URL.

        CRITICAL: only_main_content is ALWAYS False.

        Returns dict with: success, markdown, html, statusCode,
        has_paywall, has_auth_required, error, metadata.
        """
        try:
            result = self.client.scrape(
                url,
                formats=["markdown", "html"],
                only_main_content=_ONLY_MAIN_CONTENT,
                block_ads=False,
                wait_for=2000,
                timeout=30000,
                proxy="stealth",
                skip_tls_verification=True,
            )

            # result is a Document object
            metadata = getattr(result, "metadata", None)
            status_code = metadata.get("statusCode") if isinstance(metadata, dict) else None

            return {
                "success": True,
                "markdown": getattr(result, "markdown", None) or "",
                "html": getattr(result, "html", None) or "",
                "statusCode": status_code,
                "metadata": metadata,
                "warning": getattr(result, "warning", None),
                "has_paywall": False,
                "has_auth_required": False,
                "error": None,
            }
        except Exception as exc:
            logger.error("firecrawl_scrape_failed", url=url, error=str(exc))
            return {
                "success": False,
                "markdown": None,
                "html": None,
                "statusCode": None,
                "metadata": None,
                "warning": None,
                "has_paywall": False,
                "has_auth_required": False,
                "error": str(exc),
            }

    def batch_capture_snapshots(
        self,
        urls: list[str],
        poll_interval: int = 2,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Batch scrape using Firecrawl batch API.

        CRITICAL: only_main_content is ALWAYS False.

        Returns dict with: success, documents, total, completed, failed, errors.
        """
        try:
            batch_kwargs: dict[str, Any] = {
                "urls": urls,
                "formats": ["markdown", "html"],
                "only_main_content": _ONLY_MAIN_CONTENT,
                "block_ads": False,
                "wait_for": 2000,
                "timeout": 30000,
                "proxy": "stealth",
                "skip_tls_verification": True,
                "poll_interval": poll_interval,
            }
            if timeout is not None:
                batch_kwargs["wait_timeout"] = timeout

            result = self.client.batch_scrape(**batch_kwargs)

            documents: list[dict[str, Any]] = []
            if hasattr(result, "data") and result.data:
                for doc in result.data:
                    doc_metadata = getattr(doc, "metadata", None)
                    source_url = (
                        doc_metadata.get("sourceURL", "") if isinstance(doc_metadata, dict) else ""
                    )
                    documents.append(
                        {
                            "markdown": getattr(doc, "markdown", None) or "",
                            "html": getattr(doc, "html", None) or "",
                            "metadata": doc_metadata,
                            "url": source_url,
                        }
                    )

            return {
                "success": True,
                "documents": documents,
                "total": getattr(result, "total", len(documents)),
                "completed": getattr(result, "completed", len(documents)),
                "failed": 0,
                "errors": [],
            }
        except Exception as exc:
            logger.error("firecrawl_batch_scrape_failed", error=str(exc))
            return {
                "success": False,
                "documents": [],
                "total": len(urls),
                "completed": 0,
                "failed": len(urls),
                "errors": [str(exc)],
            }

    def crawl_website(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 50,
        include_subdomains: bool = True,
    ) -> dict[str, Any]:
        """Crawl entire website for full-site discovery.

        CRITICAL: only_main_content is ALWAYS False.

        Returns dict with: success, pages, total_pages, error.
        """
        try:
            result = self.client.crawl(
                url=url,
                limit=max_pages,
                scrape_options={
                    "formats": ["markdown", "html"],
                    "only_main_content": _ONLY_MAIN_CONTENT,
                    "wait_for": 2000,
                    "timeout": 30000,
                },
            )

            pages: list[dict[str, Any]] = []
            if hasattr(result, "data") and result.data:
                for page in result.data:
                    page_metadata = getattr(page, "metadata", None)
                    source_url = (
                        page_metadata.get("sourceURL", "")
                        if isinstance(page_metadata, dict)
                        else ""
                    )
                    pages.append(
                        {
                            "markdown": getattr(page, "markdown", None) or "",
                            "html": getattr(page, "html", None) or "",
                            "metadata": page_metadata,
                            "url": source_url,
                        }
                    )

            return {
                "success": True,
                "pages": pages,
                "total_pages": len(pages),
                "error": None,
            }
        except Exception as exc:
            logger.error("firecrawl_crawl_failed", url=url, error=str(exc))
            return {
                "success": False,
                "pages": [],
                "total_pages": 0,
                "error": str(exc),
            }
