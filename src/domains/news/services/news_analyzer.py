"""News article significance analysis service."""

from __future__ import annotations

from typing import Any

import structlog

from src.domains.monitoring.core.significance_analysis import (
    analyze_content_significance,
)

logger = structlog.get_logger(__name__)


class NewsAnalyzer:
    """Analyzes significance of news articles."""

    def __init__(
        self,
        llm_client: Any | None = None,
        llm_enabled: bool = False,
    ) -> None:
        self.llm_client = llm_client
        self.llm_enabled = llm_enabled

    def analyze(self, title: str, content: str, company_name: str) -> dict[str, Any]:
        """Analyze a news article for significance.

        Returns dict with significance fields.
        """
        combined = f"{title} {content}"
        result = analyze_content_significance(combined)

        if self.llm_enabled and self.llm_client:
            try:
                llm_result = self.llm_client.validate_news_significance(
                    title=title,
                    source="",
                    content=content,
                    keywords=result.matched_keywords,
                    company_name=company_name,
                )
                if not llm_result.get("error"):
                    result.classification = llm_result.get("classification", result.classification)
                    result.sentiment = llm_result.get("sentiment", result.sentiment)
                    result.confidence = llm_result.get("confidence", result.confidence)
            except Exception as exc:
                logger.warning("llm_news_analysis_failed", error=str(exc))

        return {
            "significance_classification": result.classification,
            "significance_sentiment": result.sentiment,
            "significance_confidence": result.confidence,
            "matched_keywords": result.matched_keywords,
            "matched_categories": result.matched_categories,
            "significance_notes": result.notes,
        }
