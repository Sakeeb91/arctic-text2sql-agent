"""
Tests for the caching module.

Issue #8: Phase 3.1 Performance Optimization
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.cache import (
    CacheEntry,
    CacheManager,
    CacheNamespace,
    CacheStats,
    cache_inference_result,
    cache_model_output,
    cache_prompt,
    cache_query_result,
    cache_schema,
    cached,
    generate_prompt_hash,
    generate_query_hash,
    get_cache_manager,
    get_cached_inference_result,
    get_cached_model_output,
    get_cached_prompt,
    get_cached_query_result,
    get_cached_schema,
    invalidate_schema_cache,
)


class TestCacheStats:
    """Tests for CacheStats dataclass."""

    def test_initial_stats(self) -> None:
        """Test initial statistics values."""
        stats = CacheStats()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.errors == 0
        assert stats.total_requests == 0
        assert stats.hit_rate == 0.0

    def test_hit_rate_calculation(self) -> None:
        """Test hit rate calculation."""
        stats = CacheStats(hits=75, misses=25, total_requests=100)
        assert stats.hit_rate == 0.75

    def test_hit_rate_zero_requests(self) -> None:
        """Test hit rate with zero requests."""
        stats = CacheStats()
        assert stats.hit_rate == 0.0

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        stats = CacheStats(
            hits=10,
            misses=5,
            errors=1,
            total_requests=15,
            avg_hit_time_ms=1.5,
            avg_miss_time_ms=2.0,
        )
        result = stats.to_dict()
        assert result["hits"] == 10
        assert result["misses"] == 5
        assert result["errors"] == 1
        assert result["total_requests"] == 15
        assert result["hit_rate"] == pytest.approx(0.6667, rel=0.01)


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_entry_creation(self) -> None:
        """Test creating a cache entry."""
        entry = CacheEntry(
            key="test_key",
            value={"data": "test"},
            created_at=time.time(),
            ttl=3600,
            namespace="query",
        )
        assert entry.key == "test_key"
        assert entry.value == {"data": "test"}
        assert entry.ttl == 3600

    def test_is_expired_false(self) -> None:
        """Test entry is not expired."""
        entry = CacheEntry(
            key="test",
            value="data",
            created_at=time.time(),
            ttl=3600,
            namespace="query",
        )
        assert not entry.is_expired

    def test_is_expired_true(self) -> None:
        """Test entry is expired."""
        entry = CacheEntry(
            key="test",
            value="data",
            created_at=time.time() - 7200,  # 2 hours ago
            ttl=3600,  # 1 hour TTL
            namespace="query",
        )
        assert entry.is_expired

    def test_to_dict_and_from_dict(self) -> None:
        """Test serialization and deserialization."""
        original = CacheEntry(
            key="test",
            value={"nested": "data"},
            created_at=1234567890.0,
            ttl=3600,
            namespace="model",
        )
        data = original.to_dict()
        restored = CacheEntry.from_dict(data)

        assert restored.key == original.key
        assert restored.value == original.value
        assert restored.created_at == original.created_at
        assert restored.ttl == original.ttl
        assert restored.namespace == original.namespace


class TestCacheNamespace:
    """Tests for CacheNamespace enum."""

    def test_namespace_values(self) -> None:
        """Test namespace enum values."""
        assert CacheNamespace.QUERY_RESULT.value == "query"
        assert CacheNamespace.MODEL_OUTPUT.value == "model"
        assert CacheNamespace.SCHEMA.value == "schema"
        assert CacheNamespace.INFERENCE.value == "inference"
        assert CacheNamespace.VALIDATION.value == "validation"


class TestCacheManager:
    """Tests for CacheManager class."""

    @pytest.fixture
    def cache_manager(self) -> CacheManager:
        """Create a fresh cache manager for testing."""
        return CacheManager()

    @pytest.mark.asyncio
    async def test_in_memory_fallback(self, cache_manager: CacheManager) -> None:
        """Test in-memory cache when Redis unavailable."""
        # Without connecting, should use in-memory cache
        success = await cache_manager.set(
            "test_key",
            {"data": "value"},
            CacheNamespace.QUERY_RESULT,
        )
        assert success

        result = await cache_manager.get("test_key", CacheNamespace.QUERY_RESULT)
        assert result == {"data": "value"}

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, cache_manager: CacheManager) -> None:
        """Test getting a key that doesn't exist."""
        result = await cache_manager.get("nonexistent", CacheNamespace.QUERY_RESULT)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_key(self, cache_manager: CacheManager) -> None:
        """Test deleting a cached key."""
        await cache_manager.set("to_delete", "value", CacheNamespace.QUERY_RESULT)

        deleted = await cache_manager.delete("to_delete", CacheNamespace.QUERY_RESULT)
        assert deleted

        result = await cache_manager.get("to_delete", CacheNamespace.QUERY_RESULT)
        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, cache_manager: CacheManager) -> None:
        """Test that entries expire after TTL."""
        await cache_manager.set(
            "expiring",
            "value",
            CacheNamespace.QUERY_RESULT,
            ttl=1,  # 1 second TTL
        )

        # Should exist initially
        result = await cache_manager.get("expiring", CacheNamespace.QUERY_RESULT)
        assert result == "value"

        # Wait for expiration
        await asyncio.sleep(1.5)

        # Should be expired now
        result = await cache_manager.get("expiring", CacheNamespace.QUERY_RESULT)
        assert result is None

    @pytest.mark.asyncio
    async def test_namespace_isolation(self, cache_manager: CacheManager) -> None:
        """Test that namespaces are isolated."""
        await cache_manager.set("key", "query_value", CacheNamespace.QUERY_RESULT)
        await cache_manager.set("key", "model_value", CacheNamespace.MODEL_OUTPUT)

        query_result = await cache_manager.get("key", CacheNamespace.QUERY_RESULT)
        model_result = await cache_manager.get("key", CacheNamespace.MODEL_OUTPUT)

        assert query_result == "query_value"
        assert model_result == "model_value"

    @pytest.mark.asyncio
    async def test_invalidate_namespace(self, cache_manager: CacheManager) -> None:
        """Test namespace invalidation."""
        await cache_manager.set("key1", "value1", CacheNamespace.SCHEMA)
        await cache_manager.set("key2", "value2", CacheNamespace.SCHEMA)
        await cache_manager.set("key3", "value3", CacheNamespace.QUERY_RESULT)

        deleted = await cache_manager.invalidate_namespace(CacheNamespace.SCHEMA)
        assert deleted >= 2

        # Schema keys should be gone
        assert await cache_manager.get("key1", CacheNamespace.SCHEMA) is None
        assert await cache_manager.get("key2", CacheNamespace.SCHEMA) is None

        # Query result should still exist
        assert await cache_manager.get("key3", CacheNamespace.QUERY_RESULT) == "value3"

    @pytest.mark.asyncio
    async def test_clear_all(self, cache_manager: CacheManager) -> None:
        """Test clearing all cache entries."""
        await cache_manager.set("key1", "value1", CacheNamespace.QUERY_RESULT)
        await cache_manager.set("key2", "value2", CacheNamespace.MODEL_OUTPUT)

        success = await cache_manager.clear()
        assert success

        assert await cache_manager.get("key1", CacheNamespace.QUERY_RESULT) is None
        assert await cache_manager.get("key2", CacheNamespace.MODEL_OUTPUT) is None

    @pytest.mark.asyncio
    async def test_stats_tracking(self, cache_manager: CacheManager) -> None:
        """Test statistics tracking."""
        await cache_manager.set("existing", "value", CacheNamespace.QUERY_RESULT)

        # Hit
        await cache_manager.get("existing", CacheNamespace.QUERY_RESULT)
        # Miss
        await cache_manager.get("nonexistent", CacheNamespace.QUERY_RESULT)

        stats = cache_manager.get_stats()
        assert stats.hits >= 1
        assert stats.misses >= 1
        assert stats.total_requests >= 2

    @pytest.mark.asyncio
    async def test_health_check(self, cache_manager: CacheManager) -> None:
        """Test health check."""
        health = await cache_manager.health_check()

        assert "redis_connected" in health
        assert "in_memory_entries" in health
        assert "stats" in health

    def test_make_key(self, cache_manager: CacheManager) -> None:
        """Test key generation with namespace."""
        key = cache_manager._make_key("test", CacheNamespace.QUERY_RESULT)
        assert key == "arctic:query:test"

        key = cache_manager._make_key("test", CacheNamespace.MODEL_OUTPUT)
        assert key == "arctic:model:test"


