"""Anthropic LLM client for significance classification and company verification.

The LLM acts as the PRIMARY classifier for significance analysis. Keyword matches
from the automated scanner are passed as hints/context, but the LLM makes its own
independent determination without being anchored by the keyword system's conclusion.
"""

from __future__ import annotations

import json
import time
from typing import Any

import anthropic
import structlog

from src.core.llm_prompts import (
    build_baseline_classification_prompt,
    build_company_verification_prompt,
    build_enriched_significance_prompt,
    build_news_classification_prompt,
    build_significance_classification_prompt,
    build_status_aware_enriched_prompt,
    build_status_aware_significance_prompt,
)
from src.utils.retry import retry_with_logging

logger = structlog.get_logger(__name__)

# Anthropic API exception types that should trigger retries
_RETRYABLE_ANTHROPIC_EXCEPTIONS = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.APIStatusError,
)

# Delay between successive API calls to avoid triggering overload (529) responses.
# Applied after each successful call; retry backoff handles spacing between failures.
_INTER_REQUEST_DELAY_SECONDS = 0.2

_FALLBACK_RESULT: dict[str, Any] = {
    "classification": "uncertain",
    "sentiment": "neutral",
    "confidence": 0.5,
    "reasoning": "",
    "validated_keywords": [],
    "false_positives": [],
    "company_status": "uncertain",
    "status_reason": "",
}


