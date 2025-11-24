"""
Unit tests for database connection management.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.exceptions import DatabaseConnectionException
from db.connection import (
    DatabaseManager,
    _get_async_url,
    get_database,
    close_database,
)


class TestGetAsyncUrl:
    """Tests for _get_async_url helper function."""

    def test_postgresql_conversion(self) -> None:
        """Test PostgreSQL URL conversion to asyncpg."""
        url = "postgresql://user:pass@localhost/db"
        result = _get_async_url(url)
        assert result == "postgresql+asyncpg://user:pass@localhost/db"

    def test_mysql_conversion(self) -> None:
        """Test MySQL URL conversion to aiomysql."""
        url = "mysql://user:pass@localhost/db"
        result = _get_async_url(url)
        assert result == "mysql+aiomysql://user:pass@localhost/db"

    def test_sqlite_conversion(self) -> None:
        """Test SQLite URL conversion to aiosqlite."""
        url = "sqlite:///./data/test.db"
        result = _get_async_url(url)
        assert result == "sqlite+aiosqlite:///./data/test.db"

    def test_already_async_url(self) -> None:
        """Test URL that already has async driver."""
        url = "postgresql+asyncpg://user:pass@localhost/db"
        result = _get_async_url(url)
        assert result == url

    def test_unknown_dialect(self) -> None:
        """Test unknown database dialect."""
        url = "oracle://user:pass@localhost/db"
        result = _get_async_url(url)
        assert result == url


class TestDatabaseManager:
    """Tests for DatabaseManager class."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.database.url = "sqlite:///./test.db"
        settings.database.pool_size = 5
        settings.database.max_overflow = 10
        settings.database.pool_timeout = 30
        return settings

    def test_init_with_defaults(self, mock_settings: MagicMock) -> None:
        """Test initialization with default settings."""
        with patch("db.connection.get_settings", return_value=mock_settings):
            manager = DatabaseManager()

            assert manager._url == "sqlite:///./test.db"
            assert manager._pool_size == 5
            assert manager._is_initialized is False

    def test_init_with_custom_url(self, mock_settings: MagicMock) -> None:
        """Test initialization with custom URL."""
        with patch("db.connection.get_settings", return_value=mock_settings):
            manager = DatabaseManager(url="postgresql://localhost/custom")

            assert manager._url == "postgresql://localhost/custom"

    def test_is_sqlite_property(self, mock_settings: MagicMock) -> None:
        """Test is_sqlite property."""
        with patch("db.connection.get_settings", return_value=mock_settings):
            manager = DatabaseManager(url="sqlite:///test.db")
            assert manager.is_sqlite is True

            manager2 = DatabaseManager(url="postgresql://localhost/db")
            assert manager2.is_sqlite is False

    def test_dialect_property(self, mock_settings: MagicMock) -> None:
        """Test dialect property for different database types."""
        with patch("db.connection.get_settings", return_value=mock_settings):
            # PostgreSQL
            manager = DatabaseManager(url="postgresql://localhost/db")
            assert manager.dialect == "postgresql"

            # MySQL
            manager = DatabaseManager(url="mysql://localhost/db")
            assert manager.dialect == "mysql"

            # SQLite
            manager = DatabaseManager(url="sqlite:///test.db")
            assert manager.dialect == "sqlite"

            # Unknown
            manager = DatabaseManager(url="unknown://localhost/db")
            assert manager.dialect == "unknown"

    @pytest.mark.asyncio
    async def test_initialize_success(self, mock_settings: MagicMock) -> None:
        """Test successful database initialization."""
        with patch("db.connection.get_settings", return_value=mock_settings):
            with patch("db.connection.create_async_engine") as mock_engine:
                mock_engine.return_value = MagicMock(spec=AsyncEngine)

                manager = DatabaseManager(url="sqlite:///test.db")
                await manager.initialize()

                assert manager._is_initialized is True
                assert manager._engine is not None
                mock_engine.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_already_initialized(
        self, mock_settings: MagicMock
    ) -> None:
        """Test that initialize is idempotent."""
        with patch("db.connection.get_settings", return_value=mock_settings):
            with patch("db.connection.create_async_engine") as mock_engine:
                mock_engine.return_value = MagicMock(spec=AsyncEngine)

                manager = DatabaseManager(url="sqlite:///test.db")
                await manager.initialize()
                await manager.initialize()  # Second call should be no-op

                # Should only be called once
                assert mock_engine.call_count == 1

    @pytest.mark.asyncio
    async def test_initialize_failure(self, mock_settings: MagicMock) -> None:
        """Test database initialization failure."""
        with patch("db.connection.get_settings", return_value=mock_settings):
            with patch(
                "db.connection.create_async_engine",
                side_effect=Exception("Connection failed"),
            ):
                manager = DatabaseManager(url="sqlite:///test.db")

                with pytest.raises(DatabaseConnectionException) as exc_info:
                    await manager.initialize()

                assert "Failed to initialize database" in str(exc_info.value.message)
                assert manager._is_initialized is False

    @pytest.mark.asyncio
    async def test_close(self, mock_settings: MagicMock) -> None:
        """Test closing database connection."""
        with patch("db.connection.get_settings", return_value=mock_settings):
            mock_engine = MagicMock(spec=AsyncEngine)
            mock_engine.dispose = AsyncMock()

            manager = DatabaseManager(url="sqlite:///test.db")
            manager._engine = mock_engine
            manager._is_initialized = True

            await manager.close()

            mock_engine.dispose.assert_called_once()
            assert manager._engine is None
            assert manager._is_initialized is False

    @pytest.mark.asyncio
    async def test_session_not_initialized(self, mock_settings: MagicMock) -> None:
        """Test session access when not initialized."""
        with patch("db.connection.get_settings", return_value=mock_settings):
            manager = DatabaseManager(url="sqlite:///test.db")

            with pytest.raises(DatabaseConnectionException) as exc_info:
                async with manager.session():
                    pass

            assert "not initialized" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_engine_property_not_initialized(
        self, mock_settings: MagicMock
    ) -> None:
        """Test engine property access when not initialized."""
        with patch("db.connection.get_settings", return_value=mock_settings):
            manager = DatabaseManager(url="sqlite:///test.db")

            with pytest.raises(DatabaseConnectionException) as exc_info:
                _ = manager.engine

            assert "not initialized" in str(exc_info.value.message)


