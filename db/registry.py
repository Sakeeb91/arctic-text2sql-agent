"""
Database registry for multi-database support (Issue #14).

This module provides centralized management of multiple database connections
with support for different dialects, health monitoring, and connection pooling.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from app.config import get_settings
from app.exceptions import (
    DatabaseAlreadyExistsException,
    DatabaseConnectionException,
    DatabaseNotRegisteredException,
    InvalidConnectionStringException,
)
from app.logging_config import get_logger
from db.dialects import (
    DialectAdapter,
    SQLDialect,
    convert_url_to_async,
    get_dialect_adapter,
)
from db.schema import SchemaInfo

logger = get_logger(__name__)


class DatabaseStatus(str, Enum):
    """Database connection status."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class DatabaseConfig:
    """
    Configuration for a registered database.

    Attributes:
        database_id: Unique identifier for this database
        connection_string: Database connection URL
        dialect: SQL dialect (auto-detected if not provided)
        display_name: Human-readable name for the database
        description: Optional description
        pool_size: Connection pool size
        max_overflow: Maximum overflow connections
        pool_timeout: Connection timeout in seconds
        read_only: Whether to restrict to read-only queries
        tags: Optional tags for categorization
    """

    database_id: str
    connection_string: str
    dialect: SQLDialect | None = None
    display_name: str | None = None
    description: str | None = None
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30
    read_only: bool = True
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Auto-detect dialect if not provided."""
        if self.dialect is None:
            self.dialect = SQLDialect.from_url(self.connection_string)
        if self.display_name is None:
            self.display_name = self.database_id

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary (excludes connection string for security)."""
        return {
            "database_id": self.database_id,
            "dialect": self.dialect.value if self.dialect else None,
            "display_name": self.display_name,
            "description": self.description,
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "pool_timeout": self.pool_timeout,
            "read_only": self.read_only,
            "tags": self.tags,
        }


@dataclass
class DatabaseHealth:
    """
    Health status of a registered database.

    Attributes:
        database_id: Database identifier
        status: Current connection status
        last_check: Timestamp of last health check
        latency_ms: Response time in milliseconds
        error_message: Error message if unhealthy
        pool_size: Current pool size
        connections_in_use: Active connections
        consecutive_failures: Number of consecutive health check failures
    """

    database_id: str
    status: DatabaseStatus = DatabaseStatus.UNKNOWN
    last_check: datetime | None = None
    latency_ms: float | None = None
    error_message: str | None = None
    pool_size: int = 0
    connections_in_use: int = 0
    consecutive_failures: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "database_id": self.database_id,
            "status": self.status.value,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "latency_ms": self.latency_ms,
            "error_message": self.error_message,
            "pool_size": self.pool_size,
            "connections_in_use": self.connections_in_use,
            "consecutive_failures": self.consecutive_failures,
            "healthy": self.status == DatabaseStatus.CONNECTED,
        }


@dataclass
class RegisteredDatabase:
    """
    A registered database with its connection resources.

    Attributes:
        config: Database configuration
        engine: SQLAlchemy async engine
        session_factory: Session factory for this database
        adapter: Dialect adapter for SQL generation
        health: Current health status
        registered_at: When the database was registered
    """

    config: DatabaseConfig
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    adapter: DialectAdapter
    health: DatabaseHealth
    schema: SchemaInfo | None = None
    schema_updated_at: datetime | None = None
    registered_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        schema_metadata = None
        if self.schema:
            schema_metadata = {
                "table_count": len(self.schema.tables),
                "last_updated": self.schema.last_updated.isoformat(),
            }
        return {
            **self.config.to_dict(),
            "registered_at": self.registered_at.isoformat(),
            "health": self.health.to_dict(),
            "schema": schema_metadata,
        }


