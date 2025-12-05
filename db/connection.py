"""
Database connection management with SQLAlchemy.

This module provides connection pooling, health checks, and
async support for multiple database backends.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.exceptions import DatabaseConnectionException
from app.logging_config import get_logger

logger = get_logger(__name__)


def _get_async_url(url: str) -> str:
    """
    Convert standard database URL to async-compatible URL.

    Args:
        url: Standard database URL

    Returns:
        Async-compatible database URL
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("mysql://"):
        return url.replace("mysql://", "mysql+aiomysql://", 1)
    elif url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return url


class DatabaseManager:
    """
    Manages database connections with connection pooling.

    Supports PostgreSQL, MySQL, and SQLite with async operations.

    Usage:
        db_manager = DatabaseManager()
        await db_manager.initialize()

        async with db_manager.session() as session:
            result = await session.execute(text("SELECT 1"))
    """

    def __init__(
        self,
        url: str | None = None,
        pool_size: int | None = None,
        max_overflow: int | None = None,
        pool_timeout: int | None = None,
    ) -> None:
        """
        Initialize database manager.

        Args:
            url: Database URL (defaults to settings)
            pool_size: Connection pool size (defaults to settings)
            max_overflow: Max overflow connections (defaults to settings)
            pool_timeout: Connection timeout (defaults to settings)
        """
        settings = get_settings()

        self._url = url or settings.database.url
        self._pool_size = pool_size or settings.database.pool_size
        self._max_overflow = max_overflow or settings.database.max_overflow
        self._pool_timeout = pool_timeout or settings.database.pool_timeout

        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        self._is_initialized = False

    @property
    def is_sqlite(self) -> bool:
        """Check if database is SQLite."""
        return self._url.startswith("sqlite")

    @property
    def dialect(self) -> str:
        """Get database dialect name."""
        if self._url.startswith("postgresql"):
            return "postgresql"
        elif self._url.startswith("mysql"):
            return "mysql"
        elif self._url.startswith("sqlite"):
            return "sqlite"
        return "unknown"

    async def initialize(self) -> None:
        """
        Initialize database connection.

        Creates engine and session factory with appropriate settings
        for the database type.
        """
        if self._is_initialized:
            return

        async_url = _get_async_url(self._url)

        engine_kwargs: dict[str, Any] = {
            "echo": False,
        }

        # SQLite requires special handling for async
        if self.is_sqlite:
            engine_kwargs["connect_args"] = {"check_same_thread": False}
            engine_kwargs["poolclass"] = StaticPool
        else:
            engine_kwargs["pool_size"] = self._pool_size
            engine_kwargs["max_overflow"] = self._max_overflow
            engine_kwargs["pool_timeout"] = self._pool_timeout
            engine_kwargs["pool_pre_ping"] = True

        try:
            self._engine = create_async_engine(async_url, **engine_kwargs)
            self._session_factory = async_sessionmaker(
                bind=self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )
            self._is_initialized = True

            logger.info(
                "database_initialized",
                dialect=self.dialect,
                pool_size=self._pool_size if not self.is_sqlite else "static",
            )

        except Exception as e:
            logger.error(
                "database_initialization_failed",
                error=str(e),
                dialect=self.dialect,
            )
            raise DatabaseConnectionException(
                message=f"Failed to initialize database: {e}",
                details={"dialect": self.dialect},
            ) from e

    async def close(self) -> None:
        """Close database connections and cleanup resources."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            self._is_initialized = False
            logger.info("database_closed")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get a database session context manager.

        Yields:
            AsyncSession: Database session

        Raises:
            DatabaseConnectionException: If not initialized
        """
        if not self._is_initialized or not self._session_factory:
            raise DatabaseConnectionException(
                message="Database not initialized. Call initialize() first."
            )

        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error("database_session_error", error=str(e))
            raise
        finally:
            await session.close()

    async def health_check(self) -> bool:
        """
        Check database connection health.

        Returns:
            bool: True if database is healthy
        """
        try:
            async with self.session() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.warning("database_health_check_failed", error=str(e))
            return False

    @property
    def engine(self) -> AsyncEngine:
        """Get the SQLAlchemy async engine."""
        if not self._engine:
            raise DatabaseConnectionException(
                message="Database not initialized. Call initialize() first."
            )
        return self._engine


# Global database manager instance
_db_manager: DatabaseManager | None = None


async def get_database() -> DatabaseManager:
    """
    Get the global database manager instance.

    Initializes the database if not already done.

    Returns:
        DatabaseManager: Global database manager
    """
    global _db_manager

    if _db_manager is None:
        _db_manager = DatabaseManager()
        await _db_manager.initialize()

    return _db_manager


async def close_database() -> None:
    """Close the global database connection."""
    global _db_manager

    if _db_manager:
        await _db_manager.close()
        _db_manager = None
