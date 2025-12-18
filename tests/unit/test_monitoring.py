"""
Unit tests for monitoring module (Issue #9).

Tests cover metrics collection, health checks, and tracing functionality.
"""

import pytest


class TestMetricsRegistry:
    """Tests for MetricsRegistry class."""

    def test_metrics_registry_initialization(self):
        """Test that metrics registry initializes correctly."""
        from app.monitoring.metrics import MetricsRegistry

        registry = MetricsRegistry()

        assert registry._initialized is True
        assert registry.registry is not None

    def test_record_request(self):
        """Test recording HTTP request metrics."""
        from app.monitoring.metrics import MetricsRegistry

        registry = MetricsRegistry()

        # Record a request
        registry.record_request(
            method="GET",
            endpoint="/api/v1/query",
            status_code=200,
            duration_seconds=0.5,
            request_size=100,
            response_size=500,
        )

        # Verify metrics were updated (no exception means success)
        metrics = registry.get_all_metrics()
        assert len(metrics) > 0

    def test_record_error(self):
        """Test recording error metrics."""
        from app.monitoring.metrics import MetricsRegistry

        registry = MetricsRegistry()

        registry.record_error(
            error_type="validation",
            source="test_module",
            severity="warning",
        )

        # Verify no exception
        metrics = registry.get_all_metrics()
        assert len(metrics) > 0

    def test_record_model_inference(self):
        """Test recording model inference metrics."""
        from app.monitoring.metrics import MetricsRegistry

        registry = MetricsRegistry()

        registry.record_model_inference(
            model_name="test-model",
            status="success",
            duration_seconds=1.5,
            confidence=0.85,
            input_tokens=100,
            output_tokens=50,
        )

        # Verify no exception
        metrics = registry.get_all_metrics()
        assert len(metrics) > 0

    def test_record_sql_query(self):
        """Test recording SQL query metrics."""
        from app.monitoring.metrics import MetricsRegistry

        registry = MetricsRegistry()

        registry.record_sql_query(
            database_id="test_db",
            query_type="SELECT",
            status="success",
            duration_seconds=0.05,
            rows_returned=10,
        )

        metrics = registry.get_all_metrics()
        assert len(metrics) > 0

    def test_record_cache_hit(self):
        """Test recording cache hit metrics."""
        from app.monitoring.metrics import MetricsRegistry

        registry = MetricsRegistry()

        registry.record_cache_hit(
            namespace="query",
            duration_seconds=0.001,
        )

        metrics = registry.get_all_metrics()
        assert len(metrics) > 0

    def test_record_cache_miss(self):
        """Test recording cache miss metrics."""
        from app.monitoring.metrics import MetricsRegistry

        registry = MetricsRegistry()

        registry.record_cache_miss(
            namespace="query",
            duration_seconds=0.001,
        )

        metrics = registry.get_all_metrics()
        assert len(metrics) > 0

    def test_generate_metrics(self):
        """Test Prometheus metrics generation."""
        from app.monitoring.metrics import MetricsRegistry

        registry = MetricsRegistry()

        # Generate metrics output
        output = registry.generate_metrics()

        assert isinstance(output, bytes)
        assert len(output) > 0

    def test_set_service_info(self):
        """Test setting service info metric."""
        from app.monitoring.metrics import MetricsRegistry

        registry = MetricsRegistry()

        registry.set_service_info(
            version="1.0.0",
            model_name="test-model",
            environment="test",
        )

        # Verify no exception
        metrics = registry.get_all_metrics()
        assert len(metrics) > 0


class TestTracingManager:
    """Tests for TracingManager class."""

    def test_tracing_manager_initialization(self):
        """Test that tracing manager initializes correctly."""
        from app.monitoring.tracing import TracingManager

        manager = TracingManager()

        assert manager._initialized is False
        assert manager._tracer is None

    def test_tracing_disabled_by_default_without_init(self):
        """Test that tracing is disabled without initialization."""
        from app.monitoring.tracing import TracingManager

        manager = TracingManager()

        assert manager.is_enabled is False

    def test_create_span_returns_noop_when_disabled(self):
        """Test that create_span returns NoOpSpan when disabled."""
        from app.monitoring.tracing import NoOpSpan, TracingManager

        manager = TracingManager()

        span = manager.create_span("test_span")

        assert isinstance(span, NoOpSpan)

    def test_noop_span_context_manager(self):
        """Test NoOpSpan context manager."""
        from app.monitoring.tracing import NoOpSpan

        span = NoOpSpan()

        with span as s:
            s.set_attribute("key", "value")
            s.add_event("test_event")

        # No exception means success

    def test_get_current_trace_id_when_disabled(self):
        """Test get_current_trace_id when tracing is disabled."""
        from app.monitoring.tracing import TracingManager

        manager = TracingManager()

        trace_id = manager.get_current_trace_id()

        assert trace_id is None

    def test_trace_function_decorator(self):
        """Test trace_function decorator."""
        from app.monitoring.tracing import trace_function

        @trace_function(name="test_function")
        def my_function():
            return "result"

        result = my_function()

        assert result == "result"

    @pytest.mark.asyncio
    async def test_trace_function_decorator_async(self):
        """Test trace_function decorator with async function."""
        from app.monitoring.tracing import trace_function

        @trace_function(name="test_async_function")
        async def my_async_function():
            return "async_result"

        result = await my_async_function()

        assert result == "async_result"


