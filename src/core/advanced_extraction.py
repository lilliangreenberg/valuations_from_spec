"""Advanced link extraction from Schema.org, meta tags, and aria-labels."""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup


def extract_schema_org_social_links(html: str) -> list[str]:
    """Extract social media URLs from Schema.org JSON-LD sameAs property."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            urls.extend(_extract_same_as(data))
        except (json.JSONDecodeError, TypeError):
            continue

    return urls


def _extract_same_as(data: object) -> list[str]:
    """Recursively extract sameAs URLs from JSON-LD data."""
    urls: list[str] = []

    if isinstance(data, dict):
        same_as = data.get("sameAs")
        if isinstance(same_as, str) and same_as.startswith(("http://", "https://")):
            urls.append(same_as)
        elif isinstance(same_as, list):
            for item in same_as:
                if isinstance(item, str) and item.startswith(("http://", "https://")):
                    urls.append(item)
        for value in data.values():
            urls.extend(_extract_same_as(value))
    elif isinstance(data, list):
        for item in data:
            urls.extend(_extract_same_as(item))

    return urls


def extract_meta_social_handles(html: str) -> list[tuple[str, str]]:
    """Extract social media handles from meta tags.

    Returns list of (platform, handle_or_url) tuples.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str]] = []

    # twitter:site meta tag
    twitter_meta = soup.find("meta", attrs={"name": "twitter:site"})
    if twitter_meta:
        content = twitter_meta.get("content", "")
        if isinstance(content, str) and content:
            if content.startswith("@"):
                results.append(("twitter", f"https://twitter.com/{content.lstrip('@')}"))
            elif content.startswith(("http://", "https://")):
                results.append(("twitter", content))

    # twitter:creator meta tag
    twitter_creator = soup.find("meta", attrs={"name": "twitter:creator"})
    if twitter_creator:
        content = twitter_creator.get("content", "")
        if isinstance(content, str) and content.startswith("@"):
            results.append(("twitter", f"https://twitter.com/{content.lstrip('@')}"))

    return results


def extract_social_links_from_regex(html: str) -> list[str]:
    """Extract social media URLs using regex across raw HTML.

    Catches URLs that might not be in standard <a> tags.
    """
    social_domains = [
        "linkedin.com",
        "twitter.com",
        "x.com",
        "youtube.com",
        "facebook.com",
        "instagram.com",
        "github.com",
        "tiktok.com",
        "medium.com",
        "mastodon.social",
        "threads.net",
        "pinterest.com",
        "bsky.app",
    ]

    urls: list[str] = []
    for domain in social_domains:
        pattern = re.compile(
            rf'https?://(?:www\.)?{re.escape(domain)}/[^\s"\'<>]+',
            re.IGNORECASE,
        )
        for match in pattern.finditer(html):
            url = match.group(0).rstrip('")>;,.')
            urls.append(url)

    # Deduplicate preserving order
    return list(dict.fromkeys(urls))
