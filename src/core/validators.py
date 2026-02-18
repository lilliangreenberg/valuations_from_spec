"""Core data validation pure functions."""

from __future__ import annotations

import re
from datetime import UTC, datetime


def validate_checksum(checksum: str) -> bool:
    """Validate that a string is a valid MD5 hex digest."""
    return bool(re.match(r"^[0-9a-f]{32}$", checksum))


def validate_confidence(value: float) -> bool:
    """Validate confidence score is between 0.0 and 1.0."""
    return 0.0 <= value <= 1.0


def validate_not_future(dt: datetime) -> bool:
    """Validate that a datetime is not in the future.

    Allows 1 minute tolerance for clock skew.
    """
    now = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    from datetime import timedelta

    return dt <= now + timedelta(seconds=60)


def validate_status_code(code: int) -> bool:
    """Validate HTTP status code range."""
    return 100 <= code <= 599


def validate_airtable_base_id(base_id: str) -> bool:
    """Validate Airtable base ID format."""
    return bool(re.match(r"^app[a-zA-Z0-9]+$", base_id))