class TestHealthChecker:
    """Tests for HealthChecker class."""

    @pytest.mark.asyncio
    async def test_check_liveness(self):
        """Test liveness check."""
        from app.monitoring.health import check_liveness

        is_alive = await check_liveness()

        assert is_alive is True

    @pytest.mark.asyncio
    async def test_health_checker_initialization(self):
        """Test health checker initialization."""
        from app.monitoring.health import HealthChecker

        checker = HealthChecker()

        assert checker._check_timeout > 0

    @pytest.mark.asyncio
    async def test_health_status_enum(self):
        """Test HealthStatus enum values."""
        from app.monitoring.health import HealthStatus

        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"

    @pytest.mark.asyncio
    async def test_service_health_to_dict(self):
        """Test ServiceHealth to_dict method."""
        from app.monitoring.health import ComponentHealth, HealthStatus, ServiceHealth

        health = ServiceHealth(
            status=HealthStatus.HEALTHY,
            version="1.0.0",
            uptime_seconds=100.0,
            components=[
                ComponentHealth(
                    name="test",
                    status=HealthStatus.HEALTHY,
                    latency_ms=10.0,
                    message="OK",
                )
            ],
        )

        result = health.to_dict()

        assert result["status"] == "healthy"
        assert result["version"] == "1.0.0"
        assert "test" in result["components"]


class TestDependencyChecks:
    """Tests for dependency health checks."""

    @pytest.mark.asyncio
    async def test_check_tcp_connection_failure(self):
        """Test TCP connection check failure."""
        from app.monitoring.dependencies import check_tcp_connection

        connected, latency = await check_tcp_connection(
            "localhost", 59999, timeout=0.5  # Invalid port
        )

        assert connected is False
        assert latency > 0

    @pytest.mark.asyncio
    async def test_dependency_check_dataclass(self):
        """Test DependencyCheck dataclass."""
        from app.monitoring.dependencies import DependencyCheck, DependencyType

        check = DependencyCheck(
            name="test",
            type=DependencyType.DATABASE,
            healthy=True,
            latency_ms=10.0,
            message="OK",
            details={"key": "value"},
        )

        assert check.name == "test"
        assert check.type == DependencyType.DATABASE
        assert check.healthy is True

    @pytest.mark.asyncio
    async def test_get_dependency_status_summary(self):
        """Test dependency status summary."""
        from app.monitoring.dependencies import (
            DependencyCheck,
            DependencyType,
            get_dependency_status_summary,
        )

        checks = [
            DependencyCheck(
                name="db",
                type=DependencyType.DATABASE,
                healthy=True,
                latency_ms=10.0,
                message="OK",
                details={},
            ),
            DependencyCheck(
                name="cache",
                type=DependencyType.CACHE,
                healthy=False,
                latency_ms=100.0,
                message="Failed",
                details={},
            ),
        ]

        summary = get_dependency_status_summary(checks)

        assert summary["total"] == 2
        assert summary["healthy"] == 1
        assert summary["unhealthy"] == 1
        assert summary["overall_healthy"] is False


class TestLoggingWithTracing:
    """Tests for logging with trace correlation."""

    def test_add_trace_context_without_tracing(self):
        """Test add_trace_context when tracing is not available."""
        import logging

        from app.logging_config import add_trace_context

        logger = logging.getLogger("test")
        event_dict = {"event": "test"}

        result = add_trace_context(logger, "info", event_dict)

        assert "event" in result
        # trace_id may or may not be present depending on context

    def test_add_service_context(self):
        """Test add_service_context processor."""
        import logging

        from app.logging_config import add_service_context

        logger = logging.getLogger("test")
        event_dict = {"event": "test"}

        result = add_service_context(logger, "info", event_dict)

        assert "service" in result
        assert result["service"] == "arctic-text2sql"

    def test_add_request_id(self):
        """Test add_request_id processor."""
        import logging

        from app.logging_config import add_request_id, request_id_context

        # Set request ID
        token = request_id_context.set("test-request-123")

        try:
            logger = logging.getLogger("test")
            event_dict = {"event": "test"}

            result = add_request_id(logger, "info", event_dict)

            assert result.get("request_id") == "test-request-123"
        finally:
            request_id_context.reset(token)
