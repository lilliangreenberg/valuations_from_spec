"""Contract tests for LLMClient retry, throttle, and fallback behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.services.llm_client import (
    _INTER_REQUEST_DELAY_SECONDS,
    LLMClient,
)


@pytest.fixture
def llm_client() -> LLMClient:
    """Create an LLMClient with a fake API key."""
    return LLMClient(api_key="test-key", model="claude-haiku-4-5-20251001")


def _mock_tool_use_response(tool_input: dict[str, object]) -> MagicMock:
    """Create a mock Anthropic API response with a tool_use content block."""
    block = MagicMock()
    block.type = "tool_use"
    block.input = tool_input
    block.name = "submit_classification"
    block.id = "toolu_test123"

    mock = MagicMock()
    mock.content = [block]
    mock.stop_reason = "tool_use"
    return mock


def _mock_text_response(text: str) -> MagicMock:
    """Create a mock Anthropic API response with text (for screenshot analysis)."""
    block = MagicMock()
    block.type = "text"
    block.text = text

    mock = MagicMock()
    mock.content = [block]
    mock.stop_reason = "end_turn"
    return mock


def _valid_classification_result() -> dict[str, object]:
    """Return a valid classification tool input dict."""
    return {
        "classification": "insignificant",
        "sentiment": "neutral",
        "confidence": 0.9,
        "reasoning": "Routine website update.",
        "validated_keywords": [],
        "false_positives": [],
    }


def _valid_verification_result() -> dict[str, object]:
    """Return a valid verification tool input dict."""
    return {
        "is_match": True,
        "confidence": 0.9,
        "reasoning": "Article describes the same product.",
    }


class TestLLMClientRetryConfig:
    """Verify retry configuration on LLM methods."""

    def test_classify_significance_has_four_max_attempts(self, llm_client: LLMClient) -> None:
        retry_obj = llm_client.classify_significance.retry  # type: ignore[attr-defined]
        assert retry_obj.stop.max_attempt_number == 4

    def test_classify_baseline_has_four_max_attempts(self, llm_client: LLMClient) -> None:
        retry_obj = llm_client.classify_baseline.retry  # type: ignore[attr-defined]
        assert retry_obj.stop.max_attempt_number == 4

    def test_classify_news_has_four_max_attempts(self, llm_client: LLMClient) -> None:
        retry_obj = llm_client.classify_news_significance.retry  # type: ignore[attr-defined]
        assert retry_obj.stop.max_attempt_number == 4

    def test_verify_company_identity_has_four_max_attempts(self, llm_client: LLMClient) -> None:
        retry_obj = llm_client.verify_company_identity.retry  # type: ignore[attr-defined]
        assert retry_obj.stop.max_attempt_number == 4

    def test_max_backoff_is_sixty_seconds(self, llm_client: LLMClient) -> None:
        for method_name in [
            "classify_significance",
            "classify_baseline",
            "classify_news_significance",
            "verify_company_identity",
        ]:
            method = getattr(llm_client, method_name)
            retry_obj = method.retry  # type: ignore[attr-defined]
            assert retry_obj.wait.max == 60, f"{method_name} should have 60s max backoff"


class TestLLMClientThrottle:
    """Verify inter-request delay behavior."""

    def test_inter_request_delay_constant_is_positive(self) -> None:
        assert _INTER_REQUEST_DELAY_SECONDS > 0
        assert _INTER_REQUEST_DELAY_SECONDS <= 1.0

    @patch("src.services.llm_client.time.sleep")
    def test_call_llm_with_tool_sleeps_after_success(
        self, mock_sleep: MagicMock, llm_client: LLMClient
    ) -> None:
        """_call_llm_with_tool should throttle after a successful API response."""
        from src.services.llm_client import _CLASSIFICATION_TOOL

        with patch.object(
            llm_client.client.messages,
            "create",
            return_value=_mock_tool_use_response(_valid_classification_result()),
        ):
            result = llm_client._call_llm_with_tool(
                "sys", "user", _CLASSIFICATION_TOOL, "test_op"
            )

        assert "error" not in result
        mock_sleep.assert_called_once_with(_INTER_REQUEST_DELAY_SECONDS)

    @patch("src.services.llm_client.time.sleep")
    def test_no_sleep_on_non_retryable_failure(
        self, mock_sleep: MagicMock, llm_client: LLMClient
    ) -> None:
        """_call_llm_with_tool should NOT throttle on non-retryable exception."""
        from src.services.llm_client import _CLASSIFICATION_TOOL

        with patch.object(
            llm_client.client.messages,
            "create",
            side_effect=ValueError("bad input"),
        ):
            result = llm_client._call_llm_with_tool(
                "sys", "user", _CLASSIFICATION_TOOL, "test_op"
            )

        assert "error" in result
        mock_sleep.assert_not_called()

    @patch("src.services.llm_client.time.sleep")
    def test_verify_company_identity_sleeps_on_success(
        self, mock_sleep: MagicMock, llm_client: LLMClient
    ) -> None:
        with patch.object(
            llm_client.client.messages,
            "create",
            return_value=_mock_tool_use_response(_valid_verification_result()),
        ):
            is_match, reasoning = llm_client.verify_company_identity(
                company_name="Test Co",
                company_url="https://test.co",
                article_title="Test Article",
                article_source="test.com",
                article_snippet="snippet",
            )

        assert is_match is True
        mock_sleep.assert_called_with(_INTER_REQUEST_DELAY_SECONDS)


class TestLLMClientFallback:
    """Verify graceful fallback when API calls fail."""

    def test_call_llm_with_tool_returns_error_on_exception(
        self, llm_client: LLMClient
    ) -> None:
        from src.services.llm_client import _CLASSIFICATION_TOOL

        with patch.object(
            llm_client.client.messages,
            "create",
            side_effect=ValueError("unexpected"),
        ):
            result = llm_client._call_llm_with_tool(
                "sys", "user", _CLASSIFICATION_TOOL, "test_op"
            )

        assert "error" in result
        assert result["classification"] == "uncertain"
        assert result["confidence"] == 0.5

    def test_call_llm_with_tool_success_returns_tool_input(
        self, llm_client: LLMClient
    ) -> None:
        from src.services.llm_client import _CLASSIFICATION_TOOL

        with patch.object(
            llm_client.client.messages,
            "create",
            return_value=_mock_tool_use_response(_valid_classification_result()),
        ):
            result = llm_client._call_llm_with_tool(
                "sys", "user", _CLASSIFICATION_TOOL, "test_op"
            )

        assert "error" not in result
        assert result["classification"] == "insignificant"
        assert result["confidence"] == 0.9

    def test_verify_company_identity_returns_false_on_failure(
        self, llm_client: LLMClient
    ) -> None:
        with patch.object(
            llm_client.client.messages,
            "create",
            side_effect=ValueError("unexpected"),
        ):
            is_match, reasoning = llm_client.verify_company_identity(
                company_name="Test Co",
                company_url="https://test.co",
                article_title="Test Article",
                article_source="test.com",
                article_snippet="snippet",
            )

        assert is_match is False
        assert "failed" in reasoning.lower()

    def test_screenshot_analysis_still_uses_text_parsing(
        self, llm_client: LLMClient
    ) -> None:
        """analyze_screenshot should still use text-based JSON parsing."""
        json_text = '{"company_name": "Test", "industry": "Tech"}'
        with patch.object(
            llm_client.client.messages,
            "create",
            return_value=_mock_text_response(json_text),
        ):
            result = llm_client.analyze_screenshot("base64data", "analyze this")

        assert result["company_name"] == "Test"
