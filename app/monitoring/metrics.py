"""
Prometheus metrics registry and base metrics (Issue #9).

This module provides the central metrics registry and defines
all application metrics for Prometheus monitoring.
"""

from functools import lru_cache
from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    multiprocess,
    CONTENT_TYPE_LATEST,
)

from app.config import get_settings


class MetricsRegistry:
    """
    Central Prometheus metrics registry.

    Manages all application metrics and provides thread-safe access
    to metric instances.
    """

    def __init__(self) -> None:
        """Initialize the metrics registry."""
        self.settings = get_settings()
        self._registry = CollectorRegistry()
        self._initialized = False

        # Info metric for service metadata
        self.service_info = Info(
            "arctic_text2sql_service",
            "Service information",
            registry=self._registry,
        )

        # Initialize base metrics
        self._init_base_metrics()

    def _init_base_metrics(self) -> None:
        """Initialize all base metrics."""
        # Service uptime
        self.uptime_seconds = Gauge(
            "arctic_text2sql_uptime_seconds",
            "Service uptime in seconds",
            registry=self._registry,
        )

        # Active connections/requests
        self.active_requests = Gauge(
            "arctic_text2sql_active_requests",
            "Number of active requests",
            registry=self._registry,
        )

        # Initialize request metrics
        self._init_request_metrics()

        self._initialized = True

    def _init_request_metrics(self) -> None:
        """Initialize HTTP request metrics for QPS and latency tracking."""
        # Request counter (QPS)
        self.http_requests_total = Counter(
            "arctic_text2sql_http_requests_total",
            "Total HTTP requests",
            ["method", "endpoint", "status_code"],
            registry=self._registry,
        )

        # Request latency histogram with percentile buckets
        # Buckets: 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 2.5s, 5s, 10s
        self.http_request_duration_seconds = Histogram(
            "arctic_text2sql_http_request_duration_seconds",
            "HTTP request latency in seconds",
            ["method", "endpoint"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=self._registry,
        )

        # Request size histogram
        self.http_request_size_bytes = Histogram(
            "arctic_text2sql_http_request_size_bytes",
            "HTTP request size in bytes",
            ["method", "endpoint"],
            buckets=(100, 500, 1000, 5000, 10000, 50000, 100000, 500000),
            registry=self._registry,
        )

        # Response size histogram
        self.http_response_size_bytes = Histogram(
            "arctic_text2sql_http_response_size_bytes",
            "HTTP response size in bytes",
            ["method", "endpoint"],
            buckets=(100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000),
            registry=self._registry,
        )

        # In-flight requests gauge
        self.http_requests_in_flight = Gauge(
            "arctic_text2sql_http_requests_in_flight",
            "Number of HTTP requests currently being processed",
            ["method", "endpoint"],
            registry=self._registry,
        )

    def record_request(
        self,
        method: str,
        endpoint: str,
        status_code: int,
        duration_seconds: float,
        request_size: int = 0,
        response_size: int = 0,
    ) -> None:
        """
        Record HTTP request metrics.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: Request endpoint path
            status_code: HTTP response status code
            duration_seconds: Request duration in seconds
            request_size: Request body size in bytes
            response_size: Response body size in bytes
        """
        # Increment request counter
        self.http_requests_total.labels(
            method=method,
            endpoint=endpoint,
            status_code=str(status_code),
        ).inc()

        # Record latency
        self.http_request_duration_seconds.labels(
            method=method,
            endpoint=endpoint,
        ).observe(duration_seconds)

        # Record request size if available
        if request_size > 0:
            self.http_request_size_bytes.labels(
                method=method,
                endpoint=endpoint,
            ).observe(request_size)

        # Record response size if available
        if response_size > 0:
            self.http_response_size_bytes.labels(
                method=method,
                endpoint=endpoint,
            ).observe(response_size)

    def set_service_info(
        self,
        version: str,
        model_name: str,
        environment: str = "production",
    ) -> None:
        """
        Set service metadata info.

        Args:
            version: Service version
            model_name: Loaded model name
            environment: Deployment environment
        """
        self.service_info.info({
            "version": version,
            "model_name": model_name,
            "environment": environment,
            "service_name": self.settings.monitoring.service_name,
        })

    @property
    def registry(self) -> CollectorRegistry:
        """Get the Prometheus collector registry."""
        return self._registry

    def generate_metrics(self) -> bytes:
        """
        Generate Prometheus metrics output.

        Returns:
            Prometheus text format metrics
        """
        return generate_latest(self._registry)

    @property
    def content_type(self) -> str:
        """Get Prometheus content type for HTTP responses."""
        return CONTENT_TYPE_LATEST

    def get_all_metrics(self) -> dict[str, Any]:
        """
        Get all current metric values as a dictionary.

        Returns:
            Dictionary of metric names to their current values
        """
        metrics: dict[str, Any] = {}

        for metric in self._registry.collect():
            for sample in metric.samples:
                name = sample.name
                labels = sample.labels
                value = sample.value

                if labels:
                    key = f"{name}{{{','.join(f'{k}={v}' for k, v in labels.items())}}}"
                else:
                    key = name

                metrics[key] = value

        return metrics


@lru_cache
def get_metrics_registry() -> MetricsRegistry:
    """
    Get the singleton metrics registry instance.

    Returns:
        MetricsRegistry: The application metrics registry
    """
    return MetricsRegistry()
