"""LinkedIn profile parsing from HTML and search snippets.

Pure functions for extracting person name, title, and profile URL
from LinkedIn people cards and Kagi search results. No I/O operations.
"""

from __future__ import annotations

import re

from src.domains.leadership.core.title_detection import (
    is_leadership_title,
    rank_title,
)

# Regex to match LinkedIn personal profile URLs (/in/slug)
_LINKEDIN_PROFILE_PATTERN = re.compile(
    r"https?://(?:www\.)?linkedin\.com/in/([a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)

# Pattern to extract name and title from LinkedIn title strings
# e.g., "John Smith - CEO - Acme Corp | LinkedIn"
_TITLE_NAME_PATTERN = re.compile(
    r"^([^-|]+?)\s*[-|]\s*(.+?)(?:\s*[-|]\s*.+)?(?:\s*\|\s*LinkedIn)?$",
    re.IGNORECASE,
)

# Pattern to extract name from card-like HTML
_NAME_PATTERN = re.compile(
    r'(?:profile-title|profile-name|card__title)["\s>]*([^<]+)',
    re.IGNORECASE,
)

# Pattern to extract subtitle/title from card-like HTML
_SUBTITLE_PATTERN = re.compile(
    r'(?:subtitle|card__subtitle|profile-role)["\s>]*([^<]+)',
    re.IGNORECASE,
)

# Pattern to extract href to /in/ profile
_HREF_IN_PATTERN = re.compile(
    r'href="(/in/[a-zA-Z0-9_-]+)"',
    re.IGNORECASE,
)


def parse_linkedin_people_card(card_html: str) -> dict[str, str] | None:
    """Extract person data from a LinkedIn people tab card HTML fragment.

    Returns dict with keys: name, title, profile_url.
    Returns None if essential data cannot be extracted.
    """
    if not card_html or not card_html.strip():
        return None

    # Extract profile URL (must be /in/ not /company/)
    href_match = _HREF_IN_PATTERN.search(card_html)
    if not href_match:
        return None

    profile_path = href_match.group(1)
    profile_url = f"https://www.linkedin.com{profile_path}"

    # Extract name
    name_match = _NAME_PATTERN.search(card_html)
    name = name_match.group(1).strip() if name_match else None

    # Extract title/subtitle
    subtitle_match = _SUBTITLE_PATTERN.search(card_html)
    title = subtitle_match.group(1).strip() if subtitle_match else ""

    if not name:
        return None

    return {
        "name": name,
        "title": title,
        "profile_url": profile_url,
    }


def parse_kagi_leadership_result(
    title: str,
    snippet: str,
    url: str,
) -> dict[str, str] | None:
    """Extract person data from a Kagi search result.

    The result must reference a LinkedIn personal profile (/in/) to be valid.
    Returns dict with keys: name, title, profile_url.
    Returns None if not a valid LinkedIn personal profile result.
    """
    # Check if URL is a LinkedIn personal profile
    profile_match = _LINKEDIN_PROFILE_PATTERN.match(url)
    if not profile_match:
        # Also check if URL is embedded in snippet
        profile_from_snippet = extract_linkedin_profile_url(snippet)
        if not profile_from_snippet:
            return None
        profile_url = profile_from_snippet
    else:
        profile_url = url.split("?")[0].rstrip("/")

    # Parse name and title from the search result title
    # Common format: "John Smith - CEO - Acme Corp | LinkedIn"
    title_match = _TITLE_NAME_PATTERN.match(title)
    if title_match:
        person_name = title_match.group(1).strip()
        person_title = title_match.group(2).strip()
    else:
        # Try simpler extraction: first part before pipe
        parts = title.split("|")
        if parts:
            name_parts = parts[0].strip().split("-")
            person_name = name_parts[0].strip() if name_parts else ""
            person_title = name_parts[1].strip() if len(name_parts) > 1 else ""
        else:
            return None

    if not person_name:
        return None

    return {
        "name": person_name,
        "title": person_title,
        "profile_url": profile_url,
    }


def extract_linkedin_profile_url(text: str) -> str | None:
    """Extract the first LinkedIn personal profile URL from arbitrary text.

    Only matches /in/ URLs (personal profiles), not /company/ URLs.
    Returns the clean URL without query params, or None if not found.
    """
    match = _LINKEDIN_PROFILE_PATTERN.search(text)
    if not match:
        return None
    return match.group(0).split("?")[0].rstrip("/")


def filter_leadership_results(
    people: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Filter, deduplicate, and sort a list of people by leadership relevance.

    - Removes non-leadership titles
    - Deduplicates by profile URL (keeps first occurrence)
    - Sorts by title seniority (CEO first)
    """
    if not people:
        return []

    # Filter to leadership only
    leaders = [p for p in people if is_leadership_title(p.get("title", ""))]

    # Deduplicate by profile URL
    seen_urls: set[str] = set()
    unique_leaders: list[dict[str, str]] = []
    for person in leaders:
        url = person.get("profile_url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_leaders.append(person)

    # Sort by seniority (lower rank = more senior = first)
    unique_leaders.sort(key=lambda p: rank_title(p.get("title", "")))

    return unique_leaders
