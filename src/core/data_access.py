"""Data access pure functions for query building and result mapping."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any


def row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a sqlite3.Row to a dictionary."""
    if row is None:
        return {}
    return dict(row)


def serialize_json_field(
    value: list[Any] | dict[str, Any] | None,
) -> str | None:
    """Serialize a list or dict to JSON string for SQLite storage."""
    if value is None:
        return None
    return json.dumps(value)


def deserialize_json_field(
    value: str | None,
) -> list[Any] | dict[str, Any]:
    """Deserialize a JSON string from SQLite to a Python object."""
    if value is None:
        return []
    try:
        result = json.loads(value)
        if isinstance(result, (list, dict)):
            return result
        return []
    except (json.JSONDecodeError, TypeError):
        return []


def format_datetime(dt: datetime | None) -> str | None:
    """Format datetime to ISO 8601 string for SQLite storage."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO 8601 string from SQLite to datetime."""
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None
