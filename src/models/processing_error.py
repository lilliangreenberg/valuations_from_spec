"""Processing error model for tracking operation failures."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, field_validator

if TYPE_CHECKING:
    from datetime import datetime


class ProcessingError(BaseModel):
    """Tracks a failed operation for debugging and retry purposes."""

    model_config = ConfigDict(strict=True)

    entity_type: Literal["company", "snapshot"]
    entity_id: int | None = None
    error_type: str
    error_message: str
    retry_count: int = 0
    occurred_at: datetime

    @field_validator("error_type")
    @classmethod
    def validate_error_type(cls, value: str) -> str:
        """Error type must be PascalCase and between 1-100 characters."""
        if not value or len(value) > 100:
            msg = "error_type must be between 1 and 100 characters"
            raise ValueError(msg)
        if not re.fullmatch(r"[A-Z][a-zA-Z0-9]*", value):
            msg = "error_type must be in PascalCase format"
            raise ValueError(msg)
        return value

    @field_validator("error_message")
    @classmethod
    def validate_error_message(cls, value: str) -> str:
        """Error message must be between 1 and 5000 characters."""
        if not value or len(value) > 5000:
            msg = "error_message must be between 1 and 5000 characters"
            raise ValueError(msg)
        return value

    @field_validator("retry_count")
    @classmethod
    def validate_retry_count(cls, value: int) -> int:
        """Retry count must be between 0 and 2."""
        if value < 0 or value > 2:
            msg = "retry_count must be between 0 and 2"
            raise ValueError(msg)
        return value
