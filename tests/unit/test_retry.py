"""
Unit tests for retry utilities.
"""

import pytest

from app.exceptions import (
    DatabaseConnectionException,
    ModelInferenceException,
    QueryExecutionException,
    QueryTimeoutException,
)
from app.retry import (
    RetryContext,
    retry_database_operation,
    retry_model_inference,
    retry_query_execution,
    with_retry,
)

# =============================================================================
# Retry Decorator Tests
# =============================================================================


class TestRetryDatabaseOperation:
    """Tests for retry_database_operation decorator."""

    @pytest.mark.asyncio
    async def test_success_without_retry(self) -> None:
        """Test successful call without needing retry."""
        call_count = 0

        @retry_database_operation(max_attempts=3)
        async def successful_operation() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        result = await successful_operation()
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_connection_exception(self) -> None:
        """Test retry on DatabaseConnectionException."""
        call_count = 0

        @retry_database_operation(max_attempts=3, min_wait=0.01, max_wait=0.02)
        async def flaky_operation() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise DatabaseConnectionException("Connection lost")
            return "success"

        result = await flaky_operation()
        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_timeout_exception(self) -> None:
        """Test retry on QueryTimeoutException."""
        call_count = 0

        @retry_database_operation(max_attempts=3, min_wait=0.01, max_wait=0.02)
        async def timeout_operation() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise QueryTimeoutException(timeout_seconds=30)
            return "success"

        result = await timeout_operation()
        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_does_not_retry_on_other_exceptions(self) -> None:
        """Test that other exceptions are not retried."""
        call_count = 0

        @retry_database_operation(max_attempts=3)
        async def failing_operation() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("Not a database error")

        with pytest.raises(ValueError):
            await failing_operation()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_exhausts_all_attempts(self) -> None:
        """Test that all attempts are used before raising."""
        call_count = 0

        @retry_database_operation(max_attempts=3, min_wait=0.01, max_wait=0.02)
        async def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise DatabaseConnectionException("Persistent failure")

        with pytest.raises(DatabaseConnectionException):
            await always_fails()
        assert call_count == 3


class TestRetryModelInference:
    """Tests for retry_model_inference decorator."""

    @pytest.mark.asyncio
    async def test_retries_on_inference_exception(self) -> None:
        """Test retry on ModelInferenceException."""
        call_count = 0

        @retry_model_inference(max_attempts=3, min_wait=0.01, max_wait=0.02)
        async def flaky_inference() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ModelInferenceException("GPU OOM")
            return "result"

        result = await flaky_inference()
        assert result == "result"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_does_not_retry_database_exceptions(self) -> None:
        """Test that database exceptions are not retried by model retry."""
        call_count = 0

        @retry_model_inference(max_attempts=3)
        async def wrong_exception() -> str:
            nonlocal call_count
            call_count += 1
            raise DatabaseConnectionException("Wrong type")

        with pytest.raises(DatabaseConnectionException):
            await wrong_exception()
        assert call_count == 1


class TestRetryQueryExecution:
    """Tests for retry_query_execution decorator."""

    @pytest.mark.asyncio
    async def test_retries_on_execution_exception(self) -> None:
        """Test retry on QueryExecutionException."""
        call_count = 0

        @retry_query_execution(max_attempts=3, min_wait=0.01, max_wait=0.02)
        async def flaky_query() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise QueryExecutionException("Deadlock")
            return "result"

        result = await flaky_query()
        assert result == "result"
        assert call_count == 2


# =============================================================================
# RetryContext Tests
# =============================================================================


