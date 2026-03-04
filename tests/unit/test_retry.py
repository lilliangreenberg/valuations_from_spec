"""Unit tests for retry_with_logging decorator."""

from __future__ import annotations

import anthropic
import pytest
from tenacity import wait_exponential

from src.utils.retry import retry_with_logging


class TestRetryWithLogging:
    """Tests for retry_with_logging decorator configuration."""

    def test_default_max_attempts_is_three(self) -> None:
        """Default max_attempts should be 3."""
        call_count = 0

        @retry_with_logging()
        def always_fails() -> None:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            always_fails()

        assert call_count == 3

    def test_custom_max_attempts(self) -> None:
        """max_attempts parameter controls total attempt count."""
        call_count = 0

        @retry_with_logging(max_attempts=4)
        def always_fails() -> None:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            always_fails()

        assert call_count == 4

    def test_default_max_wait_is_ten(self) -> None:
        """Default max_wait should be 10 seconds."""

        @retry_with_logging()
        def dummy() -> None:
            pass

        # Access the tenacity retry object's wait strategy
        retry_obj = dummy.retry  # type: ignore[attr-defined]
        wait = retry_obj.wait
        assert isinstance(wait, wait_exponential)
        assert wait.max == 10

    def test_custom_max_wait(self) -> None:
        """max_wait parameter configures the exponential backoff ceiling."""

        @retry_with_logging(max_wait=60)
        def dummy() -> None:
            pass

        retry_obj = dummy.retry  # type: ignore[attr-defined]
        wait = retry_obj.wait
        assert isinstance(wait, wait_exponential)
        assert wait.max == 60

    def test_retries_on_connection_error(self) -> None:
        """Should retry on ConnectionError."""
        call_count = 0

        @retry_with_logging(max_attempts=2)
        def fails_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("transient")
            return "ok"

        assert fails_once() == "ok"
        assert call_count == 2

    def test_retries_on_timeout_error(self) -> None:
        """Should retry on TimeoutError."""
        call_count = 0

        @retry_with_logging(max_attempts=2)
        def fails_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("transient")
            return "ok"

        assert fails_once() == "ok"
        assert call_count == 2

    def test_retries_on_os_error(self) -> None:
        """Should retry on OSError."""
        call_count = 0

        @retry_with_logging(max_attempts=2)
        def fails_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("transient")
            return "ok"

        assert fails_once() == "ok"
        assert call_count == 2

    def test_retries_on_anthropic_api_status_error(self) -> None:
        """Should retry on Anthropic APIStatusError (covers 429, 529, 5xx)."""
        call_count = 0

        @retry_with_logging(max_attempts=2)
        def fails_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise anthropic.APIStatusError(
                    message="overloaded",
                    response=_fake_response(529),
                    body=None,
                )
            return "ok"

        assert fails_once() == "ok"
        assert call_count == 2

    def test_no_retry_on_value_error(self) -> None:
        """Should NOT retry on ValueError (not in retryable list)."""

        @retry_with_logging(max_attempts=3)
        def fails() -> None:
            raise ValueError("not retryable")

        with pytest.raises(ValueError, match="not retryable"):
            fails()

    def test_no_retry_on_key_error(self) -> None:
        """Should NOT retry on KeyError."""

        @retry_with_logging(max_attempts=3)
        def fails() -> None:
            raise KeyError("not retryable")

        with pytest.raises(KeyError):
            fails()

    def test_successful_call_no_retry(self) -> None:
        """Successful calls should not trigger any retry."""
        call_count = 0

        @retry_with_logging(max_attempts=3)
        def succeeds() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        assert succeeds() == "ok"
        assert call_count == 1

    def test_max_wait_sixty_for_llm_pattern(self) -> None:
        """LLM client pattern: 4 attempts with 60s max backoff."""

        @retry_with_logging(max_attempts=4, max_wait=60)
        def dummy() -> None:
            pass

        retry_obj = dummy.retry  # type: ignore[attr-defined]
        wait = retry_obj.wait
        assert isinstance(wait, wait_exponential)
        assert wait.max == 60

        # Verify it would attempt 4 times
        call_count = 0

        @retry_with_logging(max_attempts=4, max_wait=60)
        def always_fails() -> None:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            always_fails()

        assert call_count == 4


class _FakeResponse:
    """Minimal fake httpx.Response for APIStatusError construction."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self.request = _FakeRequest()

    def json(self) -> dict[str, str]:
        return {"error": "test"}

    @property
    def text(self) -> str:
        return '{"error": "test"}'


class _FakeRequest:
    """Minimal fake httpx.Request for APIStatusError construction."""

    def __init__(self) -> None:
        self.method = "POST"
        self.url = "https://api.anthropic.com/v1/messages"
        self.headers: dict[str, str] = {}


def _fake_response(status_code: int) -> _FakeResponse:
    return _FakeResponse(status_code)