class DatabaseRegistry:
    """
    Central registry for managing multiple database connections.

    Provides:
    - Database registration and connection management
    - Health monitoring for all registered databases
    - Connection pooling per database
    - Dialect-specific SQL adapters

    Usage:
        registry = DatabaseRegistry()
        await registry.register_database(DatabaseConfig(
            database_id="analytics",
            connection_string="postgresql://...",
        ))

        async with registry.session("analytics") as session:
            result = await session.execute(text("SELECT 1"))

        health = await registry.health_check("analytics")
    """

    def __init__(self) -> None:
        """Initialize the database registry."""
        self._databases: dict[str, RegisteredDatabase] = {}
        self._lock = asyncio.Lock()
        self._health_check_interval: int = 30
        self._background_tasks: list[asyncio.Task[None]] = []

        logger.info("database_registry_initialized")

    @property
    def database_ids(self) -> list[str]:
        """Return list of registered database IDs."""
        return list(self._databases.keys())

    @property
    def database_count(self) -> int:
        """Return number of registered databases."""
        return len(self._databases)

    def is_registered(self, database_id: str) -> bool:
        """Check if a database is registered."""
        return database_id in self._databases

    async def register_database(
        self,
        config: DatabaseConfig,
        test_connection: bool = True,
    ) -> RegisteredDatabase:
        """
        Register a new database with the registry.

        Args:
            config: Database configuration
            test_connection: Whether to test the connection before registering

        Returns:
            RegisteredDatabase instance

        Raises:
            DatabaseAlreadyExistsException: If database ID already registered
            DatabaseConnectionException: If connection test fails
            InvalidConnectionStringException: If connection string is invalid
        """
        async with self._lock:
            if config.database_id in self._databases:
                raise DatabaseAlreadyExistsException(config.database_id)

            logger.info(
                "registering_database",
                database_id=config.database_id,
                dialect=config.dialect.value if config.dialect else "unknown",
            )

            try:
                # Validate and convert connection string
                async_url = convert_url_to_async(config.connection_string)

                # Get dialect adapter
                adapter = get_dialect_adapter(config.dialect or SQLDialect.POSTGRESQL)

                # Create engine with appropriate settings
                engine_kwargs = self._get_engine_kwargs(config, async_url)
                engine = create_async_engine(async_url, **engine_kwargs)

                # Create session factory
                session_factory = async_sessionmaker(
                    bind=engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                    autocommit=False,
                    autoflush=False,
                )

                # Initialize health status
                health = DatabaseHealth(
                    database_id=config.database_id,
                    status=DatabaseStatus.CONNECTING,
                )

                # Test connection if requested
                if test_connection:
                    try:
                        health = await self._perform_health_check(
                            config.database_id, engine, adapter
                        )
                        if health.status != DatabaseStatus.CONNECTED:
                            raise DatabaseConnectionException(
                                message=f"Connection test failed: {health.error_message}",
                                details={"database_id": config.database_id},
                            )
                    except Exception as e:
                        await engine.dispose()
                        raise DatabaseConnectionException(
                            message=f"Failed to connect: {e}",
                            details={"database_id": config.database_id},
                        ) from e

                # Create registered database entry
                registered = RegisteredDatabase(
                    config=config,
                    engine=engine,
                    session_factory=session_factory,
                    adapter=adapter,
                    health=health,
                )

                self._databases[config.database_id] = registered

                logger.info(
                    "database_registered",
                    database_id=config.database_id,
                    dialect=config.dialect.value if config.dialect else "unknown",
                    pool_size=config.pool_size,
                )

                return registered

            except (
                DatabaseAlreadyExistsException,
                DatabaseConnectionException,
            ):
                raise
            except Exception as e:
                logger.error(
                    "database_registration_failed",
                    database_id=config.database_id,
                    error=str(e),
                )
                raise InvalidConnectionStringException(
                    message=f"Failed to create database connection: {e}",
                    details={"database_id": config.database_id},
                ) from e

    async def unregister_database(self, database_id: str) -> None:
        """
        Unregister and close a database connection.

        Args:
            database_id: ID of database to unregister

        Raises:
            DatabaseNotRegisteredException: If database not found
        """
        async with self._lock:
            if database_id not in self._databases:
                raise DatabaseNotRegisteredException(database_id)

            registered = self._databases[database_id]

            logger.info("unregistering_database", database_id=database_id)

            # Close the engine
            await registered.engine.dispose()

            # Remove from registry
            del self._databases[database_id]

            logger.info("database_unregistered", database_id=database_id)

    def get_database(self, database_id: str) -> RegisteredDatabase:
        """
        Get a registered database by ID.

        Args:
            database_id: Database identifier

        Returns:
            RegisteredDatabase instance

        Raises:
            DatabaseNotRegisteredException: If database not found
        """
        if database_id not in self._databases:
            raise DatabaseNotRegisteredException(database_id)
        return self._databases[database_id]

    def get_engine(self, database_id: str) -> AsyncEngine:
        """
        Get the SQLAlchemy engine for a database.

        Args:
            database_id: Database identifier

        Returns:
            AsyncEngine instance

        Raises:
            DatabaseNotRegisteredException: If database not found
        """
        return self.get_database(database_id).engine

    def get_adapter(self, database_id: str) -> DialectAdapter:
        """
        Get the dialect adapter for a database.

        Args:
            database_id: Database identifier

        Returns:
            DialectAdapter instance

        Raises:
            DatabaseNotRegisteredException: If database not found
        """
        return self.get_database(database_id).adapter

    def update_schema(self, database_id: str, schema: SchemaInfo) -> None:
        """
        Store schema metadata for a registered database.

        Args:
            database_id: Database identifier
            schema: Extracted schema information
        """
        registered = self.get_database(database_id)
        registered.schema = schema
        registered.schema_updated_at = schema.last_updated

    @asynccontextmanager
    async def session(self, database_id: str) -> AsyncGenerator[AsyncSession, None]:
        """
        Get a database session context manager.

        Args:
            database_id: Database identifier

        Yields:
            AsyncSession for the specified database

        Raises:
            DatabaseNotRegisteredException: If database not found
        """
        registered = self.get_database(database_id)
        session = registered.session_factory()

        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(
                "database_session_error",
                database_id=database_id,
                error=str(e),
            )
            raise
        finally:
            await session.close()

    async def health_check(self, database_id: str) -> DatabaseHealth:
        """
        Perform health check on a specific database.

        Args:
            database_id: Database identifier

        Returns:
            DatabaseHealth status

        Raises:
            DatabaseNotRegisteredException: If database not found
        """
        registered = self.get_database(database_id)
        health = await self._perform_health_check(
            database_id,
            registered.engine,
            registered.adapter,
        )
        registered.health = health
        return health

    async def health_check_all(self) -> dict[str, DatabaseHealth]:
        """
        Perform health checks on all registered databases.

        Returns:
            Dictionary mapping database_id to DatabaseHealth
        """
        results: dict[str, DatabaseHealth] = {}

        for database_id in self._databases:
            try:
                results[database_id] = await self.health_check(database_id)
            except Exception as e:
                results[database_id] = DatabaseHealth(
                    database_id=database_id,
                    status=DatabaseStatus.ERROR,
                    last_check=datetime.now(),
                    error_message=str(e),
                )

        return results

    def list_databases(
        self,
        dialect: SQLDialect | None = None,
        tags: list[str] | None = None,
        healthy_only: bool = False,
    ) -> list[RegisteredDatabase]:
        """
        List registered databases with optional filtering.

        Args:
            dialect: Filter by dialect
            tags: Filter by tags (any match)
            healthy_only: Only return healthy databases

        Returns:
            List of RegisteredDatabase matching filters
        """
        results: list[RegisteredDatabase] = []

        for registered in self._databases.values():
            # Apply dialect filter
            if dialect and registered.config.dialect != dialect:
                continue

            # Apply tags filter
            if tags and not any(tag in registered.config.tags for tag in tags):
                continue

            # Apply health filter
            if healthy_only and registered.health.status != DatabaseStatus.CONNECTED:
                continue

            results.append(registered)

        return results

    async def close_all(self) -> None:
        """Close all database connections."""
        logger.info("closing_all_databases", count=len(self._databases))

        for database_id in list(self._databases.keys()):
            try:
                await self.unregister_database(database_id)
            except Exception as e:
                logger.error(
                    "database_close_error",
                    database_id=database_id,
                    error=str(e),
                )

        logger.info("all_databases_closed")

    def _get_engine_kwargs(
        self,
        config: DatabaseConfig,
        async_url: str,
    ) -> dict[str, Any]:
        """Get SQLAlchemy engine keyword arguments based on configuration."""
        engine_kwargs: dict[str, Any] = {
            "echo": False,
        }

        # SQLite requires special handling
        if config.dialect == SQLDialect.SQLITE:
            engine_kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in async_url:
                engine_kwargs["poolclass"] = StaticPool
            else:
                engine_kwargs["poolclass"] = NullPool
        else:
            engine_kwargs["pool_size"] = config.pool_size
            engine_kwargs["max_overflow"] = config.max_overflow
            engine_kwargs["pool_timeout"] = config.pool_timeout
            engine_kwargs["pool_pre_ping"] = True

        return engine_kwargs

    async def _perform_health_check(
        self,
        database_id: str,
        engine: AsyncEngine,
        adapter: DialectAdapter,
    ) -> DatabaseHealth:
        """Perform a health check on a database engine."""
        import time

        start_time = time.perf_counter()
        health = DatabaseHealth(
            database_id=database_id,
            last_check=datetime.now(),
        )

        try:
            async with engine.connect() as conn:
                await conn.execute(text(adapter.get_health_check_query()))

            latency_ms = (time.perf_counter() - start_time) * 1000
            health.status = DatabaseStatus.CONNECTED
            health.latency_ms = round(latency_ms, 2)
            health.consecutive_failures = 0

            logger.debug(
                "database_health_check_passed",
                database_id=database_id,
                latency_ms=health.latency_ms,
            )

        except Exception as e:
            health.status = DatabaseStatus.ERROR
            health.error_message = str(e)
            health.consecutive_failures = (
                self._databases[database_id].health.consecutive_failures + 1
                if database_id in self._databases
                else 1
            )

            logger.warning(
                "database_health_check_failed",
                database_id=database_id,
                error=str(e),
                consecutive_failures=health.consecutive_failures,
            )

        return health


