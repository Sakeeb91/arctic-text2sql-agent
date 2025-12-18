"""
Prometheus metrics registry and base metrics (Issue #9).

This module provides the central metrics registry and defines
all application metrics for Prometheus monitoring.
"""

from functools import lru_cache
from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    multiprocess,
    CONTENT_TYPE_LATEST,
)

from app.config import get_settings


class MetricsRegistry:
    """
    Central Prometheus metrics registry.

    Manages all application metrics and provides thread-safe access
    to metric instances.
    """

    def __init__(self) -> None:
        """Initialize the metrics registry."""
        self.settings = get_settings()
        self._registry = CollectorRegistry()
        self._initialized = False

        # Info metric for service metadata
        self.service_info = Info(
            "arctic_text2sql_service",
            "Service information",
            registry=self._registry,
        )

        # Initialize base metrics
        self._init_base_metrics()

    def _init_base_metrics(self) -> None:
        """Initialize all base metrics."""
        # Service uptime
        self.uptime_seconds = Gauge(
            "arctic_text2sql_uptime_seconds",
            "Service uptime in seconds",
            registry=self._registry,
        )

        # Active connections/requests
        self.active_requests = Gauge(
            "arctic_text2sql_active_requests",
            "Number of active requests",
            registry=self._registry,
        )

        # Initialize request metrics
        self._init_request_metrics()

        # Initialize error metrics
        self._init_error_metrics()

        # Initialize model inference metrics
        self._init_model_metrics()

        # Initialize SQL execution metrics
        self._init_sql_metrics()

        self._initialized = True

    def _init_request_metrics(self) -> None:
        """Initialize HTTP request metrics for QPS and latency tracking."""
        # Request counter (QPS)
        self.http_requests_total = Counter(
            "arctic_text2sql_http_requests_total",
            "Total HTTP requests",
            ["method", "endpoint", "status_code"],
            registry=self._registry,
        )

        # Request latency histogram with percentile buckets
        # Buckets: 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 2.5s, 5s, 10s
        self.http_request_duration_seconds = Histogram(
            "arctic_text2sql_http_request_duration_seconds",
            "HTTP request latency in seconds",
            ["method", "endpoint"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=self._registry,
        )

        # Request size histogram
        self.http_request_size_bytes = Histogram(
            "arctic_text2sql_http_request_size_bytes",
            "HTTP request size in bytes",
            ["method", "endpoint"],
            buckets=(100, 500, 1000, 5000, 10000, 50000, 100000, 500000),
            registry=self._registry,
        )

        # Response size histogram
        self.http_response_size_bytes = Histogram(
            "arctic_text2sql_http_response_size_bytes",
            "HTTP response size in bytes",
            ["method", "endpoint"],
            buckets=(100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000),
            registry=self._registry,
        )

        # In-flight requests gauge
        self.http_requests_in_flight = Gauge(
            "arctic_text2sql_http_requests_in_flight",
            "Number of HTTP requests currently being processed",
            ["method", "endpoint"],
            registry=self._registry,
        )

    def _init_error_metrics(self) -> None:
        """Initialize error tracking metrics by type and source."""
        # Total errors counter by type
        self.errors_total = Counter(
            "arctic_text2sql_errors_total",
            "Total errors by type",
            ["error_type", "source", "severity"],
            registry=self._registry,
        )

        # Application exception counter
        self.exceptions_total = Counter(
            "arctic_text2sql_exceptions_total",
            "Total unhandled exceptions",
            ["exception_class", "endpoint"],
            registry=self._registry,
        )

        # Validation error counter
        self.validation_errors_total = Counter(
            "arctic_text2sql_validation_errors_total",
            "Total validation errors",
            ["field", "error_type"],
            registry=self._registry,
        )

        # Authentication/authorization errors
        self.auth_errors_total = Counter(
            "arctic_text2sql_auth_errors_total",
            "Total authentication and authorization errors",
            ["error_type", "endpoint"],
            registry=self._registry,
        )

        # Rate limit errors
        self.rate_limit_errors_total = Counter(
            "arctic_text2sql_rate_limit_errors_total",
            "Total rate limit exceeded errors",
            ["endpoint", "client_ip"],
            registry=self._registry,
        )

        # Circuit breaker state gauge
        self.circuit_breaker_state = Gauge(
            "arctic_text2sql_circuit_breaker_state",
            "Circuit breaker state (0=closed, 1=half-open, 2=open)",
            ["circuit_name"],
            registry=self._registry,
        )

        # Circuit breaker trips counter
        self.circuit_breaker_trips_total = Counter(
            "arctic_text2sql_circuit_breaker_trips_total",
            "Total circuit breaker trips",
            ["circuit_name"],
            registry=self._registry,
        )

    def _init_model_metrics(self) -> None:
        """Initialize model inference metrics."""
        # Model inference counter
        self.model_inferences_total = Counter(
            "arctic_text2sql_model_inferences_total",
            "Total model inference requests",
            ["model_name", "status"],
            registry=self._registry,
        )

        # Model inference latency histogram
        # Buckets optimized for LLM inference: 100ms to 60s
        self.model_inference_duration_seconds = Histogram(
            "arctic_text2sql_model_inference_duration_seconds",
            "Model inference latency in seconds",
            ["model_name"],
            buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 25.0, 60.0),
            registry=self._registry,
        )

        # Token usage counters
        self.model_tokens_total = Counter(
            "arctic_text2sql_model_tokens_total",
            "Total tokens processed",
            ["model_name", "token_type"],  # token_type: input, output
            registry=self._registry,
        )

        # Model confidence histogram
        self.model_confidence_score = Histogram(
            "arctic_text2sql_model_confidence_score",
            "Model confidence score distribution",
            ["model_name"],
            buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
            registry=self._registry,
        )

        # Model memory usage gauge
        self.model_memory_bytes = Gauge(
            "arctic_text2sql_model_memory_bytes",
            "Model memory usage in bytes",
            ["model_name", "memory_type"],  # memory_type: cpu, gpu
            registry=self._registry,
        )

        # Model loading status gauge
        self.model_loaded = Gauge(
            "arctic_text2sql_model_loaded",
            "Whether model is currently loaded (1=loaded, 0=unloaded)",
            ["model_name"],
            registry=self._registry,
        )

        # Agent reasoning steps histogram
        self.agent_reasoning_steps = Histogram(
            "arctic_text2sql_agent_reasoning_steps",
            "Number of reasoning steps per query",
            ["model_name"],
            buckets=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
            registry=self._registry,
        )

        # Self-correction attempts counter
        self.self_correction_attempts_total = Counter(
            "arctic_text2sql_self_correction_attempts_total",
            "Total self-correction attempts",
            ["model_name", "success"],
            registry=self._registry,
        )

    def record_model_inference(
        self,
        model_name: str,
        status: str,
        duration_seconds: float,
        confidence: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """
        Record model inference metrics.

        Args:
            model_name: Name of the model used
            status: Inference status ('success', 'failure', 'timeout')
            duration_seconds: Inference duration in seconds
            confidence: Model confidence score (0.0-1.0)
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
        """
        # Increment inference counter
        self.model_inferences_total.labels(
            model_name=model_name,
            status=status,
        ).inc()

        # Record latency
        self.model_inference_duration_seconds.labels(
            model_name=model_name,
        ).observe(duration_seconds)

        # Record confidence
        self.model_confidence_score.labels(
            model_name=model_name,
        ).observe(confidence)

        # Record token counts
        if input_tokens > 0:
            self.model_tokens_total.labels(
                model_name=model_name,
                token_type="input",
            ).inc(input_tokens)

        if output_tokens > 0:
            self.model_tokens_total.labels(
                model_name=model_name,
                token_type="output",
            ).inc(output_tokens)

    def record_reasoning_steps(
        self,
        model_name: str,
        steps: int,
    ) -> None:
        """
        Record agent reasoning step count.

        Args:
            model_name: Name of the model used
            steps: Number of reasoning steps taken
        """
        self.agent_reasoning_steps.labels(model_name=model_name).observe(steps)

    def record_self_correction(
        self,
        model_name: str,
        success: bool,
    ) -> None:
        """
        Record a self-correction attempt.

        Args:
            model_name: Name of the model used
            success: Whether the correction was successful
        """
        self.self_correction_attempts_total.labels(
            model_name=model_name,
            success=str(success).lower(),
        ).inc()

    def set_model_memory(
        self,
        model_name: str,
        cpu_bytes: int,
        gpu_bytes: int = 0,
    ) -> None:
        """
        Set model memory usage.

        Args:
            model_name: Name of the model
            cpu_bytes: CPU memory usage in bytes
            gpu_bytes: GPU memory usage in bytes
        """
        self.model_memory_bytes.labels(
            model_name=model_name,
            memory_type="cpu",
        ).set(cpu_bytes)

        self.model_memory_bytes.labels(
            model_name=model_name,
            memory_type="gpu",
        ).set(gpu_bytes)

    def set_model_loaded_status(
        self,
        model_name: str,
        loaded: bool,
    ) -> None:
        """
        Set model loaded status.

        Args:
            model_name: Name of the model
            loaded: Whether the model is loaded
        """
        self.model_loaded.labels(model_name=model_name).set(1 if loaded else 0)

    def _init_sql_metrics(self) -> None:
        """Initialize SQL execution metrics."""
        # SQL query counter
        self.sql_queries_total = Counter(
            "arctic_text2sql_sql_queries_total",
            "Total SQL queries executed",
            ["database_id", "query_type", "status"],
            registry=self._registry,
        )

        # SQL query latency histogram
        # Buckets: 1ms to 30s for database queries
        self.sql_query_duration_seconds = Histogram(
            "arctic_text2sql_sql_query_duration_seconds",
            "SQL query execution latency in seconds",
            ["database_id", "query_type"],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
            registry=self._registry,
        )

        # SQL rows returned histogram
        self.sql_rows_returned = Histogram(
            "arctic_text2sql_sql_rows_returned",
            "Number of rows returned by SQL queries",
            ["database_id"],
            buckets=(0, 1, 5, 10, 25, 50, 100, 250, 500, 1000, 5000, 10000),
            registry=self._registry,
        )

        # Database connection pool metrics
        self.db_pool_size = Gauge(
            "arctic_text2sql_db_pool_size",
            "Database connection pool size",
            ["database_id"],
            registry=self._registry,
        )

        self.db_pool_checked_out = Gauge(
            "arctic_text2sql_db_pool_checked_out",
            "Database connections currently checked out",
            ["database_id"],
            registry=self._registry,
        )

        self.db_pool_overflow = Gauge(
            "arctic_text2sql_db_pool_overflow",
            "Database connection pool overflow",
            ["database_id"],
            registry=self._registry,
        )

        # SQL validation metrics
        self.sql_validation_total = Counter(
            "arctic_text2sql_sql_validation_total",
            "Total SQL validation requests",
            ["database_id", "valid"],
            registry=self._registry,
        )

        # SQL syntax errors counter
        self.sql_syntax_errors_total = Counter(
            "arctic_text2sql_sql_syntax_errors_total",
            "Total SQL syntax errors detected",
            ["database_id", "error_type"],
            registry=self._registry,
        )

        # Schema introspection metrics
        self.schema_introspection_total = Counter(
            "arctic_text2sql_schema_introspection_total",
            "Total schema introspection requests",
            ["database_id", "status"],
            registry=self._registry,
        )

        self.schema_introspection_duration_seconds = Histogram(
            "arctic_text2sql_schema_introspection_duration_seconds",
            "Schema introspection latency in seconds",
            ["database_id"],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
            registry=self._registry,
        )

    def record_sql_query(
        self,
        database_id: str,
        query_type: str,
        status: str,
        duration_seconds: float,
        rows_returned: int = 0,
    ) -> None:
        """
        Record SQL query execution metrics.

        Args:
            database_id: Database identifier
            query_type: Type of query (SELECT, INSERT, UPDATE, DELETE, etc.)
            status: Query status ('success', 'error', 'timeout')
            duration_seconds: Query execution time in seconds
            rows_returned: Number of rows returned (for SELECT queries)
        """
        # Increment query counter
        self.sql_queries_total.labels(
            database_id=database_id,
            query_type=query_type,
            status=status,
        ).inc()

        # Record latency
        self.sql_query_duration_seconds.labels(
            database_id=database_id,
            query_type=query_type,
        ).observe(duration_seconds)

        # Record rows returned
        if rows_returned > 0:
            self.sql_rows_returned.labels(
                database_id=database_id,
            ).observe(rows_returned)

    def record_sql_validation(
        self,
        database_id: str,
        valid: bool,
    ) -> None:
        """
        Record SQL validation result.

        Args:
            database_id: Database identifier
            valid: Whether the SQL was valid
        """
        self.sql_validation_total.labels(
            database_id=database_id,
            valid=str(valid).lower(),
        ).inc()

    def record_sql_syntax_error(
        self,
        database_id: str,
        error_type: str,
    ) -> None:
        """
        Record a SQL syntax error.

        Args:
            database_id: Database identifier
            error_type: Type of syntax error
        """
        self.sql_syntax_errors_total.labels(
            database_id=database_id,
            error_type=error_type,
        ).inc()

    def record_schema_introspection(
        self,
        database_id: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        """
        Record schema introspection metrics.

        Args:
            database_id: Database identifier
            status: Introspection status ('success', 'error', 'cached')
            duration_seconds: Introspection duration in seconds
        """
        self.schema_introspection_total.labels(
            database_id=database_id,
            status=status,
        ).inc()

        self.schema_introspection_duration_seconds.labels(
            database_id=database_id,
        ).observe(duration_seconds)

    def set_db_pool_metrics(
        self,
        database_id: str,
        pool_size: int,
        checked_out: int,
        overflow: int,
    ) -> None:
        """
        Set database connection pool metrics.

        Args:
            database_id: Database identifier
            pool_size: Total pool size
            checked_out: Connections currently checked out
            overflow: Overflow connections in use
        """
        self.db_pool_size.labels(database_id=database_id).set(pool_size)
        self.db_pool_checked_out.labels(database_id=database_id).set(checked_out)
        self.db_pool_overflow.labels(database_id=database_id).set(overflow)

    def record_error(
        self,
        error_type: str,
        source: str,
        severity: str = "error",
    ) -> None:
        """
        Record an error metric.

        Args:
            error_type: Type of error (e.g., 'validation', 'database', 'model')
            source: Source of error (e.g., module or function name)
            severity: Error severity ('warning', 'error', 'critical')
        """
        self.errors_total.labels(
            error_type=error_type,
            source=source,
            severity=severity,
        ).inc()

    def record_exception(
        self,
        exception_class: str,
        endpoint: str,
    ) -> None:
        """
        Record an unhandled exception.

        Args:
            exception_class: Name of the exception class
            endpoint: Endpoint where exception occurred
        """
        self.exceptions_total.labels(
            exception_class=exception_class,
            endpoint=endpoint,
        ).inc()

    def record_validation_error(
        self,
        field: str,
        error_type: str,
    ) -> None:
        """
        Record a validation error.

        Args:
            field: Field that failed validation
            error_type: Type of validation error
        """
        self.validation_errors_total.labels(
            field=field,
            error_type=error_type,
        ).inc()

    def record_auth_error(
        self,
        error_type: str,
        endpoint: str,
    ) -> None:
        """
        Record an authentication/authorization error.

        Args:
            error_type: Type of auth error ('invalid_token', 'expired', 'unauthorized')
            endpoint: Endpoint where error occurred
        """
        self.auth_errors_total.labels(
            error_type=error_type,
            endpoint=endpoint,
        ).inc()

    def record_rate_limit(
        self,
        endpoint: str,
        client_ip: str = "unknown",
    ) -> None:
        """
        Record a rate limit exceeded event.

        Args:
            endpoint: Endpoint where rate limit was exceeded
            client_ip: Client IP address (can be anonymized)
        """
        self.rate_limit_errors_total.labels(
            endpoint=endpoint,
            client_ip=client_ip,
        ).inc()

    def set_circuit_breaker_state(
        self,
        circuit_name: str,
        state: int,
    ) -> None:
        """
        Set circuit breaker state.

        Args:
            circuit_name: Name of the circuit breaker
            state: State value (0=closed, 1=half-open, 2=open)
        """
        self.circuit_breaker_state.labels(circuit_name=circuit_name).set(state)

    def record_circuit_breaker_trip(
        self,
        circuit_name: str,
    ) -> None:
        """
        Record a circuit breaker trip event.

        Args:
            circuit_name: Name of the circuit breaker
        """
        self.circuit_breaker_trips_total.labels(circuit_name=circuit_name).inc()

    def record_request(
        self,
        method: str,
        endpoint: str,
        status_code: int,
        duration_seconds: float,
        request_size: int = 0,
        response_size: int = 0,
    ) -> None:
        """
        Record HTTP request metrics.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: Request endpoint path
            status_code: HTTP response status code
            duration_seconds: Request duration in seconds
            request_size: Request body size in bytes
            response_size: Response body size in bytes
        """
        # Increment request counter
        self.http_requests_total.labels(
            method=method,
            endpoint=endpoint,
            status_code=str(status_code),
        ).inc()

        # Record latency
        self.http_request_duration_seconds.labels(
            method=method,
            endpoint=endpoint,
        ).observe(duration_seconds)

        # Record request size if available
        if request_size > 0:
            self.http_request_size_bytes.labels(
                method=method,
                endpoint=endpoint,
            ).observe(request_size)

        # Record response size if available
        if response_size > 0:
            self.http_response_size_bytes.labels(
                method=method,
                endpoint=endpoint,
            ).observe(response_size)

    def set_service_info(
        self,
        version: str,
        model_name: str,
        environment: str = "production",
    ) -> None:
        """
        Set service metadata info.

        Args:
            version: Service version
            model_name: Loaded model name
            environment: Deployment environment
        """
        self.service_info.info({
            "version": version,
            "model_name": model_name,
            "environment": environment,
            "service_name": self.settings.monitoring.service_name,
        })

    @property
    def registry(self) -> CollectorRegistry:
        """Get the Prometheus collector registry."""
        return self._registry

    def generate_metrics(self) -> bytes:
        """
        Generate Prometheus metrics output.

        Returns:
            Prometheus text format metrics
        """
        return generate_latest(self._registry)

    @property
    def content_type(self) -> str:
        """Get Prometheus content type for HTTP responses."""
        return CONTENT_TYPE_LATEST

    def get_all_metrics(self) -> dict[str, Any]:
        """
        Get all current metric values as a dictionary.

        Returns:
            Dictionary of metric names to their current values
        """
        metrics: dict[str, Any] = {}

        for metric in self._registry.collect():
            for sample in metric.samples:
                name = sample.name
                labels = sample.labels
                value = sample.value

                if labels:
                    key = f"{name}{{{','.join(f'{k}={v}' for k, v in labels.items())}}}"
                else:
                    key = name

                metrics[key] = value

        return metrics


@lru_cache
def get_metrics_registry() -> MetricsRegistry:
    """
    Get the singleton metrics registry instance.

    Returns:
        MetricsRegistry: The application metrics registry
    """
    return MetricsRegistry()
