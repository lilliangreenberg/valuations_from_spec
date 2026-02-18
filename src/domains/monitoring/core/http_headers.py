"""HTTP header parsing utilities."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


def parse_last_modified(header_value: str | None) -> datetime | None:
    """Parse HTTP Last-Modified header value to datetime.

    Handles RFC 2822 date format from HTTP headers.
    Returns None if header is missing or unparseable.
    """
    if not header_value:
        return None
    try:
        dt = parsedate_to_datetime(header_value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None


def extract_content_type(headers: dict[str, str]) -> str | None:
    """Extract Content-Type from headers dict (case-insensitive)."""
    for key, value in headers.items():
        if key.lower() == "content-type":
            return value.split(";")[0].strip()
    return None


def is_html_content(content_type: str | None) -> bool:
    """Check if content type indicates HTML content."""
    if not content_type:
        return False
    return content_type.lower() in ("text/html", "application/xhtml+xml")
