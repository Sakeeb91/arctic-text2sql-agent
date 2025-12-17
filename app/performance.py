"""
Performance monitoring and metrics utilities.

Issue #8: Phase 3.1 Performance Optimization

This module provides:
- Connection pool monitoring
- Performance metrics collection
- Timing utilities
- Memory usage tracking
"""

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, Summary

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# Prometheus Metrics
# =============================================================================

# Request metrics
REQUEST_COUNT = Counter(
    "text2sql_requests_total",
    "Total number of Text2SQL requests",
    ["endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "text2sql_request_latency_seconds",
    "Request latency in seconds",
    ["endpoint"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0],
)

# Inference metrics
INFERENCE_TIME = Histogram(
    "text2sql_inference_seconds",
    "Model inference time in seconds",
    buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 30.0],
)

INFERENCE_CONFIDENCE = Histogram(
    "text2sql_inference_confidence",
    "Distribution of confidence scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

TOKENS_PROCESSED = Counter(
    "text2sql_tokens_total",
    "Total tokens processed",
    ["type"],  # input, output
)

# Cache metrics
CACHE_HITS = Counter(
    "text2sql_cache_hits_total",
    "Total cache hits",
    ["namespace"],
)

CACHE_MISSES = Counter(
    "text2sql_cache_misses_total",
    "Total cache misses",
    ["namespace"],
)

CACHE_LATENCY = Summary(
    "text2sql_cache_operation_seconds",
    "Cache operation latency",
    ["operation"],  # get, set, delete
)

# Database metrics
DB_POOL_SIZE = Gauge(
    "text2sql_db_pool_size",
    "Current database connection pool size",
)

DB_POOL_CHECKED_IN = Gauge(
    "text2sql_db_pool_checked_in",
    "Number of connections currently checked in to pool",
)

DB_POOL_CHECKED_OUT = Gauge(
    "text2sql_db_pool_checked_out",
    "Number of connections currently checked out from pool",
)

DB_POOL_OVERFLOW = Gauge(
    "text2sql_db_pool_overflow",
    "Number of overflow connections in use",
)

DB_QUERY_TIME = Histogram(
    "text2sql_db_query_seconds",
    "Database query execution time",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

# System metrics
MEMORY_USAGE_BYTES = Gauge(
    "text2sql_memory_usage_bytes",
    "Current memory usage in bytes",
    ["type"],  # rss, vms, model
)

GPU_MEMORY_USAGE_BYTES = Gauge(
    "text2sql_gpu_memory_bytes",
    "GPU memory usage in bytes",
    ["device"],
)

ACTIVE_REQUESTS = Gauge(
    "text2sql_active_requests",
    "Number of currently active requests",
)


# =============================================================================
# Performance Data Classes
# =============================================================================


@dataclass
class PoolMetrics:
    """Database connection pool metrics."""

    pool_size: int = 0
    checked_in: int = 0
    checked_out: int = 0
    overflow: int = 0
    max_overflow: int = 0
    timeout: int = 0

    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary."""
        return {
            "pool_size": self.pool_size,
            "checked_in": self.checked_in,
            "checked_out": self.checked_out,
            "overflow": self.overflow,
            "max_overflow": self.max_overflow,
            "timeout": self.timeout,
        }


@dataclass
class PerformanceSnapshot:
    """Point-in-time performance snapshot."""

    timestamp: float = field(default_factory=time.time)
    memory_rss_mb: float = 0.0
    memory_vms_mb: float = 0.0
    gpu_memory_mb: float = 0.0
    pool_metrics: PoolMetrics = field(default_factory=PoolMetrics)
    active_requests: int = 0
    cache_hit_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp,
            "memory": {
                "rss_mb": round(self.memory_rss_mb, 2),
                "vms_mb": round(self.memory_vms_mb, 2),
                "gpu_mb": round(self.gpu_memory_mb, 2),
            },
            "pool": self.pool_metrics.to_dict(),
            "active_requests": self.active_requests,
            "cache_hit_rate": round(self.cache_hit_rate, 4),
        }


# =============================================================================
# Timing Utilities
# =============================================================================


class Timer:
    """
    Context manager for timing code blocks.

    Usage:
        with Timer() as t:
            # code to time
        print(f"Elapsed: {t.elapsed_ms}ms")
    """

    def __init__(self) -> None:
        self.start_time: float = 0.0
        self.end_time: float = 0.0

    def __enter__(self) -> "Timer":
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        self.end_time = time.perf_counter()

    @property
    def elapsed(self) -> float:
        """Elapsed time in seconds."""
        return self.end_time - self.start_time

    @property
    def elapsed_ms(self) -> float:
        """Elapsed time in milliseconds."""
        return self.elapsed * 1000


@asynccontextmanager
async def async_timer() -> Any:
    """
    Async context manager for timing code blocks.

    Usage:
        async with async_timer() as t:
            await some_async_operation()
        print(f"Elapsed: {t.elapsed_ms}ms")
    """
    timer = Timer()
    timer.start_time = time.perf_counter()
    try:
        yield timer
    finally:
        timer.end_time = time.perf_counter()


def timed(metric: Histogram | Summary | None = None) -> Any:
    """
    Decorator for timing async functions.

    Args:
        metric: Optional Prometheus metric to observe

    Usage:
        @timed(INFERENCE_TIME)
        async def model_inference():
            ...
    """

    def decorator(func: Any) -> Any:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                elapsed = time.perf_counter() - start
                if metric is not None:
                    metric.observe(elapsed)
                logger.debug(
                    "function_timed",
                    function=func.__name__,
                    elapsed_ms=round(elapsed * 1000, 2),
                )

        return wrapper

    return decorator


# =============================================================================
# Monitoring Functions
# =============================================================================


async def get_pool_metrics() -> PoolMetrics:
    """
    Get current database connection pool metrics.

    Returns:
        PoolMetrics with current pool state
    """
    try:
        from db.connection import get_database

        db_manager = await get_database()
        pool = db_manager.engine.pool

        metrics = PoolMetrics(
            pool_size=pool.size(),  # type: ignore[attr-defined]
            checked_in=pool.checkedin(),  # type: ignore[attr-defined]
            checked_out=pool.checkedout(),  # type: ignore[attr-defined]
            overflow=pool.overflow(),  # type: ignore[attr-defined]
            max_overflow=db_manager.engine.pool._max_overflow,  # type: ignore[attr-defined]
            timeout=int(db_manager.engine.pool._timeout),  # type: ignore[attr-defined]
        )

        # Update Prometheus gauges
        DB_POOL_SIZE.set(metrics.pool_size)
        DB_POOL_CHECKED_IN.set(metrics.checked_in)
        DB_POOL_CHECKED_OUT.set(metrics.checked_out)
        DB_POOL_OVERFLOW.set(metrics.overflow)

        return metrics

    except Exception as e:
        logger.warning("get_pool_metrics_error", error=str(e))
        return PoolMetrics()


def get_memory_usage() -> dict[str, float]:
    """
    Get current memory usage.

    Returns:
        Dictionary with memory usage in MB
    """
    try:
        import psutil

        process = psutil.Process()
        mem_info = process.memory_info()

        rss_mb = mem_info.rss / (1024 * 1024)
        vms_mb = mem_info.vms / (1024 * 1024)

        MEMORY_USAGE_BYTES.labels(type="rss").set(mem_info.rss)
        MEMORY_USAGE_BYTES.labels(type="vms").set(mem_info.vms)

        return {
            "rss_mb": round(rss_mb, 2),
            "vms_mb": round(vms_mb, 2),
        }

    except ImportError:
        logger.debug("psutil_not_available")
        return {"rss_mb": 0.0, "vms_mb": 0.0}
    except Exception as e:
        logger.warning("get_memory_usage_error", error=str(e))
        return {"rss_mb": 0.0, "vms_mb": 0.0}


def get_gpu_memory_usage() -> dict[str, Any]:
    """
    Get GPU memory usage if available.

    Returns:
        Dictionary with GPU memory usage in MB per device
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return {}

        result: dict[str, Any] = {}
        for i in range(torch.cuda.device_count()):
            allocated = torch.cuda.memory_allocated(i)
            reserved = torch.cuda.memory_reserved(i)
            result[f"cuda:{i}"] = {
                "allocated_mb": round(allocated / (1024 * 1024), 2),
                "reserved_mb": round(reserved / (1024 * 1024), 2),
            }
            GPU_MEMORY_USAGE_BYTES.labels(device=f"cuda:{i}").set(allocated)

        return result

    except ImportError:
        return {}
    except Exception as e:
        logger.warning("get_gpu_memory_error", error=str(e))
        return {}


async def get_performance_snapshot() -> PerformanceSnapshot:
    """
    Get comprehensive performance snapshot.

    Returns:
        PerformanceSnapshot with current metrics
    """
    memory = get_memory_usage()
    gpu_memory = get_gpu_memory_usage()
    pool_metrics = await get_pool_metrics()

    # Get cache hit rate if available
    cache_hit_rate = 0.0
    try:
        from app.cache import get_cache_manager

        cache = await get_cache_manager()
        stats = cache.get_stats()
        cache_hit_rate = stats.hit_rate
    except Exception:  # nosec B110 - Cache is optional, non-critical for snapshot
        pass

    return PerformanceSnapshot(
        timestamp=time.time(),
        memory_rss_mb=memory.get("rss_mb", 0.0),
        memory_vms_mb=memory.get("vms_mb", 0.0),
        gpu_memory_mb=sum(
            v.get("allocated_mb", 0.0)
            for v in gpu_memory.values()
            if isinstance(v, dict)
        ),
        pool_metrics=pool_metrics,
        cache_hit_rate=cache_hit_rate,
    )


# =============================================================================
# Request Tracking
# =============================================================================


class RequestTracker:
    """Track active requests for monitoring."""

    def __init__(self) -> None:
        self._active_count = 0
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def track(self, endpoint: str) -> Any:
        """
        Track a request.

        Args:
            endpoint: Endpoint name for metrics
        """
        async with self._lock:
            self._active_count += 1
            ACTIVE_REQUESTS.set(self._active_count)

        start_time = time.perf_counter()
        status = "success"

        try:
            yield
        except Exception:
            status = "error"
            raise
        finally:
            elapsed = time.perf_counter() - start_time
            REQUEST_COUNT.labels(endpoint=endpoint, status=status).inc()
            REQUEST_LATENCY.labels(endpoint=endpoint).observe(elapsed)

            async with self._lock:
                self._active_count -= 1
                ACTIVE_REQUESTS.set(self._active_count)

    @property
    def active_count(self) -> int:
        """Get current active request count."""
        return self._active_count


# Global request tracker
_request_tracker: RequestTracker | None = None


def get_request_tracker() -> RequestTracker:
    """Get global request tracker instance."""
    global _request_tracker
    if _request_tracker is None:
        _request_tracker = RequestTracker()
    return _request_tracker


# =============================================================================
# Performance Configuration
# =============================================================================


@dataclass
class PerformanceConfig:
    """Performance-related configuration."""

    # Target latencies (p95) in seconds
    api_latency_target: float = 3.0
    inference_latency_target: float = 2.0
    db_query_latency_target: float = 0.5

    # Memory limits in GB
    max_memory_gb: float = 8.0

    # Throughput targets
    target_qps: int = 100

    @classmethod
    def from_settings(cls) -> "PerformanceConfig":
        """Create from application settings."""
        settings = get_settings()
        return cls(
            # Use defaults for now, could be extended with env vars
            max_memory_gb=(
                8.0 if settings.huggingface.enable_8bit_quantization else 16.0
            ),
        )


def check_performance_targets(snapshot: PerformanceSnapshot) -> dict[str, Any]:
    """
    Check if performance is meeting targets.

    Args:
        snapshot: Current performance snapshot

    Returns:
        Dictionary with target status
    """
    config = PerformanceConfig.from_settings()

    return {
        "memory_ok": snapshot.memory_rss_mb < (config.max_memory_gb * 1024),
        "pool_healthy": snapshot.pool_metrics.overflow == 0,
        "cache_effective": snapshot.cache_hit_rate > 0.5,
        "targets": {
            "max_memory_gb": config.max_memory_gb,
            "api_latency_target_s": config.api_latency_target,
            "inference_latency_target_s": config.inference_latency_target,
        },
    }
