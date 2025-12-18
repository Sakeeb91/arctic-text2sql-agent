"""
Trace context propagation middleware (Issue #9).

This module provides middleware for propagating trace context
across HTTP requests and integrating with OpenTelemetry.
"""

import uuid
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.logging_config import request_id_context
from app.monitoring.tracing import (
    get_tracing_manager,
    span_id_context,
    trace_id_context,
)


class TraceContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware for trace context propagation.

    Extracts trace context from incoming requests and injects
    it into outgoing responses. Also generates request IDs
    for correlation.

    Supported headers:
    - traceparent (W3C Trace Context)
    - X-Request-ID (custom request ID)
    - X-Trace-ID (custom trace ID)
    """

    def __init__(
        self,
        app: ASGIApp,
        generate_request_id: bool = True,
    ) -> None:
        """
        Initialize the trace context middleware.

        Args:
            app: The ASGI application
            generate_request_id: Whether to generate request IDs if not present
        """
        super().__init__(app)
        self.generate_request_id = generate_request_id
        self.tracing = get_tracing_manager()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Response],
    ) -> Response:
        """
        Process request with trace context propagation.

        Args:
            request: The incoming request
            call_next: The next middleware/handler in the chain

        Returns:
            The response with trace headers added
        """
        # Extract or generate request ID
        request_id = self._extract_request_id(request)
        request_id_context.set(request_id)

        # Extract trace context from headers
        trace_id, span_id, trace_flags = self._extract_trace_context(request)

        # Set context variables
        if trace_id:
            trace_id_context.set(trace_id)
        if span_id:
            span_id_context.set(span_id)

        # Create server span if tracing is enabled
        if self.tracing.is_enabled:
            span_name = f"{request.method} {request.url.path}"
            with self.tracing.create_span(
                span_name,
                attributes={
                    "http.method": request.method,
                    "http.url": str(request.url),
                    "http.route": request.url.path,
                    "http.host": request.headers.get("host", ""),
                    "http.user_agent": request.headers.get("user-agent", ""),
                    "request.id": request_id,
                },
                kind="server",
            ):
                response = await call_next(request)

                # Add trace attributes from response
                self.tracing.set_span_attribute(
                    "http.status_code", response.status_code
                )

                # Add response headers
                response = self._add_response_headers(
                    response, request_id, trace_id, span_id
                )

                return response
        else:
            # Process without tracing
            response = await call_next(request)
            response = self._add_response_headers(
                response, request_id, trace_id, span_id
            )
            return response

    def _extract_request_id(self, request: Request) -> str:
        """
        Extract or generate request ID.

        Args:
            request: The incoming request

        Returns:
            The request ID
        """
        # Check for existing request ID headers
        request_id = request.headers.get("X-Request-ID") or request.headers.get(
            "X-Correlation-ID"
        )

        # Generate if not present and enabled
        if not request_id and self.generate_request_id:
            request_id = str(uuid.uuid4())

        return request_id or ""

    def _extract_trace_context(
        self, request: Request
    ) -> tuple[str | None, str | None, int]:
        """
        Extract trace context from request headers.

        Supports W3C Trace Context format (traceparent header).

        Args:
            request: The incoming request

        Returns:
            Tuple of (trace_id, span_id, trace_flags)
        """
        trace_id = None
        span_id = None
        trace_flags = 0

        # Try W3C traceparent header first
        # Format: 00-{trace_id}-{span_id}-{trace_flags}
        traceparent = request.headers.get("traceparent")
        if traceparent:
            try:
                parts = traceparent.split("-")
                if len(parts) == 4:
                    trace_id = parts[1]
                    span_id = parts[2]
                    trace_flags = int(parts[3], 16)
            except (ValueError, IndexError):
                pass

        # Fall back to custom headers
        if not trace_id:
            trace_id = request.headers.get("X-Trace-ID")
        if not span_id:
            span_id = request.headers.get("X-Span-ID")

        return trace_id, span_id, trace_flags

    def _add_response_headers(
        self,
        response: Response,
        request_id: str,
        trace_id: str | None,
        span_id: str | None,
    ) -> Response:
        """
        Add trace context headers to response.

        Args:
            response: The outgoing response
            request_id: The request ID
            trace_id: The trace ID
            span_id: The span ID

        Returns:
            Response with headers added
        """
        # Add request ID header
        if request_id:
            response.headers["X-Request-ID"] = request_id

        # Add trace context headers
        current_trace_id = self.tracing.get_current_trace_id() or trace_id
        current_span_id = self.tracing.get_current_span_id() or span_id

        if current_trace_id:
            response.headers["X-Trace-ID"] = current_trace_id

            # Add W3C traceparent header
            if current_span_id:
                response.headers["traceparent"] = (
                    f"00-{current_trace_id}-{current_span_id}-01"
                )

        return response


def setup_trace_middleware(app: ASGIApp) -> None:
    """
    Setup trace context middleware on a FastAPI application.

    Args:
        app: The FastAPI application
    """
    app.add_middleware(TraceContextMiddleware)
