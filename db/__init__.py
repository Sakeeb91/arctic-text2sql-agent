"""
Database connection and schema management utilities.

This package provides database infrastructure:
- connection: Async database connection management with pooling
- schema: Schema introspection and serialization for prompts
- executor: Safe SQL query execution with validation and retry
- migrations: Alembic-based database schema migrations

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
"""

from db.connection import DatabaseManager, close_database, get_database
from db.executor import (
    QueryResult,
    QueryValidator,
    SafeQueryExecutor,
    sanitize_identifier,
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
    # Query execution
    "SafeQueryExecutor",
    "QueryResult",
    "QueryValidator",
    "sanitize_identifier",
]
