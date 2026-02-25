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


def _get_metadata_field(metadata: Any, snake_key: str, camel_key: str) -> Any:
    """Extract a field from metadata, handling both Pydantic objects and dicts.

    Firecrawl v2 returns DocumentMetadata Pydantic objects (snake_case attrs),
    but older versions or mocks may return plain dicts (camelCase keys).
    """
    if metadata is None:
        return None
    # Pydantic object: try snake_case attribute
    if hasattr(metadata, snake_key):
        return getattr(metadata, snake_key)
    # Dict fallback: try camelCase key
    if isinstance(metadata, dict):
        return metadata.get(camel_key) or metadata.get(snake_key)
    return None


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
                formats=["markdown", "html", "branding"],
                only_main_content=_ONLY_MAIN_CONTENT,
                block_ads=False,
                wait_for=2000,
                timeout=30000,
                proxy="stealth",
                skip_tls_verification=True,
            )

            # result is a Document object with Pydantic metadata
            metadata = getattr(result, "metadata", None)
            status_code = _get_metadata_field(metadata, "status_code", "statusCode")
            branding = getattr(result, "branding", None)

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
                "branding": branding,
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
                "branding": None,
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
                "formats": ["markdown", "html", "branding"],
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
                    source_url = _get_metadata_field(doc_metadata, "source_url", "sourceURL") or ""
                    doc_branding = getattr(doc, "branding", None)
                    documents.append(
                        {
                            "markdown": getattr(doc, "markdown", None) or "",
                            "html": getattr(doc, "html", None) or "",
                            "metadata": doc_metadata,
                            "url": source_url,
                            "branding": doc_branding,
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
                    "formats": ["markdown", "html", "branding"],
                    "only_main_content": _ONLY_MAIN_CONTENT,
                    "wait_for": 2000,
                    "timeout": 30000,
                },
            )

            pages: list[dict[str, Any]] = []
            if hasattr(result, "data") and result.data:
                for page in result.data:
                    page_metadata = getattr(page, "metadata", None)
                    source_url = _get_metadata_field(page_metadata, "source_url", "sourceURL") or ""
                    page_branding = getattr(page, "branding", None)
                    pages.append(
                        {
                            "markdown": getattr(page, "markdown", None) or "",
                            "html": getattr(page, "html", None) or "",
                            "metadata": page_metadata,
                            "url": source_url,
                            "branding": page_branding,
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
