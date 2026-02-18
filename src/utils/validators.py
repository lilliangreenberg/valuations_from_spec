"""URL and data validation utilities."""

from __future__ import annotations

import re
from urllib.parse import urlparse


def is_valid_url(url: str) -> bool:
    """Check if a string is a valid HTTP/HTTPS URL."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def is_valid_md5(checksum: str) -> bool:
    """Check if a string is a valid MD5 hex digest (32 lowercase hex chars)."""
    return bool(re.match(r"^[0-9a-f]{32}$", checksum))


def normalize_url(url: str) -> str:
    """Normalize a URL by lowercasing, removing trailing slashes and www."""
    url = url.strip().lower()
    parsed = urlparse(url)
    netloc = parsed.netloc
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{netloc}{path}"


def extract_domain(url: str) -> str:
    """Extract the domain from a URL."""
    parsed = urlparse(url)
    netloc = parsed.netloc
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def is_valid_checksum_hex(value: str) -> bool:
    """Validate a hex string is a valid checksum (32 chars, lowercase)."""
    return bool(re.match(r"^[0-9a-f]{32}$", value.lower()))
