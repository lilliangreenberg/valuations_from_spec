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


def _mock_response(text: str) -> MagicMock:
    """Create a mock Anthropic API response with given text."""
    mock = MagicMock()
    mock.content = [MagicMock(text=text)]
    return mock


def _valid_json_response() -> str:
    """Return a valid JSON classification response."""
    return (
        '{"classification": "insignificant", "sentiment": "neutral",'
        ' "confidence": 0.85, "reasoning": "test"}'
    )


class TestLLMClientRetryConfig:
    """Verify retry configuration on LLM methods."""

    def test_classify_significance_has_four_max_attempts(self, llm_client: LLMClient) -> None:
        """classify_significance should retry up to 4 attempts."""
        retry_obj = llm_client.classify_significance.retry  # type: ignore[attr-defined]
        # stop_after_attempt stores the max as stop.max_attempt_number
        assert retry_obj.stop.max_attempt_number == 4

    def test_classify_baseline_has_four_max_attempts(self, llm_client: LLMClient) -> None:
        """classify_baseline should retry up to 4 attempts."""
        retry_obj = llm_client.classify_baseline.retry  # type: ignore[attr-defined]
        assert retry_obj.stop.max_attempt_number == 4

    def test_classify_news_has_four_max_attempts(self, llm_client: LLMClient) -> None:
        """classify_news_significance should retry up to 4 attempts."""
        retry_obj = llm_client.classify_news_significance.retry  # type: ignore[attr-defined]
        assert retry_obj.stop.max_attempt_number == 4

    def test_verify_company_identity_has_four_max_attempts(self, llm_client: LLMClient) -> None:
        """verify_company_identity should retry up to 4 attempts."""
        retry_obj = llm_client.verify_company_identity.retry  # type: ignore[attr-defined]
        assert retry_obj.stop.max_attempt_number == 4

    def test_max_backoff_is_sixty_seconds(self, llm_client: LLMClient) -> None:
        """All LLM methods should use 60s max backoff for 529 resilience."""
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
        """The throttle delay should be a positive value."""
        assert _INTER_REQUEST_DELAY_SECONDS > 0
        assert _INTER_REQUEST_DELAY_SECONDS <= 1.0  # sanity: not too slow

    @patch("src.services.llm_client.time.sleep")
    def test_call_llm_sleeps_after_successful_response(
        self, mock_sleep: MagicMock, llm_client: LLMClient
    ) -> None:
        """_call_llm should throttle after a successful API response."""
        with patch.object(
            llm_client.client.messages,
            "create",
            return_value=_mock_response(_valid_json_response()),
        ):
            result = llm_client._call_llm("sys", "user", "test_op")

        assert "error" not in result
        mock_sleep.assert_called_once_with(_INTER_REQUEST_DELAY_SECONDS)

    @patch("src.services.llm_client.time.sleep")
    def test_no_sleep_on_non_retryable_failure(
        self, mock_sleep: MagicMock, llm_client: LLMClient
    ) -> None:
        """_call_llm should NOT throttle when a non-retryable exception occurs."""
        with patch.object(
            llm_client.client.messages,
            "create",
            side_effect=ValueError("bad input"),
        ):
            result = llm_client._call_llm("sys", "user", "test_op")

        assert "error" in result
        mock_sleep.assert_not_called()

    @patch("src.services.llm_client.time.sleep")
    def test_verify_company_identity_sleeps_on_success(
        self, mock_sleep: MagicMock, llm_client: LLMClient
    ) -> None:
        """verify_company_identity should throttle after success."""
        response_text = '{"is_match": true, "reasoning": "test match"}'
        with patch.object(
            llm_client.client.messages,
            "create",
            return_value=_mock_response(response_text),
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

    def test_call_llm_returns_error_dict_on_non_retryable_exception(
        self, llm_client: LLMClient
    ) -> None:
        """Non-retryable exceptions should return a dict with 'error' key."""
        with patch.object(
            llm_client.client.messages,
            "create",
            side_effect=ValueError("unexpected"),
        ):
            result = llm_client._call_llm("sys", "user", "test_op")

        assert "error" in result
        assert result["classification"] == "uncertain"
        assert result["confidence"] == 0.5

    def test_call_llm_returns_error_on_json_parse_failure(self, llm_client: LLMClient) -> None:
        """Unparseable LLM response should return error dict."""
        with patch.object(
            llm_client.client.messages,
            "create",
            return_value=_mock_response("not valid json at all"),
        ):
            result = llm_client._call_llm("sys", "user", "test_op")

        assert "error" in result

    def test_call_llm_success_returns_parsed_json(self, llm_client: LLMClient) -> None:
        """Successful API call should return parsed JSON dict without error."""
        with patch.object(
            llm_client.client.messages,
            "create",
            return_value=_mock_response(_valid_json_response()),
        ):
            result = llm_client._call_llm("sys", "user", "test_op")

        assert "error" not in result
        assert result["classification"] == "insignificant"
        assert result["confidence"] == 0.85

    def test_verify_company_identity_returns_false_on_failure(self, llm_client: LLMClient) -> None:
        """verify_company_identity returns (False, reason) on non-retryable error."""
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
        assert "Verification failed" in reasoning