class TestGlobalDatabaseFunctions:
    """Tests for global database management functions."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.database.url = "sqlite:///./test.db"
        settings.database.pool_size = 5
        settings.database.max_overflow = 10
        settings.database.pool_timeout = 30
        return settings

    @pytest.fixture(autouse=True)
    def reset_global_manager(self) -> None:
        """Reset global database manager between tests."""
        import db.connection

        db.connection._db_manager = None
        yield
        db.connection._db_manager = None

    @pytest.mark.asyncio
    async def test_get_database_creates_manager(self, mock_settings: MagicMock) -> None:
        """Test get_database creates and initializes manager."""
        with patch("db.connection.get_settings", return_value=mock_settings):
            with patch("db.connection.create_async_engine") as mock_engine:
                mock_engine.return_value = MagicMock(spec=AsyncEngine)

                manager = await get_database()

                assert manager is not None
                assert manager._is_initialized is True

    @pytest.mark.asyncio
    async def test_get_database_returns_same_instance(
        self, mock_settings: MagicMock
    ) -> None:
        """Test get_database returns the same instance."""
        with patch("db.connection.get_settings", return_value=mock_settings):
            with patch("db.connection.create_async_engine") as mock_engine:
                mock_engine.return_value = MagicMock(spec=AsyncEngine)

                manager1 = await get_database()
                manager2 = await get_database()

                assert manager1 is manager2

    @pytest.mark.asyncio
    async def test_close_database(self, mock_settings: MagicMock) -> None:
        """Test close_database closes the global manager."""
        with patch("db.connection.get_settings", return_value=mock_settings):
            with patch("db.connection.create_async_engine") as mock_engine:
                mock_engine_instance = MagicMock(spec=AsyncEngine)
                mock_engine_instance.dispose = AsyncMock()
                mock_engine.return_value = mock_engine_instance

                await get_database()
                await close_database()

                import db.connection

                assert db.connection._db_manager is None

    @pytest.mark.asyncio
    async def test_close_database_when_not_initialized(self) -> None:
        """Test close_database when no manager exists."""
        # Should not raise any errors
        await close_database()
