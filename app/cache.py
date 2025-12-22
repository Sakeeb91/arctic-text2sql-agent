"""
Redis-based caching layer for performance optimization.

This module provides a comprehensive caching solution for:
- Query result caching
- Model output caching
- Schema caching with invalidation

Issue #8: Phase 3.1 Performance Optimization
"""

import asyncio
import hashlib
import json
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Any, TypeVar

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

# Type variable for generic cache decorator
T = TypeVar("T")


class CacheNamespace(str, Enum):
    """Cache key namespaces for different data types."""

    QUERY_RESULT = "query"
    MODEL_OUTPUT = "model"
    PROMPT = "prompt"
    SCHEMA = "schema"
    INFERENCE = "inference"
    VALIDATION = "validation"


@dataclass
class CacheStats:
    """Cache statistics for monitoring."""

    hits: int = 0
    misses: int = 0
    errors: int = 0
    total_requests: int = 0
    avg_hit_time_ms: float = 0.0
    avg_miss_time_ms: float = 0.0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "errors": self.errors,
            "total_requests": self.total_requests,
            "hit_rate": round(self.hit_rate, 4),
            "avg_hit_time_ms": round(self.avg_hit_time_ms, 2),
            "avg_miss_time_ms": round(self.avg_miss_time_ms, 2),
        }


@dataclass
class CacheEntry:
    """Represents a cached entry with metadata."""

    key: str
    value: Any
    created_at: float
    ttl: int
    namespace: str

    @property
    def is_expired(self) -> bool:
        """Check if entry is expired."""
        return time.time() > (self.created_at + self.ttl)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "key": self.key,
            "value": self.value,
            "created_at": self.created_at,
            "ttl": self.ttl,
            "namespace": self.namespace,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CacheEntry":
        """Create from dictionary."""
        return cls(
            key=data["key"],
            value=data["value"],
            created_at=data["created_at"],
            ttl=data["ttl"],
            namespace=data["namespace"],
        )