class LLMClient:
    """Client for Anthropic LLM API."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    @retry_with_logging(max_attempts=4, max_wait=60)
    def classify_significance(
        self,
        content_excerpt: str,
        keywords: list[str],
        categories: list[str],
        magnitude: str,
        company_name: str,
        homepage_url: str,
        social_context: str = "",
    ) -> dict[str, Any]:
        """Classify significance of a content change using LLM as primary classifier.

        Keywords and categories are passed as hints from the automated scanner,
        not as the answer. The LLM makes an independent determination.
        Company name and URL are provided so the LLM can identify false positives
        where keyword matches are just the company's own name.

        When social_context is non-empty, uses the enriched prompt template that
        includes social media activity data. Otherwise uses the standard template.

        Returns dict with: classification, sentiment, confidence, reasoning,
        validated_keywords, false_positives, error.
        """
        if social_context:
            system_prompt, user_prompt = build_enriched_significance_prompt(
                content_excerpt,
                keywords,
                categories,
                magnitude,
                company_name,
                homepage_url,
                social_context,
            )
        else:
            system_prompt, user_prompt = build_significance_classification_prompt(
                content_excerpt,
                keywords,
                categories,
                magnitude,
                company_name,
                homepage_url,
            )
        return self._call_llm(system_prompt, user_prompt, "classify_significance")

    @retry_with_logging(max_attempts=4, max_wait=60)
    def classify_significance_with_status(
        self,
        content_excerpt: str,
        keywords: list[str],
        categories: list[str],
        magnitude: str,
        company_name: str,
        homepage_url: str,
        social_context: str = "",
        company_notes: str = "",
    ) -> dict[str, Any]:
        """Classify significance and determine company status in a single LLM call.

        Identical signature to classify_significance but uses status-aware prompts
        that also elicit company_status and status_reason in the response.

        When company_notes is provided, it is injected into the prompt as analyst
        context to help the LLM handle unusual or edge-case companies.

        Returns dict with: classification, sentiment, confidence, reasoning,
        validated_keywords, false_positives, company_status, status_reason, error.
        """
        if social_context:
            system_prompt, user_prompt = build_status_aware_enriched_prompt(
                content_excerpt,
                keywords,
                categories,
                magnitude,
                company_name,
                homepage_url,
                social_context,
                company_notes=company_notes,
            )
        else:
            system_prompt, user_prompt = build_status_aware_significance_prompt(
                content_excerpt,
                keywords,
                categories,
                magnitude,
                company_name,
                homepage_url,
                company_notes=company_notes,
            )
        return self._call_llm(
            system_prompt, user_prompt, "classify_significance_with_status"
        )

    @retry_with_logging(max_attempts=4, max_wait=60)
    def classify_baseline(
        self,
        content_excerpt: str,
        keywords: list[str],
        categories: list[str],
        company_name: str,
        homepage_url: str,
    ) -> dict[str, Any]:
        """Classify baseline signals from a company's first website snapshot.

        Analyzes full page content (not a diff) for pre-existing health signals
        like company closure, acquisition, or active operations.
        Company name and URL are provided so the LLM can identify false positives
        where keyword matches are just the company's own name.

        Returns dict with: classification, sentiment, confidence, reasoning,
        validated_keywords, false_positives, error.
        """
        system_prompt, user_prompt = build_baseline_classification_prompt(
            content_excerpt,
            keywords,
            categories,
            company_name,
            homepage_url,
        )
        return self._call_llm(system_prompt, user_prompt, "classify_baseline")

    @retry_with_logging(max_attempts=4, max_wait=60)
    def classify_news_significance(
        self,
        title: str,
        source: str,
        content: str,
        keywords: list[str],
        company_name: str,
    ) -> dict[str, Any]:
        """Classify significance of a news article using LLM as primary classifier.

        Returns dict with: classification, sentiment, confidence, reasoning,
        validated_keywords, false_positives, error.
        """
        system_prompt, user_prompt = build_news_classification_prompt(
            title, source, content, keywords, company_name
        )
        return self._call_llm(system_prompt, user_prompt, "classify_news_significance")

    @retry_with_logging(max_attempts=4, max_wait=60)
    def verify_company_identity(
        self,
        company_name: str,
        company_url: str,
        article_title: str,
        article_source: str,
        article_snippet: str,
        company_description: str = "",
    ) -> tuple[bool, str]:
        """Verify if a news article is about the specified company.

        Returns (is_match, reasoning).
        """
        system_prompt, user_prompt = build_company_verification_prompt(
            company_name,
            company_url,
            article_title,
            article_source,
            article_snippet,
            company_description=company_description,
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
            time.sleep(_INTER_REQUEST_DELAY_SECONDS)
            result = self._parse_json_response(text)
            is_match = result.get("is_match", False)
            reasoning = result.get("reasoning", "No reasoning provided")
            return bool(is_match), str(reasoning)
        except _RETRYABLE_ANTHROPIC_EXCEPTIONS:
            raise
        except Exception as exc:
            logger.warning("llm_company_verification_failed", error=str(exc))
            return False, f"Verification failed: {exc}"

    @retry_with_logging(max_attempts=4, max_wait=60)
    def analyze_screenshot(
        self,
        screenshot_base64: str,
        prompt: str,
    ) -> dict[str, Any]:
        """Analyze a screenshot image using Claude Vision.

        Sends a base64-encoded PNG image to Claude with the given prompt
        and returns the parsed JSON response.

        Args:
            screenshot_base64: Base64-encoded PNG image data.
            prompt: The analysis prompt describing what to extract.

        Returns:
            Parsed JSON dict from the Vision response, or dict with 'error' key.
        """
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                temperature=0.0,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": screenshot_base64,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
            )

            text = response.content[0].text
            time.sleep(_INTER_REQUEST_DELAY_SECONDS)
            return self._parse_json_response(text)
        except _RETRYABLE_ANTHROPIC_EXCEPTIONS:
            raise
        except Exception as exc:
            logger.warning("llm_screenshot_analysis_failed", error=str(exc))
            return {"error": f"Screenshot analysis failed: {exc}"}

    def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        operation: str,
    ) -> dict[str, Any]:
        """Common LLM call pattern for classification methods.

        Returns parsed JSON dict on success, or dict with 'error' key on failure.
        Callers should check for the 'error' key to determine if fallback is needed.
        """
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=800,
                temperature=0.0,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            text = response.content[0].text
            time.sleep(_INTER_REQUEST_DELAY_SECONDS)
            return self._parse_json_response(text)
        except _RETRYABLE_ANTHROPIC_EXCEPTIONS:
            raise  # Let retry handle these
        except Exception as exc:
            logger.warning(f"{operation}_failed", error=str(exc))
            return {
                **_FALLBACK_RESULT,
                "reasoning": f"LLM classification failed: {exc}",
                "error": str(exc),
            }

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
