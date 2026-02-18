"""Social media platform detection from URLs."""

from __future__ import annotations

import re
from enum import StrEnum


class Platform(StrEnum):
    LINKEDIN = "linkedin"
    TWITTER = "twitter"
    YOUTUBE = "youtube"
    BLUESKY = "bluesky"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    GITHUB = "github"
    TIKTOK = "tiktok"
    MEDIUM = "medium"
    MASTODON = "mastodon"
    THREADS = "threads"
    PINTEREST = "pinterest"
    BLOG = "blog"


# Platform detection patterns (order matters for some overlapping patterns)
PLATFORM_PATTERNS: list[tuple[Platform, re.Pattern[str]]] = [
    (Platform.LINKEDIN, re.compile(r"linkedin\.com/(company|in)/", re.IGNORECASE)),
    (Platform.TWITTER, re.compile(r"(twitter|x)\.com/", re.IGNORECASE)),
    (Platform.YOUTUBE, re.compile(r"youtube\.com/(c/|channel/|@|user/)", re.IGNORECASE)),
    (Platform.BLUESKY, re.compile(r"bsky\.app/profile/", re.IGNORECASE)),
    (Platform.FACEBOOK, re.compile(r"(facebook|fb)\.com/", re.IGNORECASE)),
    (Platform.INSTAGRAM, re.compile(r"instagram\.com/", re.IGNORECASE)),
    (Platform.GITHUB, re.compile(r"github\.com/[^/]+", re.IGNORECASE)),
    (Platform.TIKTOK, re.compile(r"tiktok\.com/@", re.IGNORECASE)),
    (Platform.MEDIUM, re.compile(r"(medium\.com/@|\.medium\.com)", re.IGNORECASE)),
    (Platform.MASTODON, re.compile(r"(mastodon\.|/@[a-zA-Z0-9_]+)", re.IGNORECASE)),
    (Platform.THREADS, re.compile(r"threads\.net/@", re.IGNORECASE)),
    (Platform.PINTEREST, re.compile(r"pinterest\.com/", re.IGNORECASE)),
]


def detect_platform(url: str) -> Platform | None:
    """Detect the social media platform from a URL.

    Returns the matched Platform enum or None if no platform detected.
    """
    for platform, pattern in PLATFORM_PATTERNS:
        if pattern.search(url):
            return platform
    return None


def is_social_media_url(url: str) -> bool:
    """Check if a URL is a recognized social media platform URL."""
    return detect_platform(url) is not None
