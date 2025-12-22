"""
Database connection and schema management utilities.

This package provides database infrastructure:
- connection: Async database connection management with pooling
- schema: Schema introspection and serialization for prompts
- executor: Safe SQL query execution with validation and retry
- migrations: Alembic-based database schema migrations
- registry: Multi-database registry for managing multiple connections (Issue #14)
- dialects: SQL dialect adapters for different database engines (Issue #14)

Usage:
    from db import get_database, close_database, SchemaIntrospector

    # Initialize database
    db_manager = await get_database()

    # Check health
    is_healthy = await db_manager.health_check()

    # Introspect schema
    introspector = SchemaIntrospector(db_manager.engine)
    schema = await introspector.get_schema("my_database")

    # Execute queries safely
    async with db_manager.session() as session:
        executor = SafeQueryExecutor(session)
        result = await executor.execute("SELECT * FROM users WHERE id = :id", {"id": 1})

    # Cleanup
    await close_database()

    # Multi-database support (Issue #14)
    from db import get_database_registry, DatabaseConfig, SQLDialect

    registry = await get_database_registry()
    await registry.register_database(DatabaseConfig(
        database_id="analytics",
        connection_string="postgresql://...",
    ))
    async with registry.session("analytics") as session:
        # Query analytics database
        pass
"""

from db.connection import DatabaseManager, close_database, get_database
from db.dialects import (
    DialectAdapter,
    LimitOffset,
    MariaDBAdapter,
    MySQLAdapter,
    PostgreSQLAdapter,
    SQLDialect,
    SQLiteAdapter,
    SQLServerAdapter,
    convert_url_to_async,
    get_async_driver,
    get_dialect_adapter,
)
from db.examples import (
    ExampleRecord,
    ExampleSearchResult,
    ExampleStore,
    get_example_store,
    reset_example_store,
)
from db.executor import (
    QueryResult,
    QueryValidator,
    SafeQueryExecutor,
    sanitize_identifier,
)
from db.feedback import (
    FeedbackRecord,
    FeedbackStatus,
    FeedbackStore,
    get_feedback_store,
    reset_feedback_store,
)
from db.registry import (
    DatabaseConfig,
    DatabaseHealth,
    DatabaseRegistry,
    DatabaseStatus,
    RegisteredDatabase,
    close_database_registry,
    get_database_registry,
    reset_database_registry,
)
from db.schema import (
    ColumnInfo,
    ForeignKeyInfo,
    SchemaInfo,
    SchemaIntrospector,
    TableInfo,
    get_sample_data,
)

__all__ = [
    # Connection management
    "DatabaseManager",
    "get_database",
    "close_database",
    # Schema introspection
    "SchemaInfo",
    "SchemaIntrospector",
    "TableInfo",
    "ColumnInfo",
    "ForeignKeyInfo",
    "get_sample_data",
    # Few-shot examples (Issue #16)
    "ExampleStore",
    "ExampleRecord",
    "ExampleSearchResult",
    "get_example_store",
    "reset_example_store",
    # Feedback store (Issue #16)
    "FeedbackStore",
    "FeedbackRecord",
    "FeedbackStatus",
    "get_feedback_store",
    "reset_feedback_store",
    # Query execution
    "SafeQueryExecutor",
    "QueryResult",
    "QueryValidator",
    "sanitize_identifier",
    # Multi-database registry (Issue #14)
    "DatabaseRegistry",
    "DatabaseConfig",
    "DatabaseHealth",
    "DatabaseStatus",
    "RegisteredDatabase",
    "get_database_registry",
    "close_database_registry",
    "reset_database_registry",
    # SQL dialects (Issue #14)
    "SQLDialect",
    "DialectAdapter",
    "PostgreSQLAdapter",
    "MySQLAdapter",
    "SQLiteAdapter",
    "SQLServerAdapter",
    "MariaDBAdapter",
    "LimitOffset",
    "get_dialect_adapter",
    "get_async_driver",
    "convert_url_to_async",
]
