"""Extract links from HTML and markdown content."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def extract_links_from_markdown(markdown: str) -> list[str]:
    """Extract URLs from markdown content.

    Matches markdown link syntax [text](url) and bare URLs.
    """
    urls: list[str] = []

    # Match markdown links: [text](url) or [text](url "title")
    md_link_pattern = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
    for match in md_link_pattern.finditer(markdown):
        url = match.group(2).strip()
        # Strip optional markdown title attribute: (url "title") or (url 'title')
        url = re.split(r"""\s+["']""", url, maxsplit=1)[0].strip()
        if url.startswith(("http://", "https://")):
            urls.append(url)

    # Match bare URLs
    bare_url_pattern = re.compile(r"https?://[^\s<>\"\'\)]+")
    for match in bare_url_pattern.finditer(markdown):
        url = match.group(0)
        if url not in urls:
            urls.append(url)

    return urls


def extract_links_from_html(html: str, base_url: str | None = None) -> list[str]:
    """Extract URLs from HTML <a> tags.

    Resolves relative URLs using base_url if provided.
    """
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        if isinstance(href, list):
            href = href[0]
        href = href.strip()

        if href.startswith(("http://", "https://")):
            urls.append(href)
        elif base_url and href.startswith("/"):
            urls.append(urljoin(base_url, href))

    return urls


def extract_schema_org_links(html: str) -> list[str]:
    """Extract social media links from Schema.org JSON-LD sameAs property."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    for script_tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script_tag.string or "")
            if isinstance(data, dict):
                same_as = data.get("sameAs", [])
                if isinstance(same_as, str):
                    same_as = [same_as]
                if isinstance(same_as, list):
                    for url in same_as:
                        if isinstance(url, str) and url.startswith(("http://", "https://")):
                            urls.append(url)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        same_as = item.get("sameAs", [])
                        if isinstance(same_as, str):
                            same_as = [same_as]
                        if isinstance(same_as, list):
                            for url in same_as:
                                if isinstance(url, str) and url.startswith(("http://", "https://")):
                                    urls.append(url)
        except (json.JSONDecodeError, TypeError):
            continue

    return urls


def extract_meta_tag_links(html: str) -> list[str]:
    """Extract social media links from meta tags (twitter:site, og:url, etc.)."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    # Twitter card meta tags
    for tag in soup.find_all("meta", attrs={"name": re.compile(r"twitter:", re.IGNORECASE)}):
        content = tag.get("content", "")
        if isinstance(content, str) and content.startswith(("http://", "https://")):
            urls.append(content)
        elif isinstance(content, str) and content.startswith("@"):
            urls.append(f"https://twitter.com/{content.lstrip('@')}")

    # Open Graph meta tags
    for tag in soup.find_all("meta", attrs={"property": re.compile(r"og:", re.IGNORECASE)}):
        content = tag.get("content", "")
        if isinstance(content, str) and content.startswith(("http://", "https://")):
            urls.append(content)

    return urls


def extract_aria_label_links(html: str) -> list[str]:
    """Extract links from elements with aria-labels or title attributes related to social media."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    social_keywords = [
        "linkedin",
        "twitter",
        "facebook",
        "instagram",
        "youtube",
        "github",
        "tiktok",
        "medium",
        "mastodon",
        "threads",
        "pinterest",
        "bluesky",
        "social",
    ]

    for tag in soup.find_all(["a", "link"], attrs={"aria-label": True}):
        label = tag.get("aria-label", "").lower()
        if any(kw in label for kw in social_keywords):
            href = tag.get("href", "")
            if isinstance(href, str) and href.startswith(("http://", "https://")):
                urls.append(href)

    for tag in soup.find_all(["a", "link"], attrs={"title": True}):
        title = tag.get("title", "").lower()
        if any(kw in title for kw in social_keywords):
            href = tag.get("href", "")
            if isinstance(href, str) and href.startswith(("http://", "https://")):
                urls.append(href)

    return urls


_TWITTER_STATUS_PATTERN = re.compile(
    r"https?://(?:www\.)?(twitter|x)\.com/[^/]+/status/", re.IGNORECASE
)

_TWITTER_DOMAIN_PATTERN = re.compile(r"https?://(?:www\.)?(twitter|x)\.com/", re.IGNORECASE)


def is_twitter_embed_url(url: str) -> bool:
    """Check if a URL is a Twitter/X status embed (tweet link).

    These appear on pages that embed tweet carousels or testimonials.
    Both the /status/ URLs and the profile URLs of tweet authors are noise.
    """
    return bool(_TWITTER_STATUS_PATTERN.search(url))


def filter_twitter_embeds(
    urls: list[str],
    trusted_urls: set[str] | None = None,
) -> list[str]:
    """Remove Twitter/X URLs that are part of embedded tweet content.

    When a page embeds tweets (testimonials, press mentions), the scraped
    content includes /status/ links and profile links of third-party users.
    These are not the company's own social accounts.

    Strategy: if ANY /status/ URL is present, the page has embedded tweets.
    In that case:
    - Always remove /status/ URLs
    - Remove ALL Twitter/X profile URLs UNLESS they appear in trusted_urls
      (from structured sources like schema.org, meta tags, aria-labels)

    Args:
        urls: All extracted URLs.
        trusted_urls: URLs from structured/authoritative sources that should
            be preserved even when embeds are present.
    """
    has_embeds = any(is_twitter_embed_url(u) for u in urls)
    if not has_embeds:
        return urls

    safe_urls = trusted_urls or set()

    filtered: list[str] = []
    for url in urls:
        # Always drop /status/ URLs
        if is_twitter_embed_url(url):
            continue

        # Drop Twitter/X profile URLs unless they came from a trusted source
        if _TWITTER_DOMAIN_PATTERN.match(url) and url not in safe_urls:
            continue

        filtered.append(url)

    return filtered


def extract_all_social_links(
    html: str | None,
    markdown: str | None,
    base_url: str | None = None,
) -> list[str]:
    """Extract social media links using all strategies.

    Combines results from markdown, HTML, Schema.org, meta tags, and aria-labels.
    Filters out Twitter/X embed noise. Returns deduplicated list.
    """
    all_urls: list[str] = []
    # Trusted URLs come from structured/authoritative sources (schema.org,
    # meta tags, aria-labels). These are preserved even when embed filtering
    # removes other Twitter/X URLs from the page.
    trusted_urls: set[str] = set()

    if markdown:
        all_urls.extend(extract_links_from_markdown(markdown))

    if html:
        all_urls.extend(extract_links_from_html(html, base_url))

        schema_urls = extract_schema_org_links(html)
        meta_urls = extract_meta_tag_links(html)
        aria_urls = extract_aria_label_links(html)

        trusted_urls.update(schema_urls)
        trusted_urls.update(meta_urls)
        trusted_urls.update(aria_urls)

        all_urls.extend(schema_urls)
        all_urls.extend(meta_urls)
        all_urls.extend(aria_urls)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_urls: list[str] = []
    for url in all_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)

    # Filter out Twitter/X embed noise
    unique_urls = filter_twitter_embeds(unique_urls, trusted_urls)

    return unique_urls
