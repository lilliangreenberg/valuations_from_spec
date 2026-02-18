"""Retry logic with structured logging using tenacity."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, ParamSpec, TypeVar

import anthropic
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

P = ParamSpec("P")
T = TypeVar("T")

logger = get_logger(__name__)

# Exception types that trigger retries:
# - Standard Python network errors (ConnectionError, TimeoutError, OSError)
#   covers requests library (inherits from OSError) and general I/O
# - Anthropic API transient errors (connection, timeout, 429/5xx status)
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.APIStatusError,
)


def _log_retry(retry_state: RetryCallState) -> None:
    """Log retry attempt with structured context."""
    logger.warning(
        "retrying_operation",
        attempt=retry_state.attempt_number,
        function=getattr(retry_state.fn, "__name__", "unknown"),
        error=str(retry_state.outcome.exception()) if retry_state.outcome else "unknown",
    )


def retry_with_logging(max_attempts: int = 3) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator using tenacity with structured logging.

    Retries on: ConnectionError, TimeoutError, OSError, and
    Anthropic API errors (APIConnectionError, APITimeoutError, APIStatusError).
    Uses exponential backoff starting at 2s, capped at 10s.
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
            before_sleep=_log_retry,
            reraise=True,
        )
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
