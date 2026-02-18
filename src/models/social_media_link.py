"""Social media link model for discovered social media profiles."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, field_validator

if TYPE_CHECKING:
    from datetime import datetime


class Platform(StrEnum):
    """Supported social media platforms."""

    LINKEDIN = "linkedin"
    TWITTER = "twitter"
    YOUTUBE = "youtube"
    BLUESKY = "bluesky"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    GITHUB = "github"
    TIKTOK = "tiktok"
    MEDIUM = "medium"
    MASTODON = "mastodon"
    THREADS = "threads"
    PINTEREST = "pinterest"
    BLOG = "blog"


class DiscoveryMethod(StrEnum):
    """How a social media link was discovered."""

    PAGE_FOOTER = "page_footer"
    PAGE_HEADER = "page_header"
    PAGE_CONTENT = "page_content"
    FULL_SITE_CRAWL = "full_site_crawl"


class VerificationStatus(StrEnum):
    """Verification state of a discovered social media link."""

    LOGO_MATCHED = "logo_matched"
    UNVERIFIED = "unverified"
    MANUALLY_REVIEWED = "manually_reviewed"
    FLAGGED = "flagged"


class HTMLRegion(StrEnum):
    """HTML region where the link was found."""

    FOOTER = "footer"
    HEADER = "header"
    NAV = "nav"
    ASIDE = "aside"
    MAIN = "main"
    UNKNOWN = "unknown"


class AccountType(StrEnum):
    """Whether the social media account belongs to a company or individual."""

    COMPANY = "company"
    PERSONAL = "personal"
    UNKNOWN = "unknown"


class RejectionReason(StrEnum):
    """Reason a discovered link was rejected."""

    GENERIC_LINK = "generic_link"
    NOT_SOCIAL_MEDIA = "not_social_media"
    DUPLICATE = "duplicate"
    UNRELATED = "unrelated"
    PERSONAL_ACCOUNT = "personal_account"
    DEAD_LINK = "dead_link"
    PLATFORM_HOMEPAGE = "platform_homepage"


class SocialMediaLink(BaseModel):
    """Represents a discovered social media profile for a company."""

    model_config = ConfigDict(strict=True)

    id: int | None = None
    company_id: int
    platform: Platform
    profile_url: str
    discovery_method: DiscoveryMethod
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    similarity_score: float | None = None
    discovered_at: datetime
    last_verified_at: datetime | None = None
    html_location: HTMLRegion | None = None
    account_type: AccountType | None = None
    account_confidence: float | None = None
    rejection_reason: RejectionReason | None = None

    @field_validator("similarity_score")
    @classmethod
    def validate_similarity_score(cls, value: float | None) -> float | None:
        """Similarity score must be between 0.0 and 1.0."""
        if value is not None and (value < 0.0 or value > 1.0):
            msg = "similarity_score must be between 0.0 and 1.0"
            raise ValueError(msg)
        return value

    @field_validator("account_confidence")
    @classmethod
    def validate_account_confidence(cls, value: float | None) -> float | None:
        """Account confidence must be between 0.0 and 1.0."""
        if value is not None and (value < 0.0 or value > 1.0):
            msg = "account_confidence must be between 0.0 and 1.0"
            raise ValueError(msg)
        return value
