"""
External dependency health checks (Issue #9).

This module provides health checks for external dependencies
like databases, Redis, and external APIs.
"""

import asyncio
import socket
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


class DependencyType(str, Enum):
    """Types of external dependencies."""

    DATABASE = "database"
    CACHE = "cache"
    API = "api"
    MESSAGE_QUEUE = "message_queue"
    STORAGE = "storage"


@dataclass
class DependencyCheck:
    """Result of a dependency health check."""

    name: str
    type: DependencyType
    healthy: bool
    latency_ms: float
    message: str
    details: dict[str, Any]


async def check_tcp_connection(
    host: str,
    port: int,
    timeout: float = 5.0,
) -> tuple[bool, float]:
    """
    Check TCP connectivity to a host:port.

    Args:
        host: Target hostname
        port: Target port
        timeout: Connection timeout in seconds

    Returns:
        Tuple of (connected, latency_ms)
    """
    start = time.perf_counter()
    try:
        # Create socket connection
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        latency = (time.perf_counter() - start) * 1000
        return True, latency
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        latency = (time.perf_counter() - start) * 1000
        return False, latency


async def check_http_endpoint(
    url: str,
    timeout: float = 5.0,
    expected_status: int = 200,
) -> tuple[bool, float, int]:
    """
    Check HTTP endpoint health.

    Args:
        url: Target URL
        timeout: Request timeout in seconds
        expected_status: Expected HTTP status code

    Returns:
        Tuple of (healthy, latency_ms, status_code)
    """
    import httpx

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=timeout)
            latency = (time.perf_counter() - start) * 1000
            return response.status_code == expected_status, latency, response.status_code
    except Exception:
        latency = (time.perf_counter() - start) * 1000
        return False, latency, 0


async def check_redis_connection(
    url: str,
    timeout: float = 5.0,
) -> DependencyCheck:
    """
    Check Redis connectivity.

    Args:
        url: Redis connection URL
        timeout: Connection timeout in seconds

    Returns:
        DependencyCheck result
    """
    start = time.perf_counter()
    try:
        import redis.asyncio as redis

        client = redis.from_url(url, socket_timeout=timeout)
        await asyncio.wait_for(client.ping(), timeout=timeout)
        info = await client.info("server")
        await client.close()

        latency = (time.perf_counter() - start) * 1000
        return DependencyCheck(
            name="redis",
            type=DependencyType.CACHE,
            healthy=True,
            latency_ms=latency,
            message="Redis connection healthy",
            details={
                "redis_version": info.get("redis_version", "unknown"),
                "uptime_days": info.get("uptime_in_days", 0),
            },
        )
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        return DependencyCheck(
            name="redis",
            type=DependencyType.CACHE,
            healthy=False,
            latency_ms=latency,
            message=f"Redis connection failed: {str(e)}",
            details={},
        )


async def check_database_connection(
    url: str,
    timeout: float = 5.0,
) -> DependencyCheck:
    """
    Check database connectivity.

    Args:
        url: Database connection URL
        timeout: Connection timeout in seconds

    Returns:
        DependencyCheck result
    """
    start = time.perf_counter()
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text

        # Convert URL for async driver
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://")
        elif url.startswith("mysql://"):
            url = url.replace("mysql://", "mysql+aiomysql://")
        elif url.startswith("sqlite:///"):
            url = url.replace("sqlite:///", "sqlite+aiosqlite:///")

        engine = create_async_engine(url, pool_pre_ping=True)

        async with engine.connect() as conn:
            result = await asyncio.wait_for(
                conn.execute(text("SELECT 1")),
                timeout=timeout,
            )
            await result.close()

        await engine.dispose()

        latency = (time.perf_counter() - start) * 1000
        return DependencyCheck(
            name="database",
            type=DependencyType.DATABASE,
            healthy=True,
            latency_ms=latency,
            message="Database connection healthy",
            details={"url_masked": url.split("@")[-1] if "@" in url else "local"},
        )
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        return DependencyCheck(
            name="database",
            type=DependencyType.DATABASE,
            healthy=False,
            latency_ms=latency,
            message=f"Database connection failed: {str(e)}",
            details={},
        )


async def check_otlp_collector(
    endpoint: str,
    timeout: float = 5.0,
) -> DependencyCheck:
    """
    Check OTLP collector connectivity.

    Args:
        endpoint: OTLP collector endpoint
        timeout: Connection timeout in seconds

    Returns:
        DependencyCheck result
    """
    start = time.perf_counter()

    # Parse endpoint to get host and port
    endpoint = endpoint.replace("http://", "").replace("https://", "")
    if ":" in endpoint:
        host, port_str = endpoint.split(":")
        port = int(port_str)
    else:
        host = endpoint
        port = 4317  # Default OTLP gRPC port

    connected, latency = await check_tcp_connection(host, port, timeout)

    return DependencyCheck(
        name="otlp_collector",
        type=DependencyType.API,
        healthy=connected,
        latency_ms=latency,
        message="OTLP collector reachable" if connected else "OTLP collector unreachable",
        details={"endpoint": endpoint},
    )


async def check_all_dependencies() -> list[DependencyCheck]:
    """
    Check all configured external dependencies.

    Returns:
        List of DependencyCheck results
    """
    from app.config import get_settings

    settings = get_settings()
    checks: list[DependencyCheck] = []

    # Check database
    db_check = await check_database_connection(settings.database.url)
    checks.append(db_check)

    # Check Redis if configured
    if settings.cache.redis_url:
        redis_check = await check_redis_connection(settings.cache.redis_url)
        checks.append(redis_check)

    # Check OTLP collector if tracing enabled
    if settings.monitoring.enable_tracing:
        otlp_check = await check_otlp_collector(settings.monitoring.otlp_endpoint)
        checks.append(otlp_check)

    return checks


def get_dependency_status_summary(checks: list[DependencyCheck]) -> dict[str, Any]:
    """
    Get summary of dependency health status.

    Args:
        checks: List of dependency checks

    Returns:
        Summary dictionary
    """
    healthy_count = sum(1 for c in checks if c.healthy)
    total_count = len(checks)

    return {
        "total": total_count,
        "healthy": healthy_count,
        "unhealthy": total_count - healthy_count,
        "overall_healthy": healthy_count == total_count,
        "dependencies": {
            c.name: {
                "type": c.type.value,
                "healthy": c.healthy,
                "latency_ms": round(c.latency_ms, 2),
                "message": c.message,
            }
            for c in checks
        },
    }