# =============================================================================
# Global Registry Management
# =============================================================================


_database_registry: DatabaseRegistry | None = None


async def get_database_registry() -> DatabaseRegistry:
    """
    Get or create the global database registry instance.

    Returns:
        DatabaseRegistry: Global registry instance
    """
    global _database_registry

    if _database_registry is None:
        _database_registry = DatabaseRegistry()

        # Register default database if configured
        settings = get_settings()
        if settings.database.url:
            try:
                await _database_registry.register_database(
                    DatabaseConfig(
                        database_id="default",
                        connection_string=settings.database.url,
                        display_name="Default Database",
                        description="Primary database configured via DATABASE_URL",
                        pool_size=settings.database.pool_size,
                        max_overflow=settings.database.max_overflow,
                        pool_timeout=settings.database.pool_timeout,
                    ),
                    test_connection=False,
                )
                logger.info(
                    "default_database_registered",
                    database_id="default",
                )
            except Exception as e:
                logger.warning(
                    "default_database_registration_failed",
                    error=str(e),
                )

    return _database_registry


async def close_database_registry() -> None:
    """Close the global database registry and all connections."""
    global _database_registry

    if _database_registry:
        await _database_registry.close_all()
        _database_registry = None


def reset_database_registry() -> None:
    """Reset the global database registry instance (for testing)."""
    global _database_registry
    _database_registry = None
