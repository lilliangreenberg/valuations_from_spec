"""Extract account handles from social media URLs."""

from __future__ import annotations

from urllib.parse import urlparse


def extract_handle(url: str) -> str | None:
    """Extract the account handle/username from a social media URL.

    Returns the handle without any @ prefix, or None if unable to extract.
    """
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split("/") if p]

    if not path_parts:
        return None

    netloc = parsed.netloc.lower()

    # LinkedIn
    if "linkedin.com" in netloc and len(path_parts) >= 2 and path_parts[0] in ("company", "in"):
        return path_parts[1]

    # Twitter/X
    if "twitter.com" in netloc or "x.com" in netloc:
        handle = path_parts[0]
        return handle.lstrip("@") if handle else None

    # YouTube
    if "youtube.com" in netloc:
        if path_parts[0].startswith("@"):
            return path_parts[0].lstrip("@")
        if len(path_parts) >= 2 and path_parts[0] in (
            "c",
            "channel",
            "user",
        ):
            return path_parts[1]

    # GitHub
    if "github.com" in netloc:
        return path_parts[0]

    # Instagram
    if "instagram.com" in netloc:
        return path_parts[0]

    # Facebook
    if "facebook.com" in netloc or "fb.com" in netloc:
        return path_parts[0]

    # TikTok
    if "tiktok.com" in netloc and path_parts[0].startswith("@"):
        return path_parts[0].lstrip("@")

    # Medium
    if "medium.com" in netloc:
        if path_parts[0].startswith("@"):
            return path_parts[0].lstrip("@")
    elif netloc.endswith(".medium.com"):
        return netloc.replace(".medium.com", "")

    # Bluesky
    if "bsky.app" in netloc and len(path_parts) >= 2 and path_parts[0] == "profile":
        return path_parts[1]

    # Threads
    if "threads.net" in netloc and path_parts[0].startswith("@"):
        return path_parts[0].lstrip("@")

    # Mastodon
    if "mastodon" in netloc:
        for part in path_parts:
            if part.startswith("@"):
                return part.lstrip("@")

    # Pinterest
    if "pinterest.com" in netloc:
        return path_parts[0]

    return path_parts[0] if path_parts else None
