"""
Monitoring and observability module (Issue #9).

This module provides comprehensive monitoring capabilities including:
- Prometheus metrics collection
- Distributed tracing with OpenTelemetry
- Structured logging with trace correlation
- Health check endpoints
- Alerting integration
"""

from app.monitoring.metrics import (
    MetricsRegistry,
    get_metrics_registry,
)

__all__ = [
    "MetricsRegistry",
    "get_metrics_registry",
]
