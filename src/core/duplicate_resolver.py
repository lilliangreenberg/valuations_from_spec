"""Social media link deduplication logic."""

from __future__ import annotations

from typing import Any


def deduplicate_links(
    links: list[dict[str, Any]],
    key_field: str = "profile_url",
) -> list[dict[str, Any]]:
    """Deduplicate social media links by URL.

    When duplicates found, keep the one with:
    1. Higher similarity_score
    2. Earlier discovery (first seen)
    """
    seen: dict[str, dict[str, Any]] = {}

    for link in links:
        key = link.get(key_field, "").lower().rstrip("/")
        if not key:
            continue

        if key not in seen:
            seen[key] = link
        else:
            existing = seen[key]
            existing_score = existing.get("similarity_score") or 0.0
            new_score = link.get("similarity_score") or 0.0
            if new_score > existing_score:
                seen[key] = link

    return list(seen.values())


def deduplicate_blog_links(
    blogs: list[dict[str, Any]],
    key_field: str = "blog_url",
) -> list[dict[str, Any]]:
    """Deduplicate blog links by URL."""
    seen: dict[str, dict[str, Any]] = {}

    for blog in blogs:
        key = blog.get(key_field, "").lower().rstrip("/")
        if not key:
            continue
        if key not in seen:
            seen[key] = blog

    return list(seen.values())
