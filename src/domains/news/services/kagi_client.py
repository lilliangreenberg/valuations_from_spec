"""Kagi Search API client for news monitoring."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import requests
import structlog

from src.utils.retry import retry_with_logging

logger = structlog.get_logger(__name__)


class KagiClient:
    """Client for Kagi Search API."""

    BASE_URL = "https://kagi.com/api/v0/search"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bot {api_key}",
            }
        )

    @retry_with_logging(max_attempts=3)
    def search(
        self,
        query: str,
        after_date: str | None = None,
        before_date: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search Kagi for news articles.

        Args:
            query: Search query string.
            after_date: Filter results after this date (YYYY-MM-DD).
            before_date: Filter results before this date (YYYY-MM-DD).
            limit: Maximum number of results.

        Returns:
            List of article dicts with: title, url, snippet, published, source.
        """
        # Build query with date filters
        full_query = query
        if after_date:
            full_query += f" after:{after_date}"
        if before_date:
            full_query += f" before:{before_date}"

        response = self.session.get(
            self.BASE_URL,
            params={"q": full_query, "limit": str(limit)},
            timeout=30,
        )

        if response.status_code == 401:
            raise ValueError("Invalid Kagi API key")
        if response.status_code == 429:
            raise ConnectionError("Kagi API rate limit exceeded")

        response.raise_for_status()

        data = response.json()
        articles: list[dict[str, Any]] = []

        for item in data.get("data", []):
            # Skip non-result items (Kagi returns different types)
            if not isinstance(item, dict):
                continue
            if not item.get("url"):
                continue

            # Extract source domain from URL
            source = urlparse(item["url"]).netloc
            if source.startswith("www."):
                source = source[4:]

            # Parse published date
            published = item.get("published") or item.get("t")
            if published and isinstance(published, str):
                try:
                    published_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    published = published_dt.isoformat()
                except ValueError:
                    published = datetime.now(tz=UTC).isoformat()
            else:
                published = datetime.now(tz=UTC).isoformat()

            articles.append(
                {
                    "title": item.get("title", ""),
                    "url": item["url"],
                    "snippet": item.get("snippet") or item.get("description", ""),
                    "published": published,
                    "source": source,
                }
            )

        logger.info(
            "kagi_search_completed",
            query=query,
            results=len(articles),
        )
        return articles
