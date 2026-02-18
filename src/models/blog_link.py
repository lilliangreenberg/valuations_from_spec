"""Blog link model for discovered company blogs."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from datetime import datetime

    from src.models.social_media_link import DiscoveryMethod


class BlogType(StrEnum):
    """Type of blog platform."""

    COMPANY_BLOG = "company_blog"
    MEDIUM = "medium"
    SUBSTACK = "substack"
    GHOST = "ghost"
    WORDPRESS = "wordpress"
    OTHER = "other"


class BlogLink(BaseModel):
    """Represents a discovered blog URL for a company."""

    model_config = ConfigDict(strict=True)

    id: int | None = None
    company_id: int
    blog_type: BlogType
    blog_url: str
    discovery_method: DiscoveryMethod
    is_active: bool = True
    discovered_at: datetime
    last_verified_at: datetime | None = None