class TestRetryContext:
    """Tests for RetryContext class."""

    def test_iteration(self) -> None:
        """Test iterating through retry attempts."""
        ctx = RetryContext(max_attempts=3)
        attempts = list(ctx)
        assert attempts == [1, 2, 3]

    def test_early_break(self) -> None:
        """Test breaking out of retry loop early."""
        ctx = RetryContext(max_attempts=5)
        collected = []
        for attempt in ctx:
            collected.append(attempt)
            if attempt == 2:
                break
        assert collected == [1, 2]

    def test_record_failure_continues(self) -> None:
        """Test that recording failure allows continuing."""
        ctx = RetryContext(max_attempts=3, exceptions=(ValueError,))
        results = []
        for attempt in ctx:
            try:
                if attempt < 3:
                    raise ValueError("retry me")
                results.append("success")
            except ValueError as e:
                ctx.record_failure(e)
        assert results == ["success"]

    def test_record_failure_raises_on_exhausted(self) -> None:
        """Test that record_failure raises when attempts exhausted."""
        ctx = RetryContext(max_attempts=2, exceptions=(ValueError,))
        with pytest.raises(ValueError, match="final"):
            for _attempt in ctx:
                try:
                    raise ValueError("final")
                except ValueError as e:
                    ctx.record_failure(e)

    def test_record_failure_raises_unhandled_exception(self) -> None:
        """Test that unhandled exception types are raised immediately."""
        ctx = RetryContext(max_attempts=3, exceptions=(ValueError,))
        with pytest.raises(TypeError):
            for _attempt in ctx:
                try:
                    raise TypeError("not retryable")
                except TypeError as e:
                    ctx.record_failure(e)

    def test_get_delay_exponential(self) -> None:
        """Test exponential backoff calculation."""
        ctx = RetryContext(max_attempts=5, base_delay=1.0, max_delay=10.0)

        # Simulate attempts
        ctx._attempt = 1
        assert ctx.get_delay() == 1.0  # 1 * 2^0

        ctx._attempt = 2
        assert ctx.get_delay() == 2.0  # 1 * 2^1

        ctx._attempt = 3
        assert ctx.get_delay() == 4.0  # 1 * 2^2

        ctx._attempt = 4
        assert ctx.get_delay() == 8.0  # 1 * 2^3

        ctx._attempt = 5
        assert ctx.get_delay() == 10.0  # capped at max_delay

    def test_should_retry_property(self) -> None:
        """Test should_retry property."""
        ctx = RetryContext(max_attempts=3)

        ctx._attempt = 1
        assert ctx.should_retry is True

        ctx._attempt = 2
        assert ctx.should_retry is True

        ctx._attempt = 3
        assert ctx.should_retry is False


# =============================================================================
# with_retry Function Tests
# =============================================================================


class TestWithRetry:
    """Tests for with_retry wrapper function."""

    @pytest.mark.asyncio
    async def test_async_function_success(self) -> None:
        """Test wrapping async function that succeeds."""
        call_count = 0

        async def async_func() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        wrapped = with_retry(async_func, max_attempts=3)
        result = await wrapped()
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_async_function_retry(self) -> None:
        """Test wrapping async function that needs retry."""
        call_count = 0

        async def flaky_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("transient error")
            return "success"

        wrapped = with_retry(
            flaky_func,
            max_attempts=3,
            exceptions=(ValueError,),
            base_delay=0.01,
        )
        result = await wrapped()
        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_async_function_exhausted(self) -> None:
        """Test async function that exhausts all retries."""
        call_count = 0

        async def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("persistent error")

        wrapped = with_retry(
            always_fails,
            max_attempts=3,
            exceptions=(ValueError,),
            base_delay=0.01,
        )
        with pytest.raises(ValueError):
            await wrapped()
        assert call_count == 3

    def test_sync_function_success(self) -> None:
        """Test wrapping sync function that succeeds."""
        call_count = 0

        def sync_func() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        wrapped = with_retry(sync_func, max_attempts=3)
        result = wrapped()
        assert result == "success"
        assert call_count == 1

    def test_sync_function_retry(self) -> None:
        """Test wrapping sync function that needs retry."""
        call_count = 0

        def flaky_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("transient error")
            return "success"

        wrapped = with_retry(
            flaky_func,
            max_attempts=3,
            exceptions=(ValueError,),
            base_delay=0.01,
        )
        result = wrapped()
        assert result == "success"
        assert call_count == 2


# =============================================================================
# Integration with Settings Tests
# =============================================================================


class TestRetryWithSettings:
    """Tests for retry decorators using settings."""

    @pytest.mark.asyncio
    async def test_uses_default_max_retries_from_settings(self) -> None:
        """Test that decorator uses max_retries from settings."""
        # This test verifies the decorator works with settings
        # The actual value comes from app.config.get_settings()
        call_count = 0

        @retry_database_operation(min_wait=0.01, max_wait=0.02)
        async def operation() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise DatabaseConnectionException("retry")
            return "done"

        result = await operation()
        assert result == "done"
        assert call_count == 2
