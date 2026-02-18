"""Kagi-based leadership search as fallback for LinkedIn browser scraping."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

import structlog

from src.domains.leadership.core.profile_parsing import (
    extract_linkedin_profile_url,
    filter_leadership_results,
    parse_kagi_leadership_result,
)

if TYPE_CHECKING:
    from src.domains.news.services.kagi_client import KagiClient

logger = structlog.get_logger(__name__)

# Search queries for leadership roles
_LEADERSHIP_QUERIES = [
    '"{company}" CEO linkedin.com/in',
    '"{company}" founder linkedin.com/in',
    '"{company}" CTO linkedin.com/in',
]


class LeadershipSearch:
    """Search for company leadership via Kagi search as LinkedIn fallback."""

    def __init__(self, kagi_client: KagiClient) -> None:
        self.kagi = kagi_client

    def search_leadership(
        self,
        company_name: str,
    ) -> list[dict[str, str]]:
        """Search for leadership profiles via Kagi.

        Executes multiple targeted searches (CEO, founder, CTO) in parallel
        and aggregates, deduplicates, and filters results.

        Returns list of dicts with keys: name, title, profile_url
        """
        all_results: list[dict[str, str]] = []
        queries = [tmpl.replace("{company}", company_name) for tmpl in _LEADERSHIP_QUERIES]

        with ThreadPoolExecutor(max_workers=len(queries)) as executor:
            futures = {executor.submit(self.kagi.search, query=q, limit=10): q for q in queries}

            for future in as_completed(futures):
                query = futures[future]
                try:
                    results = future.result()
                    parsed = self._parse_results(results)
                    all_results.extend(parsed)
                except Exception as exc:
                    logger.warning(
                        "kagi_leadership_search_failed",
                        query=query,
                        error=str(exc),
                    )

        # Deduplicate and filter to leadership
        filtered = filter_leadership_results(all_results)

        logger.info(
            "leadership_search_complete",
            company=company_name,
            raw_results=len(all_results),
            filtered_results=len(filtered),
        )

        return filtered

    def _parse_results(
        self,
        results: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        """Parse Kagi search results into leadership candidates."""
        parsed: list[dict[str, str]] = []

        for result in results:
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            url = result.get("url", "")

            # Try to parse as a LinkedIn profile result
            person = parse_kagi_leadership_result(title, snippet, url)
            if person:
                parsed.append(person)
                continue

            # Fallback: extract LinkedIn profile URL from snippet
            profile_url = extract_linkedin_profile_url(snippet)
            if not profile_url:
                profile_url = extract_linkedin_profile_url(url)
            if not profile_url:
                continue

            # Try to extract name from title
            name_parts = title.split("-")
            name = name_parts[0].strip() if name_parts else ""
            person_title = name_parts[1].strip() if len(name_parts) > 1 else ""

            if name:
                parsed.append(
                    {
                        "name": name,
                        "title": person_title,
                        "profile_url": profile_url,
                    }
                )

        return parsed
