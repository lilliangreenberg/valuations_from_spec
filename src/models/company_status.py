"""Company status model for operational status tracking."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, field_validator

if TYPE_CHECKING:
    from datetime import datetime


class CompanyStatusType(StrEnum):
    """Operational status of a portfolio company."""

    OPERATIONAL = "operational"
    LIKELY_CLOSED = "likely_closed"
    UNCERTAIN = "uncertain"


class SignalType(StrEnum):
    """Signal direction of a status indicator."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class StatusIndicator(BaseModel):
    """Individual indicator used to determine company status."""

    type: str
    value: str
    signal: SignalType


class CompanyStatus(BaseModel):
    """Represents the operational status assessment of a company."""

    model_config = ConfigDict(strict=True)

    id: int | None = None
    company_id: int
    status: CompanyStatusType
    confidence: float
    indicators: list[StatusIndicator]
    last_checked: datetime
    http_last_modified: datetime | None = None

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        """Confidence must be between 0.0 and 1.0."""
        if value < 0.0 or value > 1.0:
            msg = "confidence must be between 0.0 and 1.0"
            raise ValueError(msg)
        return value
