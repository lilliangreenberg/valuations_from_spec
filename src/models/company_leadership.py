"""Company leadership model for storing CEO/founder profiles."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, field_validator

if TYPE_CHECKING:
    from datetime import datetime


class LeadershipDiscoveryMethod(StrEnum):
    """How leadership data was discovered."""

    PLAYWRIGHT_SCRAPE = "playwright_scrape"
    KAGI_SEARCH = "kagi_search"


class CompanyLeadership(BaseModel):
    """Represents a leadership profile discovered for a company."""

    model_config = ConfigDict(strict=True)

    id: int | None = None
    company_id: int
    person_name: str
    title: str
    linkedin_profile_url: str
    discovery_method: LeadershipDiscoveryMethod
    confidence: float = 0.0
    is_current: bool = True
    discovered_at: datetime
    last_verified_at: datetime | None = None
    source_company_linkedin_url: str | None = None

    @field_validator("person_name")
    @classmethod
    def validate_person_name(cls, value: str) -> str:
        """Person name must be non-empty and at most 500 characters."""
        if not value or not value.strip():
            msg = "person_name must not be empty"
            raise ValueError(msg)
        if len(value) > 500:
            msg = "person_name must be at most 500 characters"
            raise ValueError(msg)
        return value.strip()

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        """Title must be non-empty and at most 500 characters."""
        if not value or not value.strip():
            msg = "title must not be empty"
            raise ValueError(msg)
        if len(value) > 500:
            msg = "title must be at most 500 characters"
            raise ValueError(msg)
        return value.strip()

    @field_validator("linkedin_profile_url")
    @classmethod
    def validate_linkedin_profile_url(cls, value: str) -> str:
        """LinkedIn profile URL must contain linkedin.com/in/."""
        if "linkedin.com/in/" not in value.lower():
            msg = "linkedin_profile_url must be a LinkedIn personal profile URL"
            raise ValueError(msg)
        return value

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        """Confidence must be between 0.0 and 1.0."""
        if value < 0.0 or value > 1.0:
            msg = "confidence must be between 0.0 and 1.0"
            raise ValueError(msg)
        return value
