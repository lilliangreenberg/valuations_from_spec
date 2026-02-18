"""News article model for monitored news mentions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator

if TYPE_CHECKING:
    from datetime import datetime

    from src.models.change_record import SignificanceClassification, SignificanceSentiment


class NewsArticle(BaseModel):
    """Represents a news article mentioning a portfolio company."""

    model_config = ConfigDict(strict=True)

    id: int | None = None
    company_id: int
    title: str
    content_url: HttpUrl
    source: str
    published_at: datetime
    discovered_at: datetime
    match_confidence: float
    match_evidence: list[str] = []
    logo_similarity: float | None = None
    company_match_snippet: str | None = None
    keyword_match_snippet: str | None = None
    significance_classification: SignificanceClassification | None = None
    significance_sentiment: SignificanceSentiment | None = None
    significance_confidence: float | None = None
    matched_keywords: list[str] = []
    matched_categories: list[str] = []
    significance_notes: str | None = None

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: int) -> int:
        """Company ID must be positive."""
        if value <= 0:
            msg = "company_id must be greater than 0"
            raise ValueError(msg)
        return value

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        """Title must be non-empty and within length limits."""
        if not value.strip():
            msg = "Title must not be empty"
            raise ValueError(msg)
        if len(value) > 500:
            msg = "Title must not exceed 500 characters"
            raise ValueError(msg)
        return value

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        """Source must be non-empty."""
        if not value.strip():
            msg = "Source must not be empty"
            raise ValueError(msg)
        return value

    @field_validator("match_confidence")
    @classmethod
    def validate_match_confidence(cls, value: float) -> float:
        """Match confidence must be between 0.0 and 1.0."""
        if value < 0.0 or value > 1.0:
            msg = "match_confidence must be between 0.0 and 1.0"
            raise ValueError(msg)
        return value

    @field_validator("logo_similarity")
    @classmethod
    def validate_logo_similarity(cls, value: float | None) -> float | None:
        """Logo similarity must be between 0.0 and 1.0."""
        if value is not None and (value < 0.0 or value > 1.0):
            msg = "logo_similarity must be between 0.0 and 1.0"
            raise ValueError(msg)
        return value

    @field_validator("significance_confidence")
    @classmethod
    def validate_significance_confidence(cls, value: float | None) -> float | None:
        """Significance confidence must be between 0.0 and 1.0."""
        if value is not None and (value < 0.0 or value > 1.0):
            msg = "significance_confidence must be between 0.0 and 1.0"
            raise ValueError(msg)
        return value
