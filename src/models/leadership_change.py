"""Leadership change event model for append-only event log."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic needs at runtime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator


class LeadershipChangeSeverity(StrEnum):
    """Severity classification for leadership change events."""

    CRITICAL = "critical"
    NOTABLE = "notable"
    MINOR = "minor"


class LeadershipChange(BaseModel):
    """An append-only event record for a leadership transition.

    Written whenever compare_leadership() detects a departure, arrival, or
    other change between the previous and current rosters. Gives the system
    a queryable history of leadership transitions that the StatusAnalyzer
    and dashboard can use.
    """

    # Not strict: we accept severity as a string literal and coerce to the
    # enum, matching how changes flow through the system (dicts from the
    # core change_detection module have string severities).
    model_config = ConfigDict(strict=False, use_enum_values=True)

    id: int | None = None
    company_id: int
    change_type: str
    person_name: str
    title: str | None = None
    linkedin_profile_url: str | None = None
    severity: LeadershipChangeSeverity
    detected_at: datetime
    confidence: float = 0.0
    discovery_method: str | None = None
    context: str | None = None

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: int) -> int:
        if value <= 0:
            msg = "company_id must be greater than 0"
            raise ValueError(msg)
        return value

    @field_validator("change_type")
    @classmethod
    def validate_change_type(cls, value: str) -> str:
        if not value or not value.strip():
            msg = "change_type must not be empty"
            raise ValueError(msg)
        return value.strip()

    @field_validator("person_name")
    @classmethod
    def validate_person_name(cls, value: str) -> str:
        if not value or not value.strip():
            msg = "person_name must not be empty"
            raise ValueError(msg)
        if len(value) > 500:
            msg = "person_name must be at most 500 characters"
            raise ValueError(msg)
        return value.strip()

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if value < 0.0 or value > 1.0:
            msg = "confidence must be between 0.0 and 1.0"
            raise ValueError(msg)
        return value