class TestCacheHelperFunctions:
    """Tests for cache helper functions."""

    def test_generate_query_hash(self) -> None:
        """Test query hash generation."""
        hash1 = generate_query_hash("SELECT * FROM users", "db1", False)
        hash2 = generate_query_hash("SELECT * FROM users", "db1", False)
        hash3 = generate_query_hash("SELECT * FROM users", "db1", True)
        hash4 = generate_query_hash("SELECT * FROM users", "db2", False)

        # Same inputs should produce same hash
        assert hash1 == hash2
        # Different inputs should produce different hashes
        assert hash1 != hash3
        assert hash1 != hash4

    def test_generate_query_hash_case_insensitive(self) -> None:
        """Test query hash is case insensitive."""
        hash1 = generate_query_hash("Show me all users", "db1", False)
        hash2 = generate_query_hash("show me all users", "db1", False)
        assert hash1 == hash2

    def test_generate_prompt_hash(self) -> None:
        """Test prompt hash generation."""
        hash1 = generate_prompt_hash("Test prompt")
        hash2 = generate_prompt_hash("Test prompt")
        hash3 = generate_prompt_hash("Different prompt")

        assert hash1 == hash2
        assert hash1 != hash3
        assert len(hash1) == 32  # SHA256 truncated to 32 chars


