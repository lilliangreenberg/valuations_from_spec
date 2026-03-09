"""Pure functions for social media content analysis.

Extracts posting dates from blog/Medium content, checks posting inactivity,
and prepares social context strings for LLM enrichment.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

# Month name mappings for date parsing
_MONTH_NAMES: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# ISO 8601 date pattern: 2025-01-15
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

# "January 15, 2025" or "Jan 15, 2025"
_MONTH_DAY_YEAR_RE = re.compile(
    r"\b(" + "|".join(_MONTH_NAMES.keys()) + r")\s+(\d{1,2}),?\s+(\d{4})\b",
    re.IGNORECASE,
)

# "15 January 2025" or "15 Jan 2025"
_DAY_MONTH_YEAR_RE = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(_MONTH_NAMES.keys()) + r")\s+(\d{4})\b",
    re.IGNORECASE,
)

# Relative dates: "3 days ago", "2 weeks ago", "1 month ago"
_RELATIVE_DATE_RE = re.compile(
    r"\b(\d+)\s+(day|days|week|weeks|month|months)\s+ago\b",
    re.IGNORECASE,
)


def _parse_iso_date(match: re.Match[str]) -> datetime | None:
    """Parse an ISO 8601 date match into a datetime."""
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _parse_month_day_year(match: re.Match[str]) -> datetime | None:
    """Parse a 'Month Day, Year' match into a datetime."""
    month_name = match.group(1).lower()
    day = int(match.group(2))
    year = int(match.group(3))
    month = _MONTH_NAMES.get(month_name)
    if month is None:
        return None
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _parse_day_month_year(match: re.Match[str]) -> datetime | None:
    """Parse a 'Day Month Year' match into a datetime."""
    day = int(match.group(1))
    month_name = match.group(2).lower()
    year = int(match.group(3))
    month = _MONTH_NAMES.get(month_name)
    if month is None:
        return None
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _parse_relative_date(match: re.Match[str], reference_date: datetime) -> datetime | None:
    """Parse a relative date like '3 days ago' into a naive datetime.

    Always returns a naive datetime (tzinfo stripped) so it can be compared
    with other regex-parsed dates which are always naive.
    """
    # Work with naive reference for consistency with other parsed dates
    naive_ref = reference_date.replace(tzinfo=None)
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit in ("day", "days"):
        return naive_ref - timedelta(days=amount)
    elif unit in ("week", "weeks"):
        return naive_ref - timedelta(weeks=amount)
    elif unit in ("month", "months"):
        # Approximate months as 30 days
        return naive_ref - timedelta(days=amount * 30)
    return None


def extract_latest_post_date(
    markdown: str,
    reference_date: datetime | None = None,
) -> datetime | None:
    """Extract the most recent post/article date from scraped blog/Medium content.

    Parses multiple date formats in order of reliability:
    1. ISO 8601 dates: 2025-01-15
    2. "Month Day, Year": January 15, 2025 / Jan 15, 2025
    3. "Day Month Year": 15 January 2025 / 15 Jan 2025
    4. Relative dates: "3 days ago", "2 weeks ago" (requires reference_date)

    Args:
        markdown: The scraped content to extract dates from.
        reference_date: Reference date for resolving relative dates.
            Should be provided by the caller (service layer), not defaulted here.

    Returns:
        The most recent valid date found, or None if no dates detected.
    """
    if not markdown:
        return None

    candidates: list[datetime] = []

    for match in _ISO_DATE_RE.finditer(markdown):
        parsed = _parse_iso_date(match)
        if parsed is not None:
            candidates.append(parsed)

    for match in _MONTH_DAY_YEAR_RE.finditer(markdown):
        parsed = _parse_month_day_year(match)
        if parsed is not None:
            candidates.append(parsed)

    for match in _DAY_MONTH_YEAR_RE.finditer(markdown):
        parsed = _parse_day_month_year(match)
        if parsed is not None:
            candidates.append(parsed)

    if reference_date is not None:
        for match in _RELATIVE_DATE_RE.finditer(markdown):
            parsed = _parse_relative_date(match, reference_date)
            if parsed is not None:
                candidates.append(parsed)

    if not candidates:
        return None

    # Filter out obviously invalid dates (future dates beyond reference or unreasonable past)
    # Parsed dates are always naive, so strip tzinfo from reference_date for comparison
    naive_ref = reference_date.replace(tzinfo=None) if reference_date is not None else None
    valid_candidates: list[datetime] = []
    for candidate in candidates:
        # Reject dates before 2000 (unlikely to be a real blog post date)
        if candidate.year < 2000:
            continue
        # Reject dates more than 1 day in the future relative to reference
        if naive_ref is not None and candidate > naive_ref + timedelta(days=1):
            continue
        valid_candidates.append(candidate)

    if not valid_candidates:
        return None

    return max(valid_candidates)


def check_posting_inactivity(
    latest_post_date: datetime | None,
    threshold_days: int = 365,
    *,
    reference_date: datetime,
) -> tuple[bool, int | None]:
    """Check whether a social media source is inactive based on posting recency.

    Args:
        latest_post_date: The most recent post date, or None if no dates found.
        threshold_days: Days of inactivity before flagging as inactive (default: 365).
        reference_date: The current date for comparison (keyword-only).

    Returns:
        Tuple of (is_inactive, days_since_last_post).
        If latest_post_date is None, returns (True, None) -- no dates found is inactive.
    """
    if latest_post_date is None:
        return True, None

    # Ensure both are naive for comparison (parsed dates are always naive)
    naive_ref = reference_date.replace(tzinfo=None)
    naive_post = latest_post_date.replace(tzinfo=None)
    delta = naive_ref - naive_post
    days_since = delta.days

    return days_since > threshold_days, days_since


def prepare_social_context(
    social_snapshots: list[dict[str, str | None]],
    inactivity_results: list[tuple[str, bool, int | None]],
    max_chars: int = 2000,
) -> str:
    """Aggregate social media content into a formatted string for LLM consumption.

    This is the bridge between social media data and the existing LLM prompt system.

    Args:
        social_snapshots: List of dicts with keys:
            source_url, source_type, content_markdown, latest_post_date.
        inactivity_results: List of (source_url, is_inactive, days_since_last_post).
        max_chars: Maximum character budget for the output string.

    Returns:
        Formatted social context string, or empty string if no data.
    """
    if not social_snapshots:
        return ""

    # Build a lookup for inactivity results
    inactivity_map: dict[str, tuple[bool, int | None]] = {
        url: (is_inactive, days) for url, is_inactive, days in inactivity_results
    }

    # Calculate character budget per source for content excerpts
    num_sources = len(social_snapshots)
    # Reserve chars for headers/metadata (~150 chars per source)
    header_budget = 150 * num_sources
    content_budget = max(0, max_chars - header_budget)
    chars_per_source = content_budget // num_sources if num_sources > 0 else 0

    sections: list[str] = ["--- Social Media Activity ---"]

    for snapshot in social_snapshots:
        source_url = snapshot.get("source_url", "unknown")
        source_type = snapshot.get("source_type", "unknown")
        content = snapshot.get("content_markdown") or ""
        post_date = snapshot.get("latest_post_date")

        is_inactive, days = inactivity_map.get(str(source_url), (True, None))

        # Format status line
        if is_inactive:
            if days is not None:
                status = f"INACTIVE ({days} days since last post)"
            else:
                status = "INACTIVE (no posting date found)"
        else:
            status = "ACTIVE"

        # Format post date
        date_str = str(post_date) if post_date else "None detected"
        if days is not None and not is_inactive:
            date_str = f"{date_str} ({days} days ago)"

        # Truncate content excerpt
        excerpt = str(content)[:chars_per_source].strip()
        if len(str(content)) > chars_per_source:
            excerpt += "..."

        section = (
            f"Source: {source_url} ({source_type})\n"
            f"Last post: {date_str}\n"
            f"Status: {status}\n"
            f"Content excerpt: {excerpt}"
        )
        sections.append(section)

    sections.append("---")
    return "\n\n".join(sections)