class CacheManager:
    """
    Async Redis cache manager with fallback to in-memory cache.

    Features:
    - Automatic connection management
    - Namespace-based key organization
    - TTL management with configurable defaults
    - Statistics tracking
    - Graceful degradation when Redis unavailable

    Usage:
        cache = await get_cache_manager()
        await cache.set("key", value, namespace=CacheNamespace.QUERY_RESULT)
        result = await cache.get("key", namespace=CacheNamespace.QUERY_RESULT)
    """

    def __init__(self) -> None:
        """Initialize cache manager."""
        self._redis: Any = None
        self._connected = False
        self._settings = get_settings()
        self._stats = CacheStats()
        self._in_memory_cache: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

        # TTL defaults per namespace (in seconds)
        self._ttl_defaults: dict[CacheNamespace, int] = {
            CacheNamespace.QUERY_RESULT: 3600,  # 1 hour
            CacheNamespace.MODEL_OUTPUT: 7200,  # 2 hours
            CacheNamespace.SCHEMA: 86400,  # 24 hours
            CacheNamespace.INFERENCE: 1800,  # 30 minutes
            CacheNamespace.VALIDATION: 3600,  # 1 hour
        }

    async def connect(self) -> bool:
        """
        Connect to Redis server.

        Returns:
            True if connected successfully, False otherwise
        """
        if self._connected:
            return True

        redis_url = self._settings.cache.redis_url
        if not redis_url:
            logger.info("cache_redis_disabled", reason="No REDIS_URL configured")
            return False

        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
                retry_on_timeout=True,
            )

            # Test connection
            await self._redis.ping()
            self._connected = True

            logger.info("cache_redis_connected", url=redis_url.split("@")[-1])
            return True

        except ImportError:
            logger.warning(
                "cache_redis_import_error", message="redis package not found"
            )
            return False
        except Exception as e:
            logger.warning("cache_redis_connection_failed", error=str(e))
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from Redis server."""
        if self._redis:
            try:
                await self._redis.close()
            except Exception as e:
                logger.warning("cache_redis_disconnect_error", error=str(e))
            finally:
                self._redis = None
                self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if connected to Redis."""
        return self._connected

    def _make_key(self, key: str, namespace: CacheNamespace) -> str:
        """
        Create namespaced cache key.

        Args:
            key: Base key
            namespace: Cache namespace

        Returns:
            Full cache key with namespace prefix
        """
        return f"arctic:{namespace.value}:{key}"

    def _generate_cache_key(self, *args: Any, **kwargs: Any) -> str:
        """
        Generate deterministic cache key from arguments.

        Args:
            *args: Positional arguments to hash
            **kwargs: Keyword arguments to hash

        Returns:
            SHA256 hash of arguments
        """
        key_data = json.dumps(
            {
                "args": [str(a) for a in args],
                "kwargs": {k: str(v) for k, v in sorted(kwargs.items())},
            },
            sort_keys=True,
        )
        return hashlib.sha256(key_data.encode()).hexdigest()[:32]

    async def get(
        self,
        key: str,
        namespace: CacheNamespace = CacheNamespace.QUERY_RESULT,
    ) -> Any | None:
        """
        Get value from cache.

        Args:
            key: Cache key
            namespace: Cache namespace

        Returns:
            Cached value or None if not found/expired
        """
        start_time = time.perf_counter()
        full_key = self._make_key(key, namespace)
        self._stats.total_requests += 1

        try:
            if self._connected and self._redis:
                # Try Redis first
                data = await self._redis.get(full_key)
                if data:
                    entry = CacheEntry.from_dict(json.loads(data))
                    if not entry.is_expired:
                        self._stats.hits += 1
                        elapsed = (time.perf_counter() - start_time) * 1000
                        self._update_hit_time(elapsed)
                        logger.debug("cache_hit", key=key, namespace=namespace.value)
                        return entry.value

            # Fall back to in-memory cache
            if full_key in self._in_memory_cache:
                entry = self._in_memory_cache[full_key]
                if not entry.is_expired:
                    self._stats.hits += 1
                    elapsed = (time.perf_counter() - start_time) * 1000
                    self._update_hit_time(elapsed)
                    logger.debug("cache_hit_memory", key=key, namespace=namespace.value)
                    return entry.value
                else:
                    # Clean up expired entry
                    del self._in_memory_cache[full_key]

            self._stats.misses += 1
            elapsed = (time.perf_counter() - start_time) * 1000
            self._update_miss_time(elapsed)
            logger.debug("cache_miss", key=key, namespace=namespace.value)
            return None

        except Exception as e:
            self._stats.errors += 1
            logger.warning("cache_get_error", key=key, error=str(e))
            return None

    async def set(
        self,
        key: str,
        value: Any,
        namespace: CacheNamespace = CacheNamespace.QUERY_RESULT,
        ttl: int | None = None,
    ) -> bool:
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            namespace: Cache namespace
            ttl: Time to live in seconds (uses namespace default if None)

        Returns:
            True if successful, False otherwise
        """
        full_key = self._make_key(key, namespace)
        effective_ttl = (
            ttl
            if ttl is not None
            else self._ttl_defaults.get(namespace, self._settings.cache.ttl)
        )

        entry = CacheEntry(
            key=key,
            value=value,
            created_at=time.time(),
            ttl=effective_ttl,
            namespace=namespace.value,
        )

        try:
            if self._connected and self._redis:
                # Store in Redis
                await self._redis.setex(
                    full_key,
                    effective_ttl,
                    json.dumps(entry.to_dict()),
                )
                logger.debug(
                    "cache_set",
                    key=key,
                    namespace=namespace.value,
                    ttl=effective_ttl,
                )
                return True

            # Fall back to in-memory cache
            async with self._lock:
                self._in_memory_cache[full_key] = entry
                # Limit in-memory cache size
                if len(self._in_memory_cache) > 1000:
                    await self._evict_oldest()

            logger.debug(
                "cache_set_memory",
                key=key,
                namespace=namespace.value,
                ttl=effective_ttl,
            )
            return True

        except Exception as e:
            self._stats.errors += 1
            logger.warning("cache_set_error", key=key, error=str(e))
            return False

    async def delete(
        self,
        key: str,
        namespace: CacheNamespace = CacheNamespace.QUERY_RESULT,
    ) -> bool:
        """
        Delete value from cache.

        Args:
            key: Cache key
            namespace: Cache namespace

        Returns:
            True if deleted, False otherwise
        """
        full_key = self._make_key(key, namespace)

        try:
            deleted = False

            if self._connected and self._redis:
                result = await self._redis.delete(full_key)
                deleted = result > 0

            # Also delete from in-memory cache
            if full_key in self._in_memory_cache:
                del self._in_memory_cache[full_key]
                deleted = True

            logger.debug(
                "cache_delete", key=key, namespace=namespace.value, deleted=deleted
            )
            return deleted

        except Exception as e:
            self._stats.errors += 1
            logger.warning("cache_delete_error", key=key, error=str(e))
            return False

    async def invalidate_namespace(self, namespace: CacheNamespace) -> int:
        """
        Invalidate all keys in a namespace.

        Args:
            namespace: Namespace to invalidate

        Returns:
            Number of keys deleted
        """
        pattern = self._make_key("*", namespace)
        deleted_count = 0

        try:
            if self._connected and self._redis:
                async for key in self._redis.scan_iter(match=pattern):
                    await self._redis.delete(key)
                    deleted_count += 1

            # Also clear from in-memory cache
            keys_to_delete = [
                k
                for k in self._in_memory_cache
                if k.startswith(f"arctic:{namespace.value}:")
            ]
            for key in keys_to_delete:
                del self._in_memory_cache[key]
                deleted_count += 1

            logger.info(
                "cache_namespace_invalidated",
                namespace=namespace.value,
                deleted_count=deleted_count,
            )
            return deleted_count

        except Exception as e:
            self._stats.errors += 1
            logger.warning(
                "cache_invalidate_error", namespace=namespace.value, error=str(e)
            )
            return deleted_count

    async def clear(self) -> bool:
        """
        Clear all cache entries.

        Returns:
            True if successful, False otherwise
        """
        try:
            if self._connected and self._redis:
                async for key in self._redis.scan_iter(match="arctic:*"):
                    await self._redis.delete(key)

            self._in_memory_cache.clear()
            logger.info("cache_cleared")
            return True

        except Exception as e:
            self._stats.errors += 1
            logger.warning("cache_clear_error", error=str(e))
            return False

    async def _evict_oldest(self) -> None:
        """Evict oldest entries from in-memory cache."""
        if len(self._in_memory_cache) <= 500:
            return

        # Sort by creation time and remove oldest 200 entries
        sorted_entries = sorted(
            self._in_memory_cache.items(),
            key=lambda x: x[1].created_at,
        )
        for key, _ in sorted_entries[:200]:
            del self._in_memory_cache[key]

        logger.debug("cache_evicted", count=200)

    def _update_hit_time(self, elapsed_ms: float) -> None:
        """Update average hit time."""
        if self._stats.hits == 1:
            self._stats.avg_hit_time_ms = elapsed_ms
        else:
            self._stats.avg_hit_time_ms = (
                self._stats.avg_hit_time_ms * (self._stats.hits - 1) + elapsed_ms
            ) / self._stats.hits

    def _update_miss_time(self, elapsed_ms: float) -> None:
        """Update average miss time."""
        if self._stats.misses == 1:
            self._stats.avg_miss_time_ms = elapsed_ms
        else:
            self._stats.avg_miss_time_ms = (
                self._stats.avg_miss_time_ms * (self._stats.misses - 1) + elapsed_ms
            ) / self._stats.misses

    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._stats

    def reset_stats(self) -> None:
        """Reset cache statistics."""
        self._stats = CacheStats()

    async def health_check(self) -> dict[str, Any]:
        """
        Check cache health status.

        Returns:
            Health status dictionary
        """
        status = {
            "redis_connected": self._connected,
            "redis_url": (
                self._settings.cache.redis_url.split("@")[-1]
                if self._settings.cache.redis_url
                else None
            ),
            "in_memory_entries": len(self._in_memory_cache),
            "stats": self._stats.to_dict(),
        }

        if self._connected and self._redis:
            try:
                info = await self._redis.info("memory")
                status["redis_memory_used"] = info.get("used_memory_human", "unknown")
            except Exception:  # nosec B110 - Optional Redis info, non-critical
                pass

        return status


# Global cache manager instance
_cache_manager: CacheManager | None = None


async def get_cache_manager() -> CacheManager:
    """
    Get or create cache manager instance.

    Returns:
        CacheManager singleton instance
    """
    global _cache_manager

    if _cache_manager is None:
        _cache_manager = CacheManager()
        await _cache_manager.connect()

    return _cache_manager


@asynccontextmanager
async def cache_context() -> Any:
    """
    Context manager for cache operations.

    Ensures proper cleanup on exit.
    """
    cache = await get_cache_manager()
    try:
        yield cache
    finally:
        pass  # Connection managed by singleton


def cached(
    namespace: CacheNamespace = CacheNamespace.QUERY_RESULT,
    ttl: int | None = None,
    key_prefix: str = "",
) -> Any:
    """
    Decorator for caching async function results.

    Args:
        namespace: Cache namespace
        ttl: Cache TTL in seconds
        key_prefix: Optional prefix for cache key

    Usage:
        @cached(namespace=CacheNamespace.QUERY_RESULT, ttl=3600)
        async def expensive_operation(arg1, arg2):
            ...
    """

    def decorator(func: Any) -> Any:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            cache = await get_cache_manager()

            # Generate cache key from function name and arguments
            key_parts = [key_prefix, func.__name__] if key_prefix else [func.__name__]
            key_data = json.dumps(
                {
                    "args": [str(a) for a in args],
                    "kwargs": {k: str(v) for k, v in sorted(kwargs.items())},
                },
                sort_keys=True,
            )
            cache_key = hashlib.sha256(
                (":".join(key_parts) + ":" + key_data).encode()
            ).hexdigest()[:32]

            # Try to get from cache
            cached_result = await cache.get(cache_key, namespace)
            if cached_result is not None:
                return cached_result

            # Execute function and cache result
            result = await func(*args, **kwargs)
            await cache.set(cache_key, result, namespace, ttl)

            return result

        return wrapper

    return decorator


# =============================================================================
# Specialized Cache Functions
# =============================================================================


async def cache_query_result(
    query_hash: str,
    sql: str,
    confidence: float,
    results: list[dict[str, Any]] | None = None,
    ttl: int | None = None,
) -> bool:
    """
    Cache a query generation result.

    Args:
        query_hash: Hash of the natural language query
        sql: Generated SQL
        confidence: Confidence score
        results: Optional query results
        ttl: Optional TTL override

    Returns:
        True if cached successfully
    """
    cache = await get_cache_manager()
    data = {
        "sql": sql,
        "confidence": confidence,
        "results": results,
        "cached_at": time.time(),
    }
    return await cache.set(query_hash, data, CacheNamespace.QUERY_RESULT, ttl)


async def get_cached_query_result(
    query_hash: str,
) -> dict[str, Any] | None:
    """
    Get cached query result.

    Args:
        query_hash: Hash of the natural language query

    Returns:
        Cached result or None
    """
    cache = await get_cache_manager()
    return await cache.get(query_hash, CacheNamespace.QUERY_RESULT)


async def cache_model_output(
    prompt_hash: str,
    output: str,
    confidence: float,
    ttl: int | None = None,
) -> bool:
    """
    Cache model inference output.

    Args:
        prompt_hash: Hash of the input prompt
        output: Model output
        confidence: Confidence score
        ttl: Optional TTL override

    Returns:
        True if cached successfully
    """
    cache = await get_cache_manager()
    data = {
        "output": output,
        "confidence": confidence,
        "cached_at": time.time(),
    }
    return await cache.set(prompt_hash, data, CacheNamespace.MODEL_OUTPUT, ttl)


async def get_cached_model_output(
    prompt_hash: str,
) -> dict[str, Any] | None:
    """
    Get cached model output.

    Args:
        prompt_hash: Hash of the input prompt

    Returns:
        Cached output or None
    """
    cache = await get_cache_manager()
    return await cache.get(prompt_hash, CacheNamespace.MODEL_OUTPUT)


async def cache_schema(
    database_id: str,
    schema_data: dict[str, Any],
    ttl: int | None = None,
) -> bool:
    """
    Cache database schema.

    Args:
        database_id: Database identifier
        schema_data: Schema information
        ttl: Optional TTL override

    Returns:
        True if cached successfully
    """
    cache = await get_cache_manager()
    return await cache.set(database_id, schema_data, CacheNamespace.SCHEMA, ttl)


async def get_cached_schema(
    database_id: str,
) -> dict[str, Any] | None:
    """
    Get cached schema.

    Args:
        database_id: Database identifier

    Returns:
        Cached schema or None
    """
    cache = await get_cache_manager()
    return await cache.get(database_id, CacheNamespace.SCHEMA)


async def invalidate_schema_cache(database_id: str | None = None) -> int:
    """
    Invalidate schema cache.

    Args:
        database_id: Specific database to invalidate, or None for all

    Returns:
        Number of entries invalidated
    """
    cache = await get_cache_manager()
    if database_id:
        deleted = await cache.delete(database_id, CacheNamespace.SCHEMA)
        return 1 if deleted else 0
    return await cache.invalidate_namespace(CacheNamespace.SCHEMA)


def generate_query_hash(
    natural_query: str,
    database_id: str,
    execute: bool = False,
) -> str:
    """
    Generate hash for a query request.

    Args:
        natural_query: Natural language query
        database_id: Database identifier
        execute: Whether execution is requested

    Returns:
        SHA256 hash of query parameters
    """
    key_data = json.dumps(
        {
            "query": natural_query.lower().strip(),
            "database_id": database_id,
            "execute": execute,
        },
        sort_keys=True,
    )
    return hashlib.sha256(key_data.encode()).hexdigest()[:32]


def generate_prompt_hash(prompt: str) -> str:
    """
    Generate hash for a model prompt.

    Args:
        prompt: Input prompt

    Returns:
        SHA256 hash of prompt
    """
    return hashlib.sha256(prompt.encode()).hexdigest()[:32]