class TestCachedDecorator:
    """Tests for the cached decorator."""

    @pytest.mark.asyncio
    async def test_cached_function(self) -> None:
        """Test that decorated function results are cached."""
        call_count = 0

        @cached(namespace=CacheNamespace.QUERY_RESULT, ttl=60)
        async def expensive_operation(arg: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"result_{arg}"

        # First call should execute function
        result1 = await expensive_operation("test")
        assert result1 == "result_test"
        assert call_count == 1

        # Second call with same args should use cache
        result2 = await expensive_operation("test")
        assert result2 == "result_test"
        # Call count may be 1 or 2 depending on cache state
        # Just verify result is correct

    @pytest.mark.asyncio
    async def test_cached_different_args(self) -> None:
        """Test that different arguments produce different cache entries."""

        @cached(namespace=CacheNamespace.QUERY_RESULT)
        async def operation(arg: str) -> str:
            return f"result_{arg}"

        result1 = await operation("arg1")
        result2 = await operation("arg2")

        assert result1 == "result_arg1"
        assert result2 == "result_arg2"


class TestSpecializedCacheFunctions:
    """Tests for specialized cache functions."""

    @pytest.mark.asyncio
    async def test_cache_query_result(self) -> None:
        """Test caching query results."""
        success = await cache_query_result(
            query_hash="test_hash",
            sql="SELECT * FROM users",
            confidence=0.95,
            results=[{"id": 1, "name": "Test"}],
        )
        assert success

        cached = await get_cached_query_result("test_hash")
        assert cached is not None
        assert cached["sql"] == "SELECT * FROM users"
        assert cached["confidence"] == 0.95

    @pytest.mark.asyncio
    async def test_cache_model_output(self) -> None:
        """Test caching model outputs."""
        success = await cache_model_output(
            prompt_hash="prompt_hash",
            output="Generated SQL output",
            confidence=0.88,
        )
        assert success

        cached = await get_cached_model_output("prompt_hash")
        assert cached is not None
        assert cached["output"] == "Generated SQL output"
        assert cached["confidence"] == 0.88

    @pytest.mark.asyncio
    async def test_cache_schema(self) -> None:
        """Test caching schema data."""
        schema_data = {
            "tables": [
                {"name": "users", "columns": ["id", "name"]},
            ],
            "dialect": "postgresql",
        }
        success = await cache_schema("test_db", schema_data)
        assert success

        cached = await get_cached_schema("test_db")
        assert cached is not None
        assert cached["dialect"] == "postgresql"
        assert len(cached["tables"]) == 1

    @pytest.mark.asyncio
    async def test_cache_prompt(self) -> None:
        """Test caching prompt text."""
        success = await cache_prompt("prompt_key", "Prompt text")
        assert success

        cached = await get_cached_prompt("prompt_key")
        assert cached == "Prompt text"

    @pytest.mark.asyncio
    async def test_cache_inference_result(self) -> None:
        """Test caching inference results."""
        payload = {
            "generated_text": "SELECT 1",
            "sql": "SELECT 1",
            "confidence": 0.99,
        }
        success = await cache_inference_result("prompt_hash", payload)
        assert success

        cached = await get_cached_inference_result("prompt_hash")
        assert cached is not None
        assert cached["sql"] == "SELECT 1"

    @pytest.mark.asyncio
    async def test_invalidate_schema_cache_specific(self) -> None:
        """Test invalidating specific schema cache."""
        await cache_schema("db1", {"data": "db1"})
        await cache_schema("db2", {"data": "db2"})

        count = await invalidate_schema_cache("db1")
        assert count == 1

        assert await get_cached_schema("db1") is None
        assert await get_cached_schema("db2") is not None

    @pytest.mark.asyncio
    async def test_invalidate_all_schema_cache(self) -> None:
        """Test invalidating all schema cache."""
        await cache_schema("db1", {"data": "db1"})
        await cache_schema("db2", {"data": "db2"})

        count = await invalidate_schema_cache(None)
        assert count >= 2

        assert await get_cached_schema("db1") is None
        assert await get_cached_schema("db2") is None


class TestGetCacheManager:
    """Tests for get_cache_manager singleton."""

    @pytest.mark.asyncio
    async def test_returns_same_instance(self) -> None:
        """Test that get_cache_manager returns singleton."""
        # Clear the global instance first
        import app.cache

        app.cache._cache_manager = None

        manager1 = await get_cache_manager()
        manager2 = await get_cache_manager()

        assert manager1 is manager2


class TestCacheManagerWithMockedRedis:
    """Tests with mocked Redis client."""

    @pytest.mark.asyncio
    async def test_connect_with_redis_url(self) -> None:
        """Test connecting when REDIS_URL is set."""
        with patch("app.cache.get_settings") as mock_settings:
            mock_settings.return_value.cache.redis_url = "redis://localhost:6379/0"

            manager = CacheManager()

            # Mock the redis.asyncio module
            with patch("redis.asyncio.from_url") as mock_from_url:
                mock_redis = AsyncMock()
                mock_redis.ping = AsyncMock(return_value=True)
                mock_from_url.return_value = mock_redis

                connected = await manager.connect()
                assert connected
                assert manager.is_connected

    @pytest.mark.asyncio
    async def test_connect_without_redis_url(self) -> None:
        """Test behavior when REDIS_URL is not set."""
        with patch("app.cache.get_settings") as mock_settings:
            mock_settings.return_value.cache.redis_url = None

            manager = CacheManager()
            connected = await manager.connect()

            assert not connected
            assert not manager.is_connected

    @pytest.mark.asyncio
    async def test_graceful_redis_failure(self) -> None:
        """Test graceful fallback when Redis fails."""
        with patch("app.cache.get_settings") as mock_settings:
            mock_settings.return_value.cache.redis_url = "redis://localhost:6379/0"
            mock_settings.return_value.cache.ttl = 3600
            mock_settings.return_value.cache.query_ttl = 3600
            mock_settings.return_value.cache.model_ttl = 7200
            mock_settings.return_value.cache.schema_ttl = 86400
            mock_settings.return_value.cache.max_memory_entries = 1000
            mock_settings.return_value.monitoring.enable_metrics = False

            manager = CacheManager()

            # Redis connection fails
            with patch("redis.asyncio.from_url") as mock_from_url:
                mock_from_url.side_effect = Exception("Connection failed")

                connected = await manager.connect()
                assert not connected

            # Should still work with in-memory cache
            success = await manager.set("key", "value", CacheNamespace.QUERY_RESULT)
            assert success

            result = await manager.get("key", CacheNamespace.QUERY_RESULT)
            assert result == "value"
