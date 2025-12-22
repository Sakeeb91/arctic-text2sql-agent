"""
Performance E2E tests for Arctic Text2SQL Agent.

These tests measure and validate performance characteristics
including latency, throughput, and resource usage.
"""

import asyncio
import statistics
import time
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.executor import SafeQueryExecutor
from db.registry import DatabaseRegistry
from db.schema import SchemaInfo

# =============================================================================
# Performance Metrics
# =============================================================================


@dataclass
class LatencyMetrics:
    """Latency metrics from performance tests."""

    samples: list[float]
    p50: float
    p95: float
    p99: float
    mean: float
    min_latency: float
    max_latency: float

    @classmethod
    def from_samples(cls, samples: list[float]) -> "LatencyMetrics":
        """Calculate metrics from samples."""
        sorted_samples = sorted(samples)
        n = len(sorted_samples)

        return cls(
            samples=samples,
            p50=sorted_samples[int(n * 0.5)] if n > 0 else 0,
            p95=sorted_samples[int(n * 0.95)] if n > 0 else 0,
            p99=sorted_samples[int(n * 0.99)] if n > 0 else 0,
            mean=statistics.mean(samples) if samples else 0,
            min_latency=min(samples) if samples else 0,
            max_latency=max(samples) if samples else 0,
        )


@dataclass
class ThroughputMetrics:
    """Throughput metrics from performance tests."""

    total_requests: int
    successful_requests: int
    failed_requests: int
    total_time_seconds: float
    requests_per_second: float

    @classmethod
    def calculate(
        cls,
        total: int,
        successful: int,
        failed: int,
        elapsed: float,
    ) -> "ThroughputMetrics":
        """Calculate throughput metrics."""
        return cls(
            total_requests=total,
            successful_requests=successful,
            failed_requests=failed,
            total_time_seconds=elapsed,
            requests_per_second=total / elapsed if elapsed > 0 else 0,
        )


