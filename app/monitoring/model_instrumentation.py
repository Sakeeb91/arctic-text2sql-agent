"""
Model inference instrumentation for tracing and metrics (Issue #9).

This module provides instrumentation for LLM inference operations
to collect traces and metrics.
"""

import functools
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from app.monitoring.metrics import get_metrics_registry
from app.monitoring.tracing import get_tracing_manager


class ModelInstrumentor:
    """
    Instrumentor for model inference operations.

    Automatically collects:
    - Inference duration traces
    - Token usage metrics
    - Confidence score distribution
    - Memory usage
    - Reasoning step counts
    """

    def __init__(self, model_name: str = "arctic-text2sql") -> None:
        """
        Initialize the model instrumentor.

        Args:
            model_name: Name of the model being instrumented
        """
        self.model_name = model_name
        self.metrics = get_metrics_registry()
        self.tracing = get_tracing_manager()

    @contextmanager
    def trace_inference(
        self,
        operation: str = "generate",
        attributes: dict[str, Any] | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """
        Context manager for tracing model inference.

        Args:
            operation: Operation name (generate, embed, etc.)
            attributes: Additional span attributes

        Yields:
            Context dictionary for recording additional metrics
        """
        span_name = f"model.{operation}"
        start_time = time.perf_counter()

        context: dict[str, Any] = {
            "start_time": start_time,
            "input_tokens": 0,
            "output_tokens": 0,
            "confidence": 0.0,
            "status": "success",
        }

        span_attrs = {
            "model.name": self.model_name,
            "model.operation": operation,
            **(attributes or {}),
        }

        try:
            with self.tracing.create_span(
                span_name, attributes=span_attrs, kind="internal"
            ):
                yield context

                # Calculate duration
                duration = time.perf_counter() - start_time

                # Record metrics
                self.metrics.record_model_inference(
                    model_name=self.model_name,
                    status=context.get("status", "success"),
                    duration_seconds=duration,
                    confidence=context.get("confidence", 0.0),
                    input_tokens=context.get("input_tokens", 0),
                    output_tokens=context.get("output_tokens", 0),
                )

                # Add span attributes
                self.tracing.set_span_attribute("model.duration_ms", duration * 1000)
                self.tracing.set_span_attribute(
                    "model.input_tokens", context.get("input_tokens", 0)
                )
                self.tracing.set_span_attribute(
                    "model.output_tokens", context.get("output_tokens", 0)
                )
                self.tracing.set_span_attribute(
                    "model.confidence", context.get("confidence", 0.0)
                )

        except Exception as e:
            duration = time.perf_counter() - start_time
            context["status"] = "error"

            # Record error metrics
            self.metrics.record_model_inference(
                model_name=self.model_name,
                status="error",
                duration_seconds=duration,
                confidence=0.0,
            )

            self.metrics.record_error(
                error_type="model_inference",
                source=self.model_name,
                severity="error",
            )

            self.tracing.record_exception(e)
            raise

    def trace_reasoning(
        self,
        step_number: int,
        step_type: str,
        attributes: dict[str, Any] | None = None,
    ) -> Any:
        """
        Create a span for a reasoning step.

        Args:
            step_number: The reasoning step number
            step_type: Type of step (think, act, observe)
            attributes: Additional span attributes

        Returns:
            Span context manager
        """
        span_name = f"agent.{step_type}"
        span_attrs = {
            "agent.step_number": step_number,
            "agent.step_type": step_type,
            "model.name": self.model_name,
            **(attributes or {}),
        }

        return self.tracing.create_span(span_name, attributes=span_attrs)

    def record_reasoning_complete(
        self,
        total_steps: int,
        success: bool,
    ) -> None:
        """
        Record completion of reasoning loop.

        Args:
            total_steps: Total reasoning steps taken
            success: Whether reasoning succeeded
        """
        self.metrics.record_reasoning_steps(
            model_name=self.model_name,
            steps=total_steps,
        )

        self.tracing.add_event(
            "agent.reasoning_complete",
            attributes={
                "agent.total_steps": total_steps,
                "agent.success": success,
            },
        )

    def record_self_correction(
        self,
        attempt: int,
        success: bool,
        correction_type: str,
    ) -> None:
        """
        Record a self-correction attempt.

        Args:
            attempt: Correction attempt number
            success: Whether correction succeeded
            correction_type: Type of correction (syntax, semantic, etc.)
        """
        self.metrics.record_self_correction(
            model_name=self.model_name,
            success=success,
        )

        self.tracing.add_event(
            "agent.self_correction",
            attributes={
                "agent.correction_attempt": attempt,
                "agent.correction_success": success,
                "agent.correction_type": correction_type,
            },
        )

    def update_memory_metrics(
        self,
        cpu_bytes: int,
        gpu_bytes: int = 0,
    ) -> None:
        """
        Update model memory usage metrics.

        Args:
            cpu_bytes: CPU memory usage in bytes
            gpu_bytes: GPU memory usage in bytes
        """
        self.metrics.set_model_memory(
            model_name=self.model_name,
            cpu_bytes=cpu_bytes,
            gpu_bytes=gpu_bytes,
        )

    def set_loaded_status(self, loaded: bool) -> None:
        """
        Set model loaded status.

        Args:
            loaded: Whether the model is loaded
        """
        self.metrics.set_model_loaded_status(
            model_name=self.model_name,
            loaded=loaded,
        )


def trace_model_operation(
    operation: str = "generate",
    model_name: str | None = None,
) -> Any:
    """
    Decorator for tracing model operations.

    Args:
        operation: Operation name
        model_name: Model name (optional, will be extracted from self if available)

    Usage:
        @trace_model_operation("generate")
        async def generate_sql(self, query: str):
            ...
    """

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            # Try to get model name from self
            name = model_name
            if not name and args:
                instance = args[0]
                if hasattr(instance, "model_name"):
                    name = instance.model_name
            name = name or "unknown"

            instrumentor = ModelInstrumentor(name)
            with instrumentor.trace_inference(operation):
                return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            # Try to get model name from self
            name = model_name
            if not name and args:
                instance = args[0]
                if hasattr(instance, "model_name"):
                    name = instance.model_name
            name = name or "unknown"

            instrumentor = ModelInstrumentor(name)
            with instrumentor.trace_inference(operation):
                return func(*args, **kwargs)

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def get_model_instrumentor(model_name: str = "arctic-text2sql") -> ModelInstrumentor:
    """
    Get a model instrumentor instance.

    Args:
        model_name: Name of the model

    Returns:
        ModelInstrumentor instance
    """
    return ModelInstrumentor(model_name)
