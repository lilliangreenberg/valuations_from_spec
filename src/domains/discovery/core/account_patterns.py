"""Platform-specific account patterns for social media classification."""

from __future__ import annotations

from urllib.parse import urlparse

# Patterns that indicate a URL is NOT a valid account (generic/utility pages)
EXCLUDED_PATHS: dict[str, list[str]] = {
    "linkedin": ["login", "signup", "help", "learning", "jobs", "feed", "messaging"],
    "twitter": [
        "login",
        "signup",
        "explore",
        "search",
        "settings",
        "home",
        "i",
        "hashtag",
    ],
    "youtube": ["watch", "results", "feed", "playlist", "gaming", "premium"],
    "facebook": [
        "login",
        "signup",
        "help",
        "marketplace",
        "watch",
        "gaming",
        "groups",
    ],
    "instagram": ["explore", "accounts", "p", "reel", "stories"],
    "github": [
        "login",
        "signup",
        "explore",
        "marketplace",
        "settings",
        "trending",
        "topics",
    ],
    "tiktok": ["discover", "upload", "live"],
    "pinterest": ["pin", "search", "ideas", "today"],
}


def is_excluded_path(url: str, platform: str) -> bool:
    """Check if a URL path is a generic/utility page (not an account)."""
    parsed = urlparse(url)
    path_parts = [p.lower() for p in parsed.path.split("/") if p]

    if not path_parts:
        return True  # Root URL is not an account

    excluded = EXCLUDED_PATHS.get(platform, [])
    first_part = path_parts[0]

    # For platforms that use @ prefix
    if platform in ("tiktok", "threads", "mastodon", "medium"):
        return not path_parts[0].startswith("@")

    # For YouTube, check for valid channel patterns
    if platform == "youtube":
        return first_part not in ("c", "channel", "user") and not first_part.startswith("@")

    # For LinkedIn, must be /company/ or /in/
    if platform == "linkedin":
        return first_part not in ("company", "in")

    # For Bluesky, must be /profile/
    if platform == "bluesky":
        return first_part != "profile"

    return first_part in excluded


def is_company_account_pattern(handle: str, company_name: str) -> bool:
    """Check if a social media handle matches the company name pattern.

    Returns True if the handle appears to belong to the company.
    """
    if not handle or not company_name:
        return False

    handle_clean = handle.lower().strip("@").replace("-", "").replace("_", "")
    company_clean = company_name.lower().replace(" ", "").replace("-", "").replace("_", "")

    # Exact match or close match
    if handle_clean == company_clean:
        return True

    # Handle contains company name or vice versa
    if company_clean in handle_clean or handle_clean in company_clean:
        return True

    # Check for common abbreviations (first letters of each word)
    words = company_name.lower().split()
    if len(words) > 1:
        initials = "".join(w[0] for w in words if w)
        if handle_clean == initials:
            return True

    return False
