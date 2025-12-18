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

        self._initialized = True

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
