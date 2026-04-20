"""Anthropic LLM client for significance classification and company verification.

Uses tool use (structured outputs) for classification methods to guarantee
consistent response format. Keyword matches from the automated scanner are
passed as hints -- the LLM makes its own independent determination.
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

# --- Tool Schemas for Structured Outputs ---

_CONFIDENCE_ENUM = [0.5, 0.7, 0.8, 0.9, 0.95]

_CLASSIFICATION_TOOL: dict[str, Any] = {
    "name": "submit_classification",
    "description": "Submit significance classification result.",
    "input_schema": {
        "type": "object",
        "required": [
            "classification",
            "sentiment",
            "confidence",
            "reasoning",
            "validated_keywords",
            "false_positives",
        ],
        "properties": {
            "classification": {
                "type": "string",
                "enum": ["significant", "insignificant", "uncertain"],
            },
            "sentiment": {
                "type": "string",
                "enum": ["positive", "negative", "neutral", "mixed"],
            },
            "confidence": {
                "type": "number",
                "enum": _CONFIDENCE_ENUM,
                "description": (
                    "0.5=coin flip, 0.7=probable, 0.8=confident, 0.9=very confident, 0.95=certain"
                ),
            },
            "reasoning": {
                "type": "string",
                "maxLength": 200,
                "description": "1-2 sentences: what specific evidence drove your decision.",
            },
            "validated_keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keywords from hints confirmed as relevant signals.",
            },
            "false_positives": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keywords from hints that are false positives.",
            },
        },
    },
}

_STATUS_CLASSIFICATION_TOOL: dict[str, Any] = {
    "name": "submit_status_classification",
    "description": "Submit significance classification and company status.",
    "input_schema": {
        "type": "object",
        "required": [
            "classification",
            "sentiment",
            "confidence",
            "reasoning",
            "validated_keywords",
            "false_positives",
            "company_status",
            "status_reason",
        ],
        "properties": {
            **_CLASSIFICATION_TOOL["input_schema"]["properties"],
            "company_status": {
                "type": "string",
                "enum": ["operational", "likely_closed", "uncertain"],
            },
            "status_reason": {
                "type": "string",
                "maxLength": 200,
                "description": (
                    "Exactly one sentence explaining status determination."
                    " Specific and factual. Shown directly to users."
                ),
            },
        },
    },
}

_VERIFICATION_TOOL: dict[str, Any] = {
    "name": "submit_verification",
    "description": "Submit company identity verification result.",
    "input_schema": {
        "type": "object",
        "required": ["is_match", "confidence", "reasoning"],
        "properties": {
            "is_match": {
                "type": "boolean",
                "description": "Whether the article is about this specific company.",
            },
            "confidence": {
                "type": "number",
                "enum": _CONFIDENCE_ENUM,
            },
            "reasoning": {
                "type": "string",
                "maxLength": 200,
            },
        },
    },
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
        """Classify significance of a content change using LLM.

        When social_context is non-empty, uses enriched prompt with social data.
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
        return self._call_llm_with_tool(
            system_prompt, user_prompt, _CLASSIFICATION_TOOL, "classify_significance"
        )

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
        """Classify significance and determine company status in a single call."""
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
        return self._call_llm_with_tool(
            system_prompt,
            user_prompt,
            _STATUS_CLASSIFICATION_TOOL,
            "classify_significance_with_status",
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
        """Classify baseline signals from a company's first website snapshot."""
        system_prompt, user_prompt = build_baseline_classification_prompt(
            content_excerpt,
            keywords,
            categories,
            company_name,
            homepage_url,
        )
        return self._call_llm_with_tool(
            system_prompt, user_prompt, _CLASSIFICATION_TOOL, "classify_baseline"
        )

    @retry_with_logging(max_attempts=4, max_wait=60)
    def classify_news_significance(
        self,
        title: str,
        source: str,
        content: str,
        keywords: list[str],
        company_name: str,
    ) -> dict[str, Any]:
        """Classify significance of a news article."""
        system_prompt, user_prompt = build_news_classification_prompt(
            title,
            source,
            content,
            keywords,
            company_name,
        )
        return self._call_llm_with_tool(
            system_prompt,
            user_prompt,
            _CLASSIFICATION_TOOL,
            "classify_news_significance",
        )

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
            result = self._call_llm_with_tool(
                system_prompt,
                user_prompt,
                _VERIFICATION_TOOL,
                "verify_company_identity",
            )
            is_match = result.get("is_match", False)
            reasoning = result.get("reasoning", "No reasoning provided")
            return bool(is_match), str(reasoning)
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

        Uses text-based responses (no tool use) since vision prompts have
        varying output schemas.
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

    def _call_llm_with_tool(
        self,
        system_prompt: str,
        user_prompt: str,
        tool: dict[str, Any],
        operation: str,
    ) -> dict[str, Any]:
        """Call LLM with forced tool use for structured output.

        The tool schema guarantees response format at the API level --
        no JSON parsing needed.

        Returns the tool input dict on success, or fallback dict on failure.
        """
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=800,
                temperature=0.0,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
            )

            time.sleep(_INTER_REQUEST_DELAY_SECONDS)

            # With forced tool_choice, the response contains a tool_use block
            for block in response.content:
                if block.type == "tool_use":
                    result: dict[str, Any] = block.input  # type: ignore[assignment]
                    return result

            # Should not happen with forced tool_choice, but handle gracefully
            logger.warning(f"{operation}_no_tool_use_block")
            return {**_FALLBACK_RESULT, "reasoning": "No tool use block in response"}
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
        """Parse a JSON response from the LLM, handling markdown code blocks.

        Used only by analyze_screenshot which uses text-based responses.
        """
        cleaned_text = text.strip()
        if cleaned_text.startswith("```"):
            lines = cleaned_text.split("\n")
            cleaned_text = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned_text

        try:
            parsed: dict[str, Any] = json.loads(cleaned_text)
            return parsed
        except json.JSONDecodeError:
            logger.warning("failed_to_parse_llm_json", text=cleaned_text[:200])
            return {"error": "Failed to parse LLM response"}
