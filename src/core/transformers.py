"""Data transformation functions for converting API responses to models."""

from __future__ import annotations

import contextlib
import hashlib
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any


def prepare_snapshot_data(
    company_id: int,
    url: str,
    scrape_result: dict[str, Any],
) -> dict[str, Any]:
    """Transform a Firecrawl scrape result into snapshot data dict.

    The returned dict can be used to construct a Snapshot model.
    """
    markdown = scrape_result.get("markdown") or ""
    html = scrape_result.get("html") or ""
    status_code = scrape_result.get("statusCode") or scrape_result.get("status_code")
    error = scrape_result.get("error")
    has_paywall = scrape_result.get("has_paywall", False)
    has_auth_required = scrape_result.get("has_auth_required", False)

    # Compute checksum from markdown content
    content_checksum = None
    if markdown:
        content_checksum = hashlib.md5(markdown.encode("utf-8")).hexdigest()

    # Parse HTTP Last-Modified if available
    metadata = scrape_result.get("metadata", {}) or {}
    last_modified_str = None
    if isinstance(metadata, dict):
        last_modified_str = metadata.get("last-modified") or metadata.get("Last-Modified")

    http_last_modified = None
    if last_modified_str:
        with contextlib.suppress(ValueError, TypeError):
            http_last_modified = parsedate_to_datetime(last_modified_str).isoformat()

    now = datetime.now(UTC).isoformat()

    return {
        "company_id": company_id,
        "url": url,
        "content_markdown": markdown or None,
        "content_html": html or None,
        "status_code": status_code,
        "captured_at": now,
        "has_paywall": has_paywall,
        "has_auth_required": has_auth_required,
        "error_message": error,
        "content_checksum": content_checksum,
        "http_last_modified": http_last_modified,
        "capture_metadata": None,
    }


def prepare_company_data(
    name: str,
    homepage_url: str | None,
    source_sheet: str,
) -> dict[str, Any]:
    """Prepare company data for database insertion."""
    now = datetime.now(UTC).isoformat()
    return {
        "name": name.strip(),
        "homepage_url": homepage_url,
        "source_sheet": source_sheet,
        "flagged_for_review": False,
        "flag_reason": None,
        "created_at": now,
        "updated_at": now,
    }


def normalize_company_name(name: str) -> str:
    """Normalize company name: strip whitespace, title-case, collapse spaces."""
    name = name.strip()
    name = re.sub(r"\s+", " ", name)
    return name.title()
