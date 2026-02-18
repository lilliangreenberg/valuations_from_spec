"""Link aggregation from multiple pages."""

from __future__ import annotations

from typing import Any


def aggregate_links_from_pages(
    page_results: list[dict[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """Aggregate social media links discovered across multiple pages.

    Each page_result has a 'links' key with a list of link dicts.
    Links are deduplicated by profile_url.
    """
    all_links: list[dict[str, Any]] = []
    for page in page_results:
        links = page.get("links", [])
        all_links.extend(links)

    # Deduplicate
    seen: dict[str, dict[str, Any]] = {}
    for link in all_links:
        url = link.get("profile_url", "").lower().rstrip("/")
        if url and url not in seen:
            seen[url] = link

    return list(seen.values())


def merge_discovery_results(
    existing_links: list[dict[str, Any]],
    new_links: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge new discovery results with existing links.

    New links take precedence if they have higher confidence.
    """
    existing_by_url: dict[str, dict[str, Any]] = {}
    for link in existing_links:
        url = link.get("profile_url", "").lower().rstrip("/")
        if url:
            existing_by_url[url] = link

    for link in new_links:
        url = link.get("profile_url", "").lower().rstrip("/")
        if not url:
            continue
        if url not in existing_by_url:
            existing_by_url[url] = link
        else:
            existing_score = existing_by_url[url].get("similarity_score") or 0.0
            new_score = link.get("similarity_score") or 0.0
            if new_score > existing_score:
                existing_by_url[url] = link

    return list(existing_by_url.values())
