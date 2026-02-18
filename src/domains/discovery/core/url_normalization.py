"""URL normalization for social media profiles."""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse


def normalize_social_url(url: str) -> str:
    """Normalize a social media URL to its canonical form.

    Rules:
    - Remove query parameters
    - Remove trailing slashes
    - Lowercase
    - Remove www.
    - Platform-specific normalization
    """
    url = url.strip()
    parsed = urlparse(url)

    # Lowercase netloc, remove www
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # Remove query params and fragments
    path = parsed.path.rstrip("/")

    # Rebuild clean URL
    scheme = parsed.scheme.lower() or "https"
    clean_url = urlunparse((scheme, netloc, path, "", "", ""))

    # Apply platform-specific normalization
    clean_url = _normalize_github(clean_url)
    clean_url = _normalize_linkedin(clean_url)
    clean_url = _normalize_youtube(clean_url)

    return clean_url


def _normalize_github(url: str) -> str:
    """Normalize GitHub URLs to org level (remove repo paths)."""
    match = re.match(r"(https?://github\.com/[^/]+)(/.*)?$", url, re.IGNORECASE)
    if match:
        return match.group(1)
    return url


def _normalize_linkedin(url: str) -> str:
    """Normalize LinkedIn URLs (remove /about, /posts, etc.)."""
    match = re.match(
        r"(https?://(?:www\.)?linkedin\.com/(?:company|in)/[^/]+)(/.*)?$",
        url,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)
    return url


def _normalize_youtube(url: str) -> str:
    """Normalize YouTube URLs to channel level."""
    # Handle @handle format
    match = re.match(r"(https?://(?:www\.)?youtube\.com/@[^/]+)(/.*)?$", url, re.IGNORECASE)
    if match:
        return match.group(1)
    # Handle /channel/ID format
    match = re.match(r"(https?://(?:www\.)?youtube\.com/channel/[^/]+)(/.*)?$", url, re.IGNORECASE)
    if match:
        return match.group(1)
    # Handle /c/name format
    match = re.match(r"(https?://(?:www\.)?youtube\.com/c/[^/]+)(/.*)?$", url, re.IGNORECASE)
    if match:
        return match.group(1)
    return url


def extract_account_handle(url: str, platform: str) -> str | None:
    """Extract the account handle/identifier from a platform URL."""
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split("/") if p]

    if not path_parts:
        return None

    if platform == "linkedin":
        # linkedin.com/company/X or linkedin.com/in/X
        if len(path_parts) >= 2:
            return path_parts[1]
    elif platform in ("twitter", "x"):
        return path_parts[0] if path_parts else None
    elif platform == "youtube":
        if path_parts[0].startswith("@"):
            return path_parts[0]
        elif len(path_parts) >= 2:
            return path_parts[1]
    elif platform == "github":
        return path_parts[0] if path_parts else None
    elif platform == "tiktok":
        return path_parts[0] if path_parts and path_parts[0].startswith("@") else None
    elif platform == "instagram" or platform == "facebook":
        return path_parts[0] if path_parts else None
    elif platform == "bluesky":
        # bsky.app/profile/X
        if len(path_parts) >= 2:
            return path_parts[1]
    elif platform == "medium":
        if path_parts and path_parts[0].startswith("@"):
            return path_parts[0]
        # X.medium.com case
        netloc = parsed.netloc.lower()
        if netloc.endswith(".medium.com"):
            return netloc.replace(".medium.com", "")
    elif platform == "threads":
        return path_parts[0] if path_parts and path_parts[0].startswith("@") else None
    elif platform == "mastodon":
        for part in path_parts:
            if part.startswith("@"):
                return part
    elif platform == "pinterest":
        return path_parts[0] if path_parts else None

    return None
