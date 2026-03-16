"""Pure functions for dashboard display formatting.

No I/O operations. These are registered as Jinja2 template filters.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse


def format_relative_time(iso_datetime: str | None) -> str:
    """Convert ISO datetime string to human-readable relative time.

    Examples: "just now", "5 minutes ago", "3 days ago", "2 months ago".
    """
    if not iso_datetime:
        return "N/A"

    try:
        parsed = datetime.fromisoformat(iso_datetime.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
    except (ValueError, AttributeError):
        return "N/A"

    now = datetime.now(UTC)
    delta = now - parsed
    seconds = int(delta.total_seconds())

    if seconds < 0:
        return "just now"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    if seconds < 2592000:
        days = seconds // 86400
        return f"{days} day{'s' if days != 1 else ''} ago"
    if seconds < 31536000:
        months = seconds // 2592000
        return f"{months} month{'s' if months != 1 else ''} ago"

    years = seconds // 31536000
    return f"{years} year{'s' if years != 1 else ''} ago"


def significance_badge_class(classification: str | None) -> str:
    """Return CSS class for a significance classification badge."""
    mapping: dict[str, str] = {
        "significant": "badge-significant",
        "insignificant": "badge-insignificant",
        "uncertain": "badge-uncertain",
    }
    return mapping.get(classification or "", "badge-unknown")


def sentiment_color_class(sentiment: str | None) -> str:
    """Return CSS class for sentiment coloring."""
    mapping: dict[str, str] = {
        "positive": "text-positive",
        "negative": "text-negative",
        "neutral": "text-neutral",
        "mixed": "text-mixed",
    }
    return mapping.get(sentiment or "", "text-neutral")


def magnitude_indicator(magnitude: str | None) -> str:
    """Return text indicator for change magnitude."""
    mapping: dict[str, str] = {
        "minor": "[MINOR]",
        "moderate": "[MODERATE]",
        "major": "[MAJOR]",
    }
    return mapping.get(magnitude or "", "")


def truncate_url(url: str, max_length: int = 60) -> str:
    """Truncate a URL for display while keeping the domain visible."""
    if not url:
        return ""
    if len(url) <= max_length:
        return url

    parsed = urlparse(url)
    domain = parsed.netloc
    path = parsed.path

    remaining = max_length - len(domain) - 3  # 3 for "..."
    if remaining > 0 and path:
        return f"{domain}{path[:remaining]}..."
    return f"{domain}..."


def platform_display_name(platform: str) -> str:
    """Convert platform enum value to display name."""
    mapping: dict[str, str] = {
        "linkedin": "LinkedIn",
        "twitter": "Twitter/X",
        "youtube": "YouTube",
        "bluesky": "Bluesky",
        "facebook": "Facebook",
        "instagram": "Instagram",
        "github": "GitHub",
        "tiktok": "TikTok",
        "medium": "Medium",
        "mastodon": "Mastodon",
        "threads": "Threads",
        "pinterest": "Pinterest",
        "blog": "Blog",
    }
    return mapping.get(platform.lower(), platform.title())


def status_badge_class(status: str | None) -> str:
    """Return CSS class for company status badge."""
    mapping: dict[str, str] = {
        "operational": "status-operational",
        "likely_closed": "status-closed",
        "uncertain": "status-uncertain",
    }
    return mapping.get(status or "", "status-unknown")


def format_confidence(confidence: float | None) -> str:
    """Format confidence score as percentage string."""
    if confidence is None:
        return "N/A"
    return f"{confidence * 100:.0f}%"


def empty_state_message(context: str) -> str:
    """Return context-appropriate message when no data exists."""
    messages: dict[str, str] = {
        "activity": (
            "All quiet across your portfolio. No significant changes detected in the past 30 days."
        ),
        "changes": "No changes match the current filters.",
        "news": "No news articles match the current filters.",
        "leadership": "No leadership profiles found.",
        "social": "No social media links discovered for this company.",
        "snapshots": "No snapshots captured yet.",
        "companies": "No companies loaded. Run 'extract-companies' to get started.",
        "operations": "No tasks have been run yet.",
    }
    return messages.get(context, "No data available.")


def format_date_short(iso_datetime: str | None) -> str:
    """Format ISO datetime as short date string (YYYY-MM-DD)."""
    if not iso_datetime:
        return "N/A"
    return iso_datetime[:10]


def freshness_tier(iso_datetime: str | None) -> str:
    """Classify a snapshot date into a freshness tier.

    Returns one of: 'fresh', 'recent', 'stale', 'very_stale', 'never'.
    """
    if not iso_datetime:
        return "never"

    try:
        parsed = datetime.fromisoformat(iso_datetime.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
    except (ValueError, AttributeError):
        return "never"

    now = datetime.now(UTC)
    days = (now - parsed).days

    if days < 7:
        return "fresh"
    if days < 30:
        return "recent"
    if days < 90:
        return "stale"
    return "very_stale"


def freshness_tier_label(tier: str) -> str:
    """Return human-readable label for a freshness tier."""
    labels: dict[str, str] = {
        "fresh": "Fresh (< 7 days)",
        "recent": "Recent (7-30 days)",
        "stale": "Stale (30-90 days)",
        "very_stale": "Very Stale (> 90 days)",
        "never": "Never Scanned",
    }
    return labels.get(tier, tier)


def health_grid_color(status: str | None, is_manual_override: bool = False) -> str:
    """Return CSS color class for a company health grid cell."""
    if status == "likely_closed" and is_manual_override:
        return "health-manual-closed"
    mapping: dict[str, str] = {
        "operational": "health-green",
        "likely_closed": "health-red",
        "uncertain": "health-yellow",
    }
    return mapping.get(status or "", "health-gray")
