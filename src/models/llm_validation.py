"""LLM validation result model for significance analysis."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, field_validator

if TYPE_CHECKING:
    from src.models.change_record import SignificanceClassification, SignificanceSentiment


class LLMValidationResult(BaseModel):
    """Result from LLM-based significance validation."""

    classification: SignificanceClassification
    sentiment: SignificanceSentiment
    confidence: float
    reasoning: str
    validated_keywords: list[str] = []
    false_positives: list[str] = []
    error: str | None = None

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        """Confidence must be between 0.0 and 1.0."""
        if value < 0.0 or value > 1.0:
            msg = "confidence must be between 0.0 and 1.0"
            raise ValueError(msg)
        return value
