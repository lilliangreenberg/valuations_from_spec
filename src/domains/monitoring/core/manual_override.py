"""Pure functions for manual status override preparation and validation."""

from __future__ import annotations

import json
from typing import Any

from src.models.company_status import CompanyStatusType, SignalType

VALID_STATUSES = {member.value for member in CompanyStatusType}


def prepare_manual_override(
    company_id: int,
    status: str,
    now_iso: str,
) -> dict[str, Any]:
    """Validate and prepare a manual status override record.

    Args:
        company_id: The company to override.
        status: Must be a valid CompanyStatusType value.
        now_iso: ISO 8601 timestamp for last_checked.

    Returns:
        A dict ready for CompanyStatusRepository.store_status().

    Raises:
        ValueError: If status is not a valid CompanyStatusType.
    """
    if status not in VALID_STATUSES:
        msg = f"Invalid status '{status}'. Must be one of: {sorted(VALID_STATUSES)}"
        raise ValueError(msg)

    indicator = {
        "type": "manual_override",
        "value": "Set by user via dashboard",
        "signal": SignalType.NEUTRAL.value,
    }

    return {
        "company_id": company_id,
        "status": status,
        "confidence": 1.0,
        "indicators": json.dumps([indicator]),
        "last_checked": now_iso,
        "http_last_modified": None,
        "is_manual_override": True,
    }
