"""
Unit tests for resilience utilities.
"""

import asyncio
from datetime import timedelta

import pytest

from app.exceptions import CircuitBreakerOpenException
from app.resilience import CircuitBreaker, CircuitBreakerConfig, compute_backoff_seconds


class TestComputeBackoffSeconds:
    """Tests for exponential backoff helper."""

    def test_backoff_grows_until_max(self) -> None:
        """Backoff should grow exponentially but cap at max."""
        delays = [
            compute_backoff_seconds(i, base_seconds=1.0, max_seconds=5.0)
            for i in range(5)
        ]
        assert delays[:3] == [1.0, 2.0, 4.0]
        assert delays[3] == 5.0  # capped
        assert delays[4] == 5.0  # still capped


class TestCircuitBreaker:
    """Tests for circuit breaker behavior."""

    @pytest.mark.asyncio
    async def test_opens_after_failures(self) -> None:
        """Circuit opens once failure threshold is exceeded."""
        breaker = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=60)
        )

        async def failing_call() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await breaker.run(failing_call)
        with pytest.raises(RuntimeError):
            await breaker.run(failing_call)

        assert breaker.is_open() is True
        assert breaker.state.failure_count == 2

    @pytest.mark.asyncio
    async def test_blocks_when_open(self) -> None:
        """Circuit should block new calls while open."""
        breaker = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1, recovery_timeout_seconds=60)
        )

        async def failing_call() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await breaker.run(failing_call)

        with pytest.raises(CircuitBreakerOpenException):
            await breaker.run(lambda: asyncio.sleep(0))

    @pytest.mark.asyncio
    async def test_half_open_allows_attempt(self) -> None:
        """Circuit transitions to half-open after recovery timeout."""
        breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout_seconds=0,
                half_open_max_attempts=1,
            )
        )

        async def failing_call() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await breaker.run(failing_call)

        # Should now be open but ready to half-open immediately
        assert breaker.can_attempt() is True
        assert breaker.state.state == "half_open"

    @pytest.mark.asyncio
    async def test_success_resets_state(self) -> None:
        """Successful call closes circuit and resets counters."""
        breaker = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1, recovery_timeout_seconds=60)
        )

        async def failing_call() -> None:
            raise RuntimeError("boom")

        async def success_call() -> str:
            return "ok"

        with pytest.raises(RuntimeError):
            await breaker.run(failing_call)

        assert breaker.is_open() is True

        # Force to half-open for the test
        breaker.state.opened_at = breaker.state.opened_at - timedelta(seconds=120)
        assert breaker.can_attempt() is True

        result = await breaker.run(success_call)
        assert result == "ok"
        assert breaker.is_open() is False
        assert breaker.state.failure_count == 0
