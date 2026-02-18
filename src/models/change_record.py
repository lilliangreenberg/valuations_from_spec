"""Change record model for website content change detection."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, field_validator

if TYPE_CHECKING:
    from datetime import datetime


class ChangeMagnitude(StrEnum):
    """Magnitude of content change between snapshots."""

    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"


class SignificanceClassification(StrEnum):
    """Business significance classification of a change or news article."""

    SIGNIFICANT = "significant"
    INSIGNIFICANT = "insignificant"
    UNCERTAIN = "uncertain"


class SignificanceSentiment(StrEnum):
    """Sentiment of a significant change or news article."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class ChangeRecord(BaseModel):
    """Represents a detected change between two website snapshots."""

    model_config = ConfigDict(strict=True)

    id: int | None = None
    company_id: int
    snapshot_id_old: int
    snapshot_id_new: int
    checksum_old: str
    checksum_new: str
    has_changed: bool
    change_magnitude: ChangeMagnitude
    detected_at: datetime
    significance_classification: SignificanceClassification | None = None
    significance_sentiment: SignificanceSentiment | None = None
    significance_confidence: float | None = None
    matched_keywords: list[str] = []
    matched_categories: list[str] = []
    significance_notes: str | None = None
    evidence_snippets: list[str] = []

    @field_validator("checksum_old", "checksum_new")
    @classmethod
    def validate_checksum(cls, value: str) -> str:
        """Checksums must be valid 32-character lowercase hex MD5 strings."""
        lowered = value.lower()
        if not re.fullmatch(r"[0-9a-f]{32}", lowered):
            msg = "Checksum must be a valid 32-character hex MD5 string"
            raise ValueError(msg)
        return lowered

    @field_validator("significance_confidence")
    @classmethod
    def validate_significance_confidence(cls, value: float | None) -> float | None:
        """Significance confidence must be between 0.0 and 1.0."""
        if value is not None and (value < 0.0 or value > 1.0):
            msg = "significance_confidence must be between 0.0 and 1.0"
            raise ValueError(msg)
        return value
