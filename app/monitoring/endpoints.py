"""
Monitoring API endpoints for Prometheus and health checks (Issue #9).

This module provides HTTP endpoints for metrics scraping and
health check queries.
"""

from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from app.monitoring.dependencies import (
    check_all_dependencies,
    get_dependency_status_summary,
)
from app.monitoring.health import (
    ServiceHealth,
    check_health,
    check_liveness,
    check_readiness,
)
from app.monitoring.metrics import get_metrics_registry

# Create router for monitoring endpoints
monitoring_router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


@monitoring_router.get("/metrics")
async def prometheus_metrics() -> Response:
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus text format for scraping.
    Configured scrape interval should be 15-30 seconds.

    Returns:
        Prometheus text format metrics
    """
    registry = get_metrics_registry()
    return Response(
        content=registry.generate_metrics(),
        media_type=registry.content_type,
    )


@monitoring_router.get("/health")
async def detailed_health() -> JSONResponse:
    """
    Detailed health check endpoint.

    Returns comprehensive health status for all components.
    Use this for monitoring dashboards and alerting.

    Returns:
        JSON with detailed component health status
    """
    health: ServiceHealth = await check_health()
    status_code = 200 if health.status.value in ("healthy", "degraded") else 503

    return JSONResponse(
        content=health.to_dict(),
        status_code=status_code,
    )


@monitoring_router.get("/health/live")
async def liveness_probe() -> JSONResponse:
    """
    Kubernetes liveness probe endpoint.

    Simple check that the service process is running.
    Use for Kubernetes liveness probes.

    Returns:
        JSON with liveness status
    """
    is_alive = await check_liveness()
    return JSONResponse(
        content={"status": "alive" if is_alive else "dead"},
        status_code=200 if is_alive else 503,
    )


@monitoring_router.get("/health/ready")
async def readiness_probe() -> JSONResponse:
    """
    Kubernetes readiness probe endpoint.

    Check that the service is ready to accept traffic.
    Use for Kubernetes readiness probes.

    Returns:
        JSON with readiness status
    """
    is_ready = await check_readiness()
    return JSONResponse(
        content={"status": "ready" if is_ready else "not_ready"},
        status_code=200 if is_ready else 503,
    )


@monitoring_router.get("/dependencies")
async def dependency_health() -> JSONResponse:
    """
    External dependency health endpoint.

    Check health of all external dependencies (database, cache, etc.).

    Returns:
        JSON with dependency health status
    """
    checks = await check_all_dependencies()
    summary = get_dependency_status_summary(checks)

    status_code = 200 if summary["overall_healthy"] else 503

    return JSONResponse(
        content=summary,
        status_code=status_code,
    )


def setup_monitoring_routes(app: Any) -> None:
    """
    Setup monitoring routes on a FastAPI application.

    Args:
        app: FastAPI application instance
    """
    app.include_router(monitoring_router)