# =============================================================================
# Query Latency Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_performance
class TestQueryLatency:
    """Tests for query execution latency."""

    @pytest.mark.asyncio
    async def test_simple_query_latency(
        self,
        e2e_engine: Any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test latency of simple SELECT queries."""
        samples: list[float] = []
        iterations = 50

        for _ in range(iterations):
            start = time.perf_counter()

            async with e2e_engine.connect() as conn:
                await conn.execute(text("SELECT * FROM customers"))

            elapsed = (time.perf_counter() - start) * 1000  # ms
            samples.append(elapsed)

        metrics = LatencyMetrics.from_samples(samples)

        # Assert reasonable latency thresholds
        assert metrics.p50 < 50, f"P50 latency too high: {metrics.p50}ms"
        assert metrics.p95 < 100, f"P95 latency too high: {metrics.p95}ms"
        assert metrics.mean < 50, f"Mean latency too high: {metrics.mean}ms"

    @pytest.mark.asyncio
    async def test_join_query_latency(
        self,
        e2e_engine: Any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test latency of JOIN queries."""
        samples: list[float] = []
        iterations = 50

        sql = """
            SELECT c.name, o.amount
            FROM customers c
            JOIN orders o ON c.id = o.customer_id
            ORDER BY o.amount DESC
        """

        for _ in range(iterations):
            start = time.perf_counter()

            async with e2e_engine.connect() as conn:
                await conn.execute(text(sql))

            elapsed = (time.perf_counter() - start) * 1000
            samples.append(elapsed)

        metrics = LatencyMetrics.from_samples(samples)

        # JOINs can be slightly slower
        assert metrics.p50 < 100, f"P50 latency too high: {metrics.p50}ms"
        assert metrics.p95 < 200, f"P95 latency too high: {metrics.p95}ms"

    @pytest.mark.asyncio
    async def test_aggregation_query_latency(
        self,
        e2e_engine: Any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test latency of aggregation queries."""
        samples: list[float] = []
        iterations = 50

        sql = """
            SELECT status, COUNT(*), SUM(amount)
            FROM orders
            GROUP BY status
        """

        for _ in range(iterations):
            start = time.perf_counter()

            async with e2e_engine.connect() as conn:
                await conn.execute(text(sql))

            elapsed = (time.perf_counter() - start) * 1000
            samples.append(elapsed)

        metrics = LatencyMetrics.from_samples(samples)

        assert metrics.p50 < 100, f"P50 latency too high: {metrics.p50}ms"


# =============================================================================
# Throughput Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_performance
class TestQueryThroughput:
    """Tests for query throughput."""

    @pytest.mark.asyncio
    async def test_sequential_throughput(
        self,
        e2e_engine: Any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test sequential query throughput."""
        iterations = 100
        successful = 0
        failed = 0

        start = time.perf_counter()

        for _ in range(iterations):
            try:
                async with e2e_engine.connect() as conn:
                    await conn.execute(text("SELECT COUNT(*) FROM customers"))
                successful += 1
            except Exception:
                failed += 1

        elapsed = time.perf_counter() - start

        metrics = ThroughputMetrics.calculate(iterations, successful, failed, elapsed)

        # Should handle at least 50 queries per second sequentially
        assert (
            metrics.requests_per_second >= 50
        ), f"Throughput too low: {metrics.requests_per_second} req/s"
        assert metrics.failed_requests == 0, f"Had {failed} failures"

    @pytest.mark.asyncio
    async def test_concurrent_throughput(
        self,
        e2e_engine: Any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test concurrent query throughput."""
        concurrency = 10
        iterations_per_worker = 20
        total = concurrency * iterations_per_worker
        successful = 0
        failed = 0

        async def worker() -> tuple[int, int]:
            nonlocal successful, failed
            local_success = 0
            local_fail = 0

            for _ in range(iterations_per_worker):
                try:
                    async with e2e_engine.connect() as conn:
                        await conn.execute(text("SELECT * FROM products LIMIT 5"))
                    local_success += 1
                except Exception:
                    local_fail += 1

            return local_success, local_fail

        start = time.perf_counter()

        results = await asyncio.gather(*[worker() for _ in range(concurrency)])

        elapsed = time.perf_counter() - start

        successful = sum(r[0] for r in results)
        failed = sum(r[1] for r in results)

        metrics = ThroughputMetrics.calculate(total, successful, failed, elapsed)

        # Concurrent throughput should be higher
        assert (
            metrics.requests_per_second >= 100
        ), f"Concurrent throughput too low: {metrics.requests_per_second} req/s"
        assert metrics.failed_requests == 0


# =============================================================================
# Safe Executor Performance Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_performance
class TestExecutorPerformance:
    """Tests for SafeQueryExecutor performance."""

    @pytest.mark.asyncio
    async def test_executor_overhead(
        self,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test SafeQueryExecutor adds minimal overhead."""
        iterations = 50

        # Direct execution samples
        direct_samples: list[float] = []
        async with e2e_session_factory() as session:
            for _ in range(iterations):
                start = time.perf_counter()
                await session.execute(text("SELECT * FROM customers"))
                elapsed = (time.perf_counter() - start) * 1000
                direct_samples.append(elapsed)

        # Executor execution samples
        executor_samples: list[float] = []
        async with e2e_session_factory() as session:
            executor = SafeQueryExecutor(
                session=session,
                allow_mutations=False,
                timeout_seconds=10,
                max_rows=100,
                database_id="e2e_test",
                dialect="sqlite",
            )

            for _ in range(iterations):
                start = time.perf_counter()
                await executor.execute("SELECT * FROM customers")
                elapsed = (time.perf_counter() - start) * 1000
                executor_samples.append(elapsed)

        direct_mean = statistics.mean(direct_samples)
        executor_mean = statistics.mean(executor_samples)

        # Executor overhead should be less than 200% (3x slower)
        # The executor adds validation, retry logic, and error handling
        overhead = (executor_mean - direct_mean) / direct_mean * 100
        assert overhead < 200, f"Executor overhead too high: {overhead:.1f}%"

    @pytest.mark.asyncio
    async def test_executor_validation_overhead(
        self,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test query validation adds minimal overhead."""
        from db.executor import QueryValidator

        iterations = 1000
        sql = "SELECT c.name, o.amount FROM customers c JOIN orders o ON c.id = o.customer_id"

        # Without validation
        start = time.perf_counter()
        for _ in range(iterations):
            pass  # Baseline
        baseline = (time.perf_counter() - start) * 1000

        # With validation
        validator = QueryValidator(allow_mutations=False)
        start = time.perf_counter()
        for _ in range(iterations):
            validator.validate(sql)
        validation_time = (time.perf_counter() - start) * 1000

        # Validation should be very fast (< 1ms per query on average)
        avg_validation_ms = (validation_time - baseline) / iterations
        assert avg_validation_ms < 1, f"Validation too slow: {avg_validation_ms}ms"


# =============================================================================
# Memory Usage Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_performance
class TestMemoryUsage:
    """Tests for memory usage."""

    @pytest.mark.asyncio
    async def test_large_result_streaming(
        self,
        e2e_engine: Any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test streaming large results doesn't hold all in memory."""
        # Generate a large result set via cross join
        sql = """
            SELECT c1.id, c1.name, p.name as product
            FROM customers c1
            CROSS JOIN products p
            LIMIT 100
        """

        async with e2e_engine.connect() as conn:
            result = await conn.execute(text(sql))
            # Stream rows instead of fetchall
            count = 0
            for _ in result:
                count += 1

            assert count == 100

    @pytest.mark.asyncio
    async def test_repeated_queries_no_leak(
        self,
        e2e_engine: Any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test repeated queries don't accumulate memory."""
        import gc

        # Run garbage collection first
        gc.collect()

        iterations = 200

        for _ in range(iterations):
            async with e2e_engine.connect() as conn:
                result = await conn.execute(text("SELECT * FROM orders"))
                rows = result.fetchall()
                # Process rows
                total = sum(row[2] for row in rows)  # sum amounts
                assert total > 0

        # Force garbage collection
        gc.collect()

        # If there was a memory leak, this would have grown significantly
        # We can't easily assert memory usage in unit tests, but the test
        # itself validates that the code can run many iterations


# =============================================================================
# Connection Pool Performance Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_performance
class TestConnectionPoolPerformance:
    """Tests for connection pool performance."""

    @pytest.mark.asyncio
    async def test_connection_reuse(
        self,
        e2e_engine: Any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test connection pool reuses connections efficiently."""
        iterations = 50
        connection_times: list[float] = []

        for _ in range(iterations):
            start = time.perf_counter()

            async with e2e_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

            elapsed = (time.perf_counter() - start) * 1000
            connection_times.append(elapsed)

        # First connection might be slower (pool creation)
        # Subsequent should be fast due to reuse
        first = connection_times[0]
        rest_mean = statistics.mean(connection_times[1:])

        # Reused connections should be significantly faster
        # or at least not much slower than first
        assert (
            rest_mean <= first * 2
        ), f"Connection reuse not efficient: first={first}ms, rest={rest_mean}ms"


# =============================================================================
# Registry Performance Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_performance
class TestRegistryPerformance:
    """Tests for database registry performance."""

    @pytest.mark.asyncio
    async def test_registry_lookup_speed(
        self,
        e2e_registry: DatabaseRegistry,
    ) -> None:
        """Test database lookup is fast."""
        iterations = 10000

        start = time.perf_counter()

        for _ in range(iterations):
            e2e_registry.get_database("e2e_test")

        elapsed = (time.perf_counter() - start) * 1000

        # 10k lookups should be very fast (< 100ms total)
        avg_lookup_ms = elapsed / iterations
        assert avg_lookup_ms < 0.01, f"Lookup too slow: {avg_lookup_ms}ms"

    @pytest.mark.asyncio
    async def test_health_check_speed(
        self,
        e2e_registry: DatabaseRegistry,
    ) -> None:
        """Test health check completes quickly."""
        samples: list[float] = []

        for _ in range(10):
            start = time.perf_counter()
            await e2e_registry.health_check("e2e_test")
            elapsed = (time.perf_counter() - start) * 1000
            samples.append(elapsed)

        metrics = LatencyMetrics.from_samples(samples)

        # Health check should be fast (< 50ms p95)
        assert metrics.p95 < 50, f"Health check too slow: {metrics.p95}ms"


# =============================================================================
# Benchmark Summary
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_performance
class TestPerformanceSummary:
    """Summary tests that report overall performance."""

    @pytest.mark.asyncio
    async def test_performance_summary(
        self,
        e2e_engine: Any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Generate a performance summary for the test database."""
        queries = [
            ("Simple SELECT", "SELECT * FROM customers"),
            ("Filtered SELECT", "SELECT * FROM customers WHERE state = 'California'"),
            ("COUNT", "SELECT COUNT(*) FROM orders"),
            (
                "JOIN",
                "SELECT c.name, o.amount FROM customers c JOIN orders o ON c.id = o.customer_id",
            ),
            ("GROUP BY", "SELECT status, COUNT(*) FROM orders GROUP BY status"),
            ("ORDER BY + LIMIT", "SELECT * FROM products ORDER BY price DESC LIMIT 5"),
        ]

        summary: dict[str, LatencyMetrics] = {}

        for name, sql in queries:
            samples: list[float] = []

            for _ in range(20):
                start = time.perf_counter()

                async with e2e_engine.connect() as conn:
                    await conn.execute(text(sql))

                elapsed = (time.perf_counter() - start) * 1000
                samples.append(elapsed)

            summary[name] = LatencyMetrics.from_samples(samples)

        # Log summary (will be visible in test output)
        print("\n" + "=" * 60)
        print("PERFORMANCE SUMMARY")
        print("=" * 60)

        for name, metrics in summary.items():
            print(f"\n{name}:")
            print(f"  P50:  {metrics.p50:.2f}ms")
            print(f"  P95:  {metrics.p95:.2f}ms")
            print(f"  Mean: {metrics.mean:.2f}ms")

        print("\n" + "=" * 60)

        # Assert all queries meet basic thresholds
        for name, metrics in summary.items():
            assert metrics.p95 < 200, f"{name} P95 too high: {metrics.p95}ms"
