"""Keyword match model for significance analysis results."""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class KeywordMatch(BaseModel):
    """Represents a matched keyword with surrounding context for significance analysis."""

    keyword: str
    category: str
    position: int
    context_before: str
    context_after: str
    is_negated: bool = False
    is_false_positive: bool = False

    @field_validator("position")
    @classmethod
    def validate_position(cls, value: int) -> int:
        """Position must be non-negative."""
        if value < 0:
            msg = "position must be >= 0"
            raise ValueError(msg)
        return value

    @field_validator("context_before")
    @classmethod
    def validate_context_before(cls, value: str) -> str:
        """Context before must not exceed 50 characters."""
        if len(value) > 50:
            msg = "context_before must not exceed 50 characters"
            raise ValueError(msg)
        return value

    @field_validator("context_after")
    @classmethod
    def validate_context_after(cls, value: str) -> str:
        """Context after must not exceed 50 characters."""
        if len(value) > 50:
            msg = "context_after must not exceed 50 characters"
            raise ValueError(msg)
        return value
