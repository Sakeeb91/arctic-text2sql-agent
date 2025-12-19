"""
Monitoring and observability module (Issue #9).

This module provides comprehensive monitoring capabilities including:
- Prometheus metrics collection
- Distributed tracing with OpenTelemetry
- Structured logging with trace correlation
- Health check endpoints
- Alerting integration
"""

from typing import Any

from app.monitoring.endpoints import (
    monitoring_router,
    setup_monitoring_routes,
)
from app.monitoring.health import (
    ComponentHealth,
    HealthChecker,
    HealthStatus,
    ServiceHealth,
    check_health,
    check_liveness,
    check_readiness,
)
from app.monitoring.metrics import (
    MetricsRegistry,
    get_metrics_registry,
)
from app.monitoring.middleware import (
    MetricsMiddleware,
    setup_metrics_middleware,
)
from app.monitoring.trace_middleware import (
    TraceContextMiddleware,
    setup_trace_middleware,
)
from app.monitoring.tracing import (
    TracingManager,
    get_tracing_manager,
    trace_function,
)

__all__ = [
    # Metrics
    "MetricsRegistry",
    "get_metrics_registry",
    # Middleware
    "MetricsMiddleware",
    "setup_metrics_middleware",
    "TraceContextMiddleware",
    "setup_trace_middleware",
    # Tracing
    "TracingManager",
    "get_tracing_manager",
    "trace_function",
    # Health
    "HealthChecker",
    "HealthStatus",
    "ServiceHealth",
    "ComponentHealth",
    "check_health",
    "check_liveness",
    "check_readiness",
    # Routes
    "monitoring_router",
    "setup_monitoring_routes",
]


def setup_monitoring(app: Any) -> None:
    """
    Setup complete monitoring stack on a FastAPI application.

    This is the main entry point for enabling monitoring.
    It sets up metrics middleware, trace context propagation,
    and monitoring endpoints.

    Args:
        app: FastAPI application instance

    Usage:
        from app.monitoring import setup_monitoring
        setup_monitoring(app)
    """
    # Setup metrics middleware
    setup_metrics_middleware(app)

    # Setup trace context middleware
    setup_trace_middleware(app)

    # Setup monitoring routes
    setup_monitoring_routes(app)

    # Initialize tracing
    tracing = get_tracing_manager()
    tracing.initialize()
