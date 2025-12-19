"""
Database instrumentation for tracing and metrics (Issue #9).

This module provides instrumentation for SQLAlchemy database
operations to collect traces and metrics.
"""

import time
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.monitoring.metrics import get_metrics_registry
from app.monitoring.tracing import get_tracing_manager


class DatabaseInstrumentor:
    """
    Instrumentor for SQLAlchemy database operations.

    Automatically collects:
    - Query execution traces
    - Query duration metrics
    - Connection pool metrics
    - Error tracking
    """

    def __init__(self, database_id: str = "default") -> None:
        """
        Initialize the database instrumentor.

        Args:
            database_id: Identifier for the database (for metrics labels)
        """
        self.database_id = database_id
        self.metrics = get_metrics_registry()
        self.tracing = get_tracing_manager()
        self._query_start_times: dict[int, float] = {}
        self._instrumented_engines: set[int] = set()

    def instrument(self, engine: Engine) -> None:
        """
        Instrument a SQLAlchemy engine.

        Args:
            engine: The SQLAlchemy engine to instrument
        """
        engine_id = id(engine)
        if engine_id in self._instrumented_engines:
            return

        # Register event listeners
        event.listen(engine, "before_cursor_execute", self._before_cursor_execute)
        event.listen(engine, "after_cursor_execute", self._after_cursor_execute)
        event.listen(engine, "handle_error", self._handle_error)
        event.listen(engine, "checkout", self._on_checkout)
        event.listen(engine, "checkin", self._on_checkin)

        self._instrumented_engines.add(engine_id)

    def uninstrument(self, engine: Engine) -> None:
        """
        Remove instrumentation from a SQLAlchemy engine.

        Args:
            engine: The SQLAlchemy engine to uninstrument
        """
        engine_id = id(engine)
        if engine_id not in self._instrumented_engines:
            return

        # Remove event listeners
        event.remove(engine, "before_cursor_execute", self._before_cursor_execute)
        event.remove(engine, "after_cursor_execute", self._after_cursor_execute)
        event.remove(engine, "handle_error", self._handle_error)
        event.remove(engine, "checkout", self._on_checkout)
        event.remove(engine, "checkin", self._on_checkin)

        self._instrumented_engines.discard(engine_id)

    def _before_cursor_execute(
        self,
        _conn: Any,
        cursor: Any,
        statement: str,
        _parameters: Any,
        context: Any,
        _executemany: bool,
    ) -> None:
        """
        Event handler called before cursor execution.

        Args:
            conn: Database connection
            cursor: Database cursor
            statement: SQL statement
            parameters: Query parameters
            context: Execution context
            executemany: Whether executing many rows
        """
        # Record start time
        context_id = id(context) if context else id(cursor)
        self._query_start_times[context_id] = time.perf_counter()

        # Start trace span
        if self.tracing.is_enabled:
            query_type = self._extract_query_type(statement)
            span_name = f"db.{query_type.lower()}"

            # Truncate statement for span name
            truncated_stmt = (
                statement[:100] + "..." if len(statement) > 100 else statement
            )

            self.tracing.create_span(
                span_name,
                attributes={
                    "db.system": "postgresql",  # or detect from engine
                    "db.statement": truncated_stmt,
                    "db.operation": query_type,
                    "db.database_id": self.database_id,
                },
                kind="client",
            ).__enter__()

    def _after_cursor_execute(
        self,
        _conn: Any,
        cursor: Any,
        statement: str,
        _parameters: Any,
        context: Any,
        _executemany: bool,
    ) -> None:
        """
        Event handler called after cursor execution.

        Args:
            conn: Database connection
            cursor: Database cursor
            statement: SQL statement
            parameters: Query parameters
            context: Execution context
            executemany: Whether executing many rows
        """
        context_id = id(context) if context else id(cursor)
        start_time = self._query_start_times.pop(context_id, None)

        if start_time:
            duration = time.perf_counter() - start_time
            query_type = self._extract_query_type(statement)

            # Record metrics
            rows_returned = cursor.rowcount if cursor.rowcount >= 0 else 0
            self.metrics.record_sql_query(
                database_id=self.database_id,
                query_type=query_type,
                status="success",
                duration_seconds=duration,
                rows_returned=rows_returned,
            )

            # Update trace span
            if self.tracing.is_enabled:
                self.tracing.set_span_attribute("db.rows_affected", rows_returned)

    def _handle_error(self, exception_context: Any) -> None:
        """
        Event handler for database errors.

        Args:
            exception_context: The exception context
        """
        # Get the original exception
        original_exception = exception_context.original_exception

        # Extract query info if available
        statement = getattr(exception_context, "statement", "")
        query_type = self._extract_query_type(statement) if statement else "UNKNOWN"

        # Record error metrics
        self.metrics.record_sql_query(
            database_id=self.database_id,
            query_type=query_type,
            status="error",
            duration_seconds=0,
        )

        # Record error type
        error_type = type(original_exception).__name__
        self.metrics.record_error(
            error_type="database",
            source=error_type,
            severity="error",
        )

        # Record exception in trace
        if self.tracing.is_enabled:
            self.tracing.record_exception(original_exception)

    def _on_checkout(
        self, _dbapi_conn: Any, _connection_record: Any, _connection_proxy: Any
    ) -> None:
        """
        Event handler for connection checkout.

        Args:
            dbapi_conn: DBAPI connection
            connection_record: Connection record
            connection_proxy: Connection proxy
        """
        # Track active connections
        self.tracing.add_event(
            "db.connection.checkout",
            attributes={"db.database_id": self.database_id},
        )

    def _on_checkin(self, _dbapi_conn: Any, _connection_record: Any) -> None:
        """
        Event handler for connection checkin.

        Args:
            dbapi_conn: DBAPI connection
            connection_record: Connection record
        """
        self.tracing.add_event(
            "db.connection.checkin",
            attributes={"db.database_id": self.database_id},
        )

    def _extract_query_type(self, statement: str) -> str:
        """
        Extract the query type from a SQL statement.

        Args:
            statement: The SQL statement

        Returns:
            Query type (SELECT, INSERT, UPDATE, DELETE, etc.)
        """
        statement = statement.strip().upper()

        if statement.startswith("SELECT"):
            return "SELECT"
        elif statement.startswith("INSERT"):
            return "INSERT"
        elif statement.startswith("UPDATE"):
            return "UPDATE"
        elif statement.startswith("DELETE"):
            return "DELETE"
        elif statement.startswith("CREATE"):
            return "CREATE"
        elif statement.startswith("ALTER"):
            return "ALTER"
        elif statement.startswith("DROP"):
            return "DROP"
        elif statement.startswith("BEGIN") or statement.startswith("START"):
            return "TRANSACTION"
        elif statement.startswith("COMMIT"):
            return "COMMIT"
        elif statement.startswith("ROLLBACK"):
            return "ROLLBACK"
        else:
            return "OTHER"

    def update_pool_metrics(self, engine: Engine) -> None:
        """
        Update connection pool metrics from engine.

        Args:
            engine: The SQLAlchemy engine
        """
        pool = engine.pool
        if pool:
            self.metrics.set_db_pool_metrics(
                database_id=self.database_id,
                pool_size=pool.size(),  # type: ignore[attr-defined]
                checked_out=pool.checkedout(),  # type: ignore[attr-defined]
                overflow=pool.overflow(),  # type: ignore[attr-defined]
            )


def setup_db_instrumentation(
    engine: Engine, database_id: str = "default"
) -> DatabaseInstrumentor:
    """
    Setup database instrumentation for a SQLAlchemy engine.

    Args:
        engine: The SQLAlchemy engine to instrument
        database_id: Identifier for the database

    Returns:
        The configured DatabaseInstrumentor
    """
    instrumentor = DatabaseInstrumentor(database_id)
    instrumentor.instrument(engine)
    return instrumentor
