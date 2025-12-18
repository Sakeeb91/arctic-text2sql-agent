"""
Metrics middleware for automatic request instrumentation (Issue #9).

This module provides FastAPI middleware for automatically collecting
HTTP request metrics without modifying individual endpoints.
"""

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.monitoring.metrics import get_metrics_registry


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware for automatic HTTP request metrics collection.

    Automatically tracks:
    - Request count (QPS)
    - Request latency (P50, P95, P99)
    - Request/response sizes
    - In-flight requests
    - Error rates

    Usage:
        from app.monitoring.middleware import MetricsMiddleware

        app.add_middleware(MetricsMiddleware)
    """

    def __init__(
        self,
        app: ASGIApp,
        exclude_paths: list[str] | None = None,
        normalize_path: bool = True,
    ) -> None:
        """
        Initialize the metrics middleware.

        Args:
            app: The ASGI application
            exclude_paths: Paths to exclude from metrics (e.g., ["/health", "/metrics"])
            normalize_path: Whether to normalize paths (remove IDs, etc.)
        """
        super().__init__(app)
        self.metrics = get_metrics_registry()
        self.exclude_paths = exclude_paths or ["/metrics", "/health", "/docs", "/redoc", "/openapi.json"]
        self.normalize_path = normalize_path

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Response],
    ) -> Response:
        """
        Process request and collect metrics.

        Args:
            request: The incoming request
            call_next: The next middleware/handler in the chain

        Returns:
            The response from the handler
        """
        path = request.url.path

        # Skip excluded paths
        if any(path.startswith(excluded) for excluded in self.exclude_paths):
            return await call_next(request)

        # Normalize path if enabled
        endpoint = self._normalize_path(path) if self.normalize_path else path
        method = request.method

        # Track in-flight requests
        self.metrics.http_requests_in_flight.labels(
            method=method,
            endpoint=endpoint,
        ).inc()

        # Get request size
        request_size = 0
        if "content-length" in request.headers:
            try:
                request_size = int(request.headers["content-length"])
            except ValueError:
                pass

        # Record start time
        start_time = time.perf_counter()

        try:
            # Process request
            response = await call_next(request)

            # Calculate duration
            duration = time.perf_counter() - start_time

            # Get response size
            response_size = 0
            if "content-length" in response.headers:
                try:
                    response_size = int(response.headers["content-length"])
                except ValueError:
                    pass

            # Record metrics
            self.metrics.record_request(
                method=method,
                endpoint=endpoint,
                status_code=response.status_code,
                duration_seconds=duration,
                request_size=request_size,
                response_size=response_size,
            )

            return response

        except Exception as e:
            # Calculate duration even on error
            duration = time.perf_counter() - start_time

            # Record error metrics
            self.metrics.record_request(
                method=method,
                endpoint=endpoint,
                status_code=500,
                duration_seconds=duration,
                request_size=request_size,
            )

            # Record exception
            self.metrics.record_exception(
                exception_class=type(e).__name__,
                endpoint=endpoint,
            )

            raise

        finally:
            # Decrement in-flight requests
            self.metrics.http_requests_in_flight.labels(
                method=method,
                endpoint=endpoint,
            ).dec()

    def _normalize_path(self, path: str) -> str:
        """
        Normalize a path by replacing dynamic segments with placeholders.

        This prevents high-cardinality labels from IDs, UUIDs, etc.

        Args:
            path: The original request path

        Returns:
            Normalized path with placeholders
        """
        import re

        # Replace UUIDs
        path = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "{uuid}",
            path,
            flags=re.IGNORECASE,
        )

        # Replace numeric IDs
        path = re.sub(r"/\d+(/|$)", r"/{id}\1", path)

        # Replace query IDs (common pattern like query_abc123)
        path = re.sub(r"query_[a-zA-Z0-9]+", "query_{id}", path)

        return path


def setup_metrics_middleware(
    app: ASGIApp,
    exclude_paths: list[str] | None = None,
) -> None:
    """
    Setup metrics middleware on a FastAPI application.

    Args:
        app: The FastAPI application
        exclude_paths: Additional paths to exclude from metrics
    """
    default_excludes = ["/metrics", "/health", "/docs", "/redoc", "/openapi.json"]
    if exclude_paths:
        default_excludes.extend(exclude_paths)

    app.add_middleware(
        MetricsMiddleware,
        exclude_paths=default_excludes,
    )
