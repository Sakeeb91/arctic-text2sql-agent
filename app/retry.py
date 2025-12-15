"""
Retry utilities using tenacity for resilient operations.

This module provides retry decorators and utilities for handling
transient failures in database connections, model inference, and
external service calls.
"""

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.exceptions import (
    DatabaseConnectionException,
    ModelInferenceException,
    QueryExecutionException,
    QueryTimeoutException,
)
from app.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


# =============================================================================
# Retry Decorators
# =============================================================================


def retry_database_operation(
    max_attempts: int | None = None,
    min_wait: float = 1.0,
    max_wait: float = 10.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Retry decorator for database operations.

    Retries on transient database errors with exponential backoff.

    Args:
        max_attempts: Maximum retry attempts (default from settings)
        min_wait: Minimum wait time in seconds
        max_wait: Maximum wait time in seconds

    Returns:
        Decorated function with retry logic
    """
    settings = get_settings()
    attempts = max_attempts or settings.resilience.max_retries

    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(
            (DatabaseConnectionException, QueryTimeoutException)
        ),
        before_sleep=_log_retry_attempt,
        reraise=True,
    )


def retry_model_inference(
    max_attempts: int | None = None,
    min_wait: float = 2.0,
    max_wait: float = 30.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Retry decorator for model inference operations.

    Retries on transient model failures with exponential backoff.
    Uses longer delays than database operations due to resource constraints.

    Args:
        max_attempts: Maximum retry attempts (default from settings)
        min_wait: Minimum wait time in seconds
        max_wait: Maximum wait time in seconds

    Returns:
        Decorated function with retry logic
    """
    settings = get_settings()
    attempts = max_attempts or settings.resilience.max_retries

    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=2, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(ModelInferenceException),
        before_sleep=_log_retry_attempt,
        reraise=True,
    )


def retry_query_execution(
    max_attempts: int | None = None,
    min_wait: float = 0.5,
    max_wait: float = 5.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Retry decorator for query execution.

    Retries on transient query execution failures.

    Args:
        max_attempts: Maximum retry attempts (default from settings)
        min_wait: Minimum wait time in seconds
        max_wait: Maximum wait time in seconds

    Returns:
        Decorated function with retry logic
    """
    settings = get_settings()
    attempts = max_attempts or settings.resilience.max_retries

    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type((QueryExecutionException, QueryTimeoutException)),
        before_sleep=_log_retry_attempt,
        reraise=True,
    )


def _log_retry_attempt(retry_state: Any) -> None:
    """Log retry attempts for monitoring."""
    exception = retry_state.outcome.exception()
    attempt = retry_state.attempt_number

    logger.warning(
        "retry_attempt",
        attempt=attempt,
        exception_type=type(exception).__name__,
        exception_message=str(exception),
        next_wait=retry_state.next_action.sleep if retry_state.next_action else None,
    )


# =============================================================================
# Retry Context Managers
# =============================================================================


class RetryContext:
    """
    Context manager for manual retry control.

    Useful when you need more control over the retry logic than
    decorators provide.

    Usage:
        async with RetryContext(max_attempts=3) as ctx:
            for attempt in ctx:
                try:
                    result = await some_operation()
                    break
                except TransientError as e:
                    ctx.record_failure(e)
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 10.0,
        exceptions: tuple[type[Exception], ...] = (Exception,),
    ) -> None:
        """
        Initialize retry context.

        Args:
            max_attempts: Maximum number of attempts
            base_delay: Base delay for exponential backoff
            max_delay: Maximum delay cap
            exceptions: Tuple of exception types to retry on
        """
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exceptions = exceptions
        self._attempt = 0
        self._last_exception: Exception | None = None

    def __iter__(self) -> "RetryContext":
        """Make context iterable for retry loop."""
        self._attempt = 0
        return self

    def __next__(self) -> int:
        """Get next attempt number."""
        # If we've exhausted attempts, stop iteration
        if self._attempt >= self.max_attempts:
            raise StopIteration

        self._attempt += 1
        return self._attempt

    def record_failure(self, exception: Exception) -> None:
        """Record a failed attempt."""
        self._last_exception = exception

        if not isinstance(exception, self.exceptions):
            raise exception

        if self._attempt >= self.max_attempts:
            raise exception

    def get_delay(self) -> float:
        """Calculate delay for current attempt."""
        delay = self.base_delay * (2 ** (self._attempt - 1))
        return float(min(delay, self.max_delay))

    @property
    def attempt(self) -> int:
        """Current attempt number."""
        return self._attempt

    @property
    def should_retry(self) -> bool:
        """Whether more retries are available."""
        return self._attempt < self.max_attempts


# =============================================================================
# Utility Functions
# =============================================================================


def with_retry(
    func: Callable[..., T],
    max_attempts: int = 3,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    base_delay: float = 1.0,
    max_delay: float = 10.0,
) -> Callable[..., T]:
    """
    Wrap a function with retry logic.

    Alternative to decorators for runtime configuration.

    Args:
        func: Function to wrap
        max_attempts: Maximum retry attempts
        exceptions: Exception types to retry on
        base_delay: Base delay for backoff
        max_delay: Maximum delay cap

    Returns:
        Wrapped function with retry logic
    """

    @wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> T:
        import asyncio

        last_exception: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                result = await func(*args, **kwargs)  # type: ignore[misc]
                return result  # type: ignore[no-any-return]
            except exceptions as e:
                last_exception = e
                if attempt < max_attempts:
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    logger.warning(
                        "retry_attempt",
                        attempt=attempt,
                        max_attempts=max_attempts,
                        delay=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)

        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected retry loop exit")

    @wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> T:
        import time

        last_exception: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                last_exception = e
                if attempt < max_attempts:
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    logger.warning(
                        "retry_attempt",
                        attempt=attempt,
                        max_attempts=max_attempts,
                        delay=delay,
                        error=str(e),
                    )
                    time.sleep(delay)

        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected retry loop exit")

    import asyncio

    if asyncio.iscoroutinefunction(func):
        return async_wrapper  # type: ignore[return-value]
    return sync_wrapper
