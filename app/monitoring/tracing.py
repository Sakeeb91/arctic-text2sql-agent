"""
Distributed tracing with OpenTelemetry (Issue #9).

This module provides distributed tracing capabilities using OpenTelemetry,
allowing request tracking across service boundaries.
"""

from contextvars import ContextVar
from functools import lru_cache
from typing import Any

from app.config import get_settings

# Context variable for current trace ID
trace_id_context: ContextVar[str | None] = ContextVar("trace_id", default=None)
span_id_context: ContextVar[str | None] = ContextVar("span_id", default=None)


class TracingManager:
    """
    Manager for OpenTelemetry distributed tracing.

    Handles tracer initialization, span creation, and context propagation.
    """

    def __init__(self) -> None:
        """Initialize the tracing manager."""
        self.settings = get_settings()
        self._tracer = None
        self._provider = None
        self._initialized = False

    def initialize(self) -> bool:
        """
        Initialize OpenTelemetry tracing.

        Returns:
            True if initialization succeeded, False otherwise
        """
        if not self.settings.monitoring.enable_tracing:
            return False

        if self._initialized:
            return True

        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import (
                SERVICE_NAME,
                SERVICE_VERSION,
                Resource,
            )
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

            # Create resource with service info
            resource = Resource.create(
                {
                    SERVICE_NAME: self.settings.monitoring.service_name,
                    SERVICE_VERSION: self.settings.monitoring.service_version,
                    "deployment.environment": "production",
                }
            )

            # Create sampler based on configured rate
            sampler = TraceIdRatioBased(self.settings.monitoring.trace_sample_rate)

            # Create tracer provider
            self._provider = TracerProvider(
                resource=resource,
                sampler=sampler,
            )

            # Create OTLP exporter
            otlp_exporter = OTLPSpanExporter(
                endpoint=self.settings.monitoring.otlp_endpoint,
                insecure=True,  # Use insecure for local development
            )

            # Add span processor
            self._provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

            # Set as global tracer provider
            trace.set_tracer_provider(self._provider)

            # Get tracer
            self._tracer = trace.get_tracer(
                self.settings.monitoring.service_name,
                self.settings.monitoring.service_version,
            )

            self._initialized = True
            return True

        except ImportError:
            # OpenTelemetry not installed
            return False
        except Exception:
            # Initialization failed
            return False

    @property
    def tracer(self) -> Any:
        """Get the OpenTelemetry tracer."""
        if not self._initialized:
            self.initialize()
        return self._tracer

    @property
    def is_enabled(self) -> bool:
        """Check if tracing is enabled and initialized."""
        return self._initialized and self._tracer is not None

    def create_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        kind: str = "internal",
    ) -> Any:
        """
        Create a new span.

        Args:
            name: Span name
            attributes: Span attributes
            kind: Span kind (internal, server, client, producer, consumer)

        Returns:
            The created span or a no-op context manager
        """
        if not self.is_enabled:
            return NoOpSpan()

        from opentelemetry.trace import SpanKind

        kind_map = {
            "internal": SpanKind.INTERNAL,
            "server": SpanKind.SERVER,
            "client": SpanKind.CLIENT,
            "producer": SpanKind.PRODUCER,
            "consumer": SpanKind.CONSUMER,
        }

        span_kind = kind_map.get(kind, SpanKind.INTERNAL)

        return self._tracer.start_as_current_span(
            name,
            attributes=attributes or {},
            kind=span_kind,
        )

    def get_current_trace_id(self) -> str | None:
        """
        Get the current trace ID.

        Returns:
            The current trace ID or None
        """
        if not self.is_enabled:
            return trace_id_context.get()

        from opentelemetry import trace

        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            return format(span.get_span_context().trace_id, "032x")
        return trace_id_context.get()

    def get_current_span_id(self) -> str | None:
        """
        Get the current span ID.

        Returns:
            The current span ID or None
        """
        if not self.is_enabled:
            return span_id_context.get()

        from opentelemetry import trace

        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            return format(span.get_span_context().span_id, "016x")
        return span_id_context.get()

    def add_event(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """
        Add an event to the current span.

        Args:
            name: Event name
            attributes: Event attributes
        """
        if not self.is_enabled:
            return

        from opentelemetry import trace

        span = trace.get_current_span()
        if span:
            span.add_event(name, attributes=attributes or {})

    def set_span_attribute(self, key: str, value: Any) -> None:
        """
        Set an attribute on the current span.

        Args:
            key: Attribute key
            value: Attribute value
        """
        if not self.is_enabled:
            return

        from opentelemetry import trace

        span = trace.get_current_span()
        if span:
            span.set_attribute(key, value)

    def record_exception(self, exception: Exception) -> None:
        """
        Record an exception on the current span.

        Args:
            exception: The exception to record
        """
        if not self.is_enabled:
            return

        from opentelemetry import trace
        from opentelemetry.trace import StatusCode

        span = trace.get_current_span()
        if span:
            span.record_exception(exception)
            span.set_status(StatusCode.ERROR, str(exception))

    def shutdown(self) -> None:
        """Shutdown the tracer provider."""
        if self._provider:
            self._provider.shutdown()
            self._initialized = False


class NoOpSpan:
    """No-operation span for when tracing is disabled."""

    def __enter__(self) -> "NoOpSpan":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        pass

    def record_exception(self, exception: Exception) -> None:
        pass


@lru_cache
def get_tracing_manager() -> TracingManager:
    """
    Get the singleton tracing manager instance.

    Returns:
        TracingManager: The application tracing manager
    """
    return TracingManager()


def trace_function(
    name: str | None = None,
    attributes: dict[str, Any] | None = None,
):
    """
    Decorator to trace a function.

    Args:
        name: Span name (defaults to function name)
        attributes: Additional span attributes

    Usage:
        @trace_function()
        async def my_function():
            ...

        @trace_function(name="custom_name", attributes={"key": "value"})
        def another_function():
            ...
    """
    import asyncio
    import functools

    def decorator(func):
        span_name = name or func.__qualname__

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            manager = get_tracing_manager()
            with manager.create_span(span_name, attributes=attributes):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    manager.record_exception(e)
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            manager = get_tracing_manager()
            with manager.create_span(span_name, attributes=attributes):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    manager.record_exception(e)
                    raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
