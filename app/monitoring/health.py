"""
Health check module for service observability (Issue #9).

This module provides comprehensive health checks for all service
dependencies and components.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from app.config import get_settings


class HealthStatus(str, Enum):
    """Health check status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """Health status for a single component."""

    name: str
    status: HealthStatus
    latency_ms: float = 0.0
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=datetime.now)


@dataclass
class ServiceHealth:
    """Overall service health status."""

    status: HealthStatus
    version: str
    uptime_seconds: float
    components: list[ComponentHealth]
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON response."""
        return {
            "status": self.status.value,
            "version": self.version,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "timestamp": self.timestamp.isoformat(),
            "components": {
                comp.name: {
                    "status": comp.status.value,
                    "latency_ms": round(comp.latency_ms, 2),
                    "message": comp.message,
                    "details": comp.details,
                    "checked_at": comp.checked_at.isoformat(),
                }
                for comp in self.components
            },
        }


class HealthChecker:
    """
    Service health checker.

    Performs health checks on all service components and dependencies.
    """

    def __init__(self) -> None:
        """Initialize the health checker."""
        self.settings = get_settings()
        self._start_time = time.time()
        self._check_timeout = self.settings.monitoring.health_check_timeout

    async def check_all(self) -> ServiceHealth:
        """
        Perform all health checks.

        Returns:
            ServiceHealth: Overall service health status
        """
        from app import __version__

        # Run all checks concurrently
        checks = await asyncio.gather(
            self._check_database(),
            self._check_model(),
            self._check_cache(),
            self._check_tracing(),
            return_exceptions=True,
        )

        components: list[ComponentHealth] = []
        for check in checks:
            if isinstance(check, Exception):
                components.append(
                    ComponentHealth(
                        name="unknown",
                        status=HealthStatus.UNHEALTHY,
                        message=str(check),
                    )
                )
            else:
                components.append(check)

        # Determine overall status
        statuses = [c.status for c in components]
        if all(s == HealthStatus.HEALTHY for s in statuses):
            overall_status = HealthStatus.HEALTHY
        elif any(s == HealthStatus.UNHEALTHY for s in statuses):
            # Check if critical components are unhealthy
            critical = ["database"]
            critical_unhealthy = any(
                c.status == HealthStatus.UNHEALTHY and c.name in critical
                for c in components
            )
            overall_status = (
                HealthStatus.UNHEALTHY if critical_unhealthy else HealthStatus.DEGRADED
            )
        else:
            overall_status = HealthStatus.DEGRADED

        return ServiceHealth(
            status=overall_status,
            version=__version__,
            uptime_seconds=time.time() - self._start_time,
            components=components,
        )

    async def _check_database(self) -> ComponentHealth:
        """Check database connectivity."""
        start = time.perf_counter()
        try:
            from db.connection import get_database

            db = await asyncio.wait_for(
                get_database(),
                timeout=self._check_timeout,
            )
            is_healthy = await asyncio.wait_for(
                db.health_check(),
                timeout=self._check_timeout,
            )

            latency = (time.perf_counter() - start) * 1000

            if is_healthy:
                return ComponentHealth(
                    name="database",
                    status=HealthStatus.HEALTHY,
                    latency_ms=latency,
                    message="Database connection healthy",
                    details={"dialect": db.dialect},
                )
            else:
                return ComponentHealth(
                    name="database",
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    message="Database health check failed",
                )

        except asyncio.TimeoutError:
            return ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                latency_ms=(time.perf_counter() - start) * 1000,
                message="Database check timed out",
            )
        except Exception as e:
            return ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                latency_ms=(time.perf_counter() - start) * 1000,
                message=f"Database error: {str(e)}",
            )

    async def _check_model(self) -> ComponentHealth:
        """Check model loading status."""
        start = time.perf_counter()
        try:
            from models.loader import get_model_loader

            loader = await asyncio.wait_for(
                get_model_loader(),
                timeout=self._check_timeout,
            )
            latency = (time.perf_counter() - start) * 1000

            if loader.is_loaded:
                info = loader.get_info()
                return ComponentHealth(
                    name="model",
                    status=HealthStatus.HEALTHY,
                    latency_ms=latency,
                    message="Model loaded and ready",
                    details={
                        "model_name": info.model_name,
                        "device": info.device,
                        "quantization": info.quantization,
                        "memory_mb": info.memory_usage_mb,
                    },
                )
            else:
                return ComponentHealth(
                    name="model",
                    status=HealthStatus.DEGRADED,
                    latency_ms=latency,
                    message="Model not loaded",
                    details={"model_name": self.settings.huggingface.model_name},
                )

        except asyncio.TimeoutError:
            return ComponentHealth(
                name="model",
                status=HealthStatus.DEGRADED,
                latency_ms=(time.perf_counter() - start) * 1000,
                message="Model check timed out",
            )
        except Exception as e:
            return ComponentHealth(
                name="model",
                status=HealthStatus.DEGRADED,
                latency_ms=(time.perf_counter() - start) * 1000,
                message=f"Model not available: {str(e)}",
            )

    async def _check_cache(self) -> ComponentHealth:
        """Check cache connectivity."""
        start = time.perf_counter()
        try:
            from app.cache import get_cache_manager

            cache = await asyncio.wait_for(
                get_cache_manager(),
                timeout=self._check_timeout,
            )
            health = await cache.health_check()
            latency = (time.perf_counter() - start) * 1000

            if health.get("redis_connected", False):
                return ComponentHealth(
                    name="cache",
                    status=HealthStatus.HEALTHY,
                    latency_ms=latency,
                    message="Redis cache connected",
                    details={
                        "redis_connected": True,
                        "in_memory_entries": health.get("in_memory_entries", 0),
                    },
                )
            else:
                return ComponentHealth(
                    name="cache",
                    status=HealthStatus.DEGRADED,
                    latency_ms=latency,
                    message="Using in-memory cache (Redis not connected)",
                    details={
                        "redis_connected": False,
                        "in_memory_entries": health.get("in_memory_entries", 0),
                    },
                )

        except asyncio.TimeoutError:
            return ComponentHealth(
                name="cache",
                status=HealthStatus.DEGRADED,
                latency_ms=(time.perf_counter() - start) * 1000,
                message="Cache check timed out",
            )
        except Exception as e:
            return ComponentHealth(
                name="cache",
                status=HealthStatus.DEGRADED,
                latency_ms=(time.perf_counter() - start) * 1000,
                message=f"Cache not available: {str(e)}",
            )

    async def _check_tracing(self) -> ComponentHealth:
        """Check tracing system status."""
        start = time.perf_counter()
        try:
            from app.monitoring.tracing import get_tracing_manager

            tracing = get_tracing_manager()
            latency = (time.perf_counter() - start) * 1000

            if tracing.is_enabled:
                return ComponentHealth(
                    name="tracing",
                    status=HealthStatus.HEALTHY,
                    latency_ms=latency,
                    message="Distributed tracing enabled",
                    details={
                        "enabled": True,
                        "endpoint": self.settings.monitoring.otlp_endpoint,
                        "sample_rate": self.settings.monitoring.trace_sample_rate,
                    },
                )
            else:
                return ComponentHealth(
                    name="tracing",
                    status=HealthStatus.DEGRADED,
                    latency_ms=latency,
                    message="Distributed tracing disabled",
                    details={"enabled": False},
                )

        except Exception as e:
            return ComponentHealth(
                name="tracing",
                status=HealthStatus.DEGRADED,
                latency_ms=(time.perf_counter() - start) * 1000,
                message=f"Tracing not available: {str(e)}",
            )


async def check_health() -> ServiceHealth:
    """
    Perform a complete health check.

    Returns:
        ServiceHealth: Service health status
    """
    checker = HealthChecker()
    return await checker.check_all()


async def check_liveness() -> bool:
    """
    Simple liveness check.

    Returns:
        True if service is alive
    """
    return True


async def check_readiness() -> bool:
    """
    Readiness check for accepting traffic.

    Returns:
        True if service is ready to accept requests
    """
    try:
        from db.connection import get_database

        db = await get_database()
        return await db.health_check()
    except Exception:
        return False
