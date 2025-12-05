"""
Resilience utilities including circuit breaker and backoff helpers.

This module centralizes defensive patterns used across the service to
gracefully degrade when downstream components fail repeatedly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypeVar

from app.exceptions import CircuitBreakerOpenException
from app.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


@dataclass
class CircuitBreakerState:
    """Track circuit breaker state."""

    failure_count: int = 0
    state: str = "closed"  # closed | open | half_open
    opened_at: datetime | None = None
    last_error: str | None = None
    half_open_attempts: int = 0


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""

    failure_threshold: int = 3
    recovery_timeout_seconds: int = 30
    half_open_max_attempts: int = 1


class CircuitBreaker:
    """
    Basic async-aware circuit breaker.

    Designed to prevent hammering unstable dependencies (e.g., model inference).
    """

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitBreakerState()

    @property
    def state(self) -> CircuitBreakerState:
        """Expose current state for introspection."""
        return self._state

    def is_open(self) -> bool:
        """Return True if breaker is open and blocking calls."""
        return self._state.state == "open"

    def _transition_to_open(self, reason: str) -> None:
        self._state.state = "open"
        self._state.opened_at = datetime.utcnow()
        self._state.last_error = reason
        self._state.half_open_attempts = 0
        logger.warning(
            "circuit_opened",
            failure_count=self._state.failure_count,
            reason=reason,
        )

    def _transition_to_half_open(self) -> None:
        self._state.state = "half_open"
        self._state.half_open_attempts = 0
        logger.info("circuit_half_open")

    def _transition_to_closed(self) -> None:
        self._state = CircuitBreakerState()
        logger.info("circuit_closed")

    def can_attempt(self) -> bool:
        """Check whether a call is allowed given current state."""
        if self._state.state == "closed":
            return True

        if self._state.state == "open":
            assert self._state.opened_at is not None
            elapsed = datetime.utcnow() - self._state.opened_at
            if elapsed >= timedelta(seconds=self._config.recovery_timeout_seconds):
                self._transition_to_half_open()
                return True
            return False

        if self._state.state == "half_open":
            return self._state.half_open_attempts < self._config.half_open_max_attempts

        return False

    def record_failure(self, reason: str) -> None:
        """Record a failure and open the circuit if threshold exceeded."""
        self._state.failure_count += 1
        self._state.last_error = reason

        if self._state.state == "half_open":
            self._transition_to_open(reason)
            return

        if self._state.failure_count >= self._config.failure_threshold:
            self._transition_to_open(reason)

    def record_success(self) -> None:
        """Reset state on success."""
        if self._state.state != "closed":
            self._transition_to_closed()
        else:
            self._state.failure_count = 0
            self._state.last_error = None

    async def run(self, func: Callable[[], Awaitable[T]]) -> T:
        """
        Execute a coroutine respecting circuit breaker rules.

        Raises CircuitBreakerOpenException if the circuit is currently blocking calls.
        """
        if not self.can_attempt():
            raise CircuitBreakerOpenException(
                details={
                    "last_error": self._state.last_error,
                    "failure_count": self._state.failure_count,
                },
                retry_after_seconds=self._config.recovery_timeout_seconds,
            )

        if self._state.state == "half_open":
            self._state.half_open_attempts += 1

        try:
            result = await func()
            self.record_success()
            return result
        except Exception as exc:  # noqa: BLE001
            self.record_failure(str(exc))
            raise


def compute_backoff_seconds(
    attempt: int,
    base_seconds: float = 1.0,
    max_seconds: float = 8.0,
) -> float:
    """
    Calculate exponential backoff delay.

    Args:
        attempt: Zero-based attempt index
        base_seconds: Starting backoff delay
        max_seconds: Maximum backoff delay

    Returns:
        Backoff delay in seconds.
    """
    delay = base_seconds * (2**attempt)
    return min(delay, max_seconds)
