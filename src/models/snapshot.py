"""Snapshot model for website content captures."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


def _utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(UTC)


class Snapshot(BaseModel):
    """Represents a captured website snapshot from Firecrawl."""

    model_config = ConfigDict(strict=True)

    id: int | None = None
    company_id: int
    url: HttpUrl
    content_markdown: str | None = None
    content_html: str | None = None
    status_code: int | None = None
    captured_at: datetime = Field(default_factory=_utc_now)
    has_paywall: bool = False
    has_auth_required: bool = False
    error_message: str | None = None
    content_checksum: str | None = None
    http_last_modified: datetime | None = None
    capture_metadata: str | None = None

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: int) -> int:
        """Company ID must be positive."""
        if value <= 0:
            msg = "company_id must be greater than 0"
            raise ValueError(msg)
        return value

    @field_validator("content_markdown")
    @classmethod
    def validate_content_markdown(cls, value: str | None) -> str | None:
        """Content markdown must not exceed 10MB."""
        if value is not None and len(value) > 10_000_000:
            msg = "content_markdown must not exceed 10,000,000 characters"
            raise ValueError(msg)
        return value

    @field_validator("content_html")
    @classmethod
    def validate_content_html(cls, value: str | None) -> str | None:
        """Content HTML must not exceed 10MB."""
        if value is not None and len(value) > 10_000_000:
            msg = "content_html must not exceed 10,000,000 characters"
            raise ValueError(msg)
        return value

    @field_validator("status_code")
    @classmethod
    def validate_status_code(cls, value: int | None) -> int | None:
        """Status code must be between 100 and 599."""
        if value is not None and (value < 100 or value > 599):
            msg = "status_code must be between 100 and 599"
            raise ValueError(msg)
        return value

    @field_validator("error_message")
    @classmethod
    def validate_error_message(cls, value: str | None) -> str | None:
        """Error message must not exceed 2000 characters."""
        if value is not None and len(value) > 2000:
            msg = "error_message must not exceed 2000 characters"
            raise ValueError(msg)
        return value

    @field_validator("content_checksum")
    @classmethod
    def validate_content_checksum(cls, value: str | None) -> str | None:
        """Content checksum must be a valid 32-character lowercase hex MD5 string."""
        if value is not None:
            lowered = value.lower()
            if not re.fullmatch(r"[0-9a-f]{32}", lowered):
                msg = "content_checksum must be a valid 32-character hex MD5 string"
                raise ValueError(msg)
            return lowered
        return value

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at(cls, value: datetime) -> datetime:
        """Captured timestamp must not be in the future."""
        now = datetime.now(UTC)
        if value > now:
            msg = "captured_at must not be in the future"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_content_or_error(self) -> Snapshot:
        """At least one of content_markdown, content_html, or error_message is required."""
        if (
            self.content_markdown is None
            and self.content_html is None
            and self.error_message is None
        ):
            msg = (
                "At least one of content_markdown, content_html, or error_message must be provided"
            )
            raise ValueError(msg)
        return self
