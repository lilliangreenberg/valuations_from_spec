"""Company model for portfolio company data."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


def _utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(UTC)


class Company(BaseModel):
    """Represents a portfolio company extracted from Airtable."""

    model_config = ConfigDict(strict=True, validate_assignment=True, extra="forbid")

    id: int | None = None
    name: str
    homepage_url: HttpUrl | None = None
    source_sheet: str
    flagged_for_review: bool = False
    flag_reason: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Strip whitespace, collapse spaces, and title-case the company name."""
        stripped = value.strip()
        if not stripped:
            msg = "Name must not be empty"
            raise ValueError(msg)
        if len(stripped) > 500:
            msg = "Name must not exceed 500 characters"
            raise ValueError(msg)
        collapsed = re.sub(r"\s+", " ", stripped)
        return collapsed.title()

    @field_validator("source_sheet")
    @classmethod
    def validate_source_sheet(cls, value: str) -> str:
        """Ensure source_sheet is non-empty."""
        if not value.strip():
            msg = "Source sheet must not be empty"
            raise ValueError(msg)
        return value

    @field_validator("flag_reason")
    @classmethod
    def validate_flag_reason(cls, value: str | None) -> str | None:
        """Validate flag_reason length."""
        if value is not None and len(value) > 1000:
            msg = "Flag reason must not exceed 1000 characters"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_flag_consistency(self) -> Company:
        """Ensure flag_reason is provided when flagged_for_review is True."""
        if self.flagged_for_review and not self.flag_reason:
            msg = "flag_reason is required when flagged_for_review is True"
            raise ValueError(msg)
        return self
