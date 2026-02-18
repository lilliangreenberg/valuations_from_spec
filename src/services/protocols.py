"""Service protocols defining interfaces for dependency injection."""

from __future__ import annotations

from typing import Any, Protocol


class WebScraperProtocol(Protocol):
    """Protocol for web scraping services."""

    def capture_snapshot(self, url: str) -> dict[str, Any]: ...

    def batch_capture_snapshots(
        self,
        urls: list[str],
        poll_interval: int = 2,
        timeout: int | None = None,
    ) -> dict[str, Any]: ...

    def crawl_website(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 50,
        include_subdomains: bool = True,
    ) -> dict[str, Any]: ...


class SearchClientProtocol(Protocol):
    """Protocol for search API clients."""

    def search(
        self,
        query: str,
        after_date: str | None = None,
        before_date: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]: ...
