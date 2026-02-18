"""Discovery result model for social media discovery operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from src.models.blog_link import BlogLink
    from src.models.company_logo import CompanyLogo
    from src.models.social_media_link import SocialMediaLink


def _utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(UTC)


class DiscoveryResult(BaseModel):
    """Transient result of a social media discovery operation (not persisted directly)."""

    company_id: int
    company_name: str
    homepage_url: str
    discovered_links: list[SocialMediaLink] = []
    discovered_blogs: list[BlogLink] = []
    extracted_logo: CompanyLogo | None = None
    logo_extraction_attempted: bool = False
    logo_extraction_failed: bool = False
    flagged_for_review: bool = False
    flag_reason: str | None = None
    error_message: str | None = None
    processing_time_seconds: float | None = None
    processed_at: datetime = Field(default_factory=_utc_now)
