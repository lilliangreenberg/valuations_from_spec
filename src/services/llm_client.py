"""Anthropic LLM client for significance validation and company verification."""

from __future__ import annotations

import json
from typing import Any

import anthropic
import structlog

from src.core.llm_prompts import (
    build_company_verification_prompt,
    build_news_significance_prompt,
    build_significance_validation_prompt,
)
from src.utils.retry import retry_with_logging

logger = structlog.get_logger(__name__)

# Anthropic API exception types that should trigger retries
_RETRYABLE_ANTHROPIC_EXCEPTIONS = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.APIStatusError,
)


class LLMClient:
    """Client for Anthropic LLM API."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20250924",
    ) -> None:
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    @retry_with_logging(max_attempts=2)
    def validate_significance(
        self,
        content_excerpt: str,
        keywords: list[str],
        categories: list[str],
        initial_classification: str,
        magnitude: str,
    ) -> dict[str, Any]:
        """Validate significance classification using LLM.

        Returns dict with: classification, sentiment, confidence, reasoning,
        validated_keywords, false_positives, error.
        """
        system_prompt, user_prompt = build_significance_validation_prompt(
            content_excerpt, keywords, categories, initial_classification, magnitude
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                temperature=0.0,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            text = response.content[0].text
            return self._parse_json_response(text)
        except _RETRYABLE_ANTHROPIC_EXCEPTIONS:
            raise  # Let retry handle these
        except Exception as exc:
            logger.warning("llm_validation_failed", error=str(exc))
            return {
                "classification": "uncertain",
                "sentiment": "neutral",
                "confidence": 0.5,
                "reasoning": f"LLM validation failed: {exc}",
                "validated_keywords": [],
                "false_positives": [],
                "error": str(exc),
            }

    @retry_with_logging(max_attempts=2)
    def validate_news_significance(
        self,
        title: str,
        source: str,
        content: str,
        keywords: list[str],
        company_name: str,
    ) -> dict[str, Any]:
        """Validate news article significance using LLM."""
        system_prompt, user_prompt = build_news_significance_prompt(
            title, source, content, keywords, company_name
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                temperature=0.0,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            text = response.content[0].text
            return self._parse_json_response(text)
        except _RETRYABLE_ANTHROPIC_EXCEPTIONS:
            raise
        except Exception as exc:
            logger.warning("llm_news_validation_failed", error=str(exc))
            return {
                "classification": "uncertain",
                "sentiment": "neutral",
                "confidence": 0.5,
                "reasoning": f"LLM validation failed: {exc}",
                "validated_keywords": [],
                "false_positives": [],
                "error": str(exc),
            }

    @retry_with_logging(max_attempts=2)
    def verify_company_identity(
        self,
        company_name: str,
        company_url: str,
        article_title: str,
        article_source: str,
        article_snippet: str,
    ) -> tuple[bool, str]:
        """Verify if a news article is about the specified company.

        Returns (is_match, reasoning).
        """
        system_prompt, user_prompt = build_company_verification_prompt(
            company_name, company_url, article_title, article_source, article_snippet
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                temperature=0.0,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            text = response.content[0].text
            result = self._parse_json_response(text)
            is_match = result.get("is_match", False)
            reasoning = result.get("reasoning", "No reasoning provided")
            return bool(is_match), str(reasoning)
        except _RETRYABLE_ANTHROPIC_EXCEPTIONS:
            raise
        except Exception as exc:
            logger.warning("llm_company_verification_failed", error=str(exc))
            return False, f"Verification failed: {exc}"

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        """Parse a JSON response from the LLM, handling markdown code blocks."""
        cleaned_text = text.strip()
        if cleaned_text.startswith("```"):
            lines = cleaned_text.split("\n")
            # Remove first and last lines (```json and ```)
            cleaned_text = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned_text

        try:
            parsed: dict[str, Any] = json.loads(cleaned_text)
            return parsed
        except json.JSONDecodeError:
            logger.warning("failed_to_parse_llm_json", text=cleaned_text[:200])
            return {"error": "Failed to parse LLM response"}
