"""
Unit tests for database registry (Issue #14: Multi-Database Support).
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.exceptions import (
    DatabaseAlreadyExistsException,
    DatabaseNotRegisteredException,
)
from db.dialects import SQLDialect
from db.registry import (
    DatabaseConfig,
    DatabaseHealth,
    DatabaseRegistry,
    DatabaseStatus,
    get_database_registry,
    reset_database_registry,
)


class TestDatabaseConfig:
    """Tests for DatabaseConfig dataclass."""

    def test_basic_config(self) -> None:
        """Test creating basic config."""
        config = DatabaseConfig(
            database_id="test_db",
            connection_string="postgresql://localhost/test",
        )

        assert config.database_id == "test_db"
        assert config.dialect == SQLDialect.POSTGRESQL
        assert config.display_name == "test_db"
        assert config.read_only is True
        assert config.pool_size == 5

    def test_auto_detect_dialect(self) -> None:
        """Test dialect auto-detection from URL."""
        pg_config = DatabaseConfig(
            database_id="pg",
            connection_string="postgresql://localhost/db",
        )
        assert pg_config.dialect == SQLDialect.POSTGRESQL

        mysql_config = DatabaseConfig(
            database_id="mysql",
            connection_string="mysql://localhost/db",
        )
        assert mysql_config.dialect == SQLDialect.MYSQL

        sqlite_config = DatabaseConfig(
            database_id="sqlite",
            connection_string="sqlite:///./test.db",
        )
        assert sqlite_config.dialect == SQLDialect.SQLITE

    def test_explicit_dialect(self) -> None:
        """Test explicit dialect specification."""
        config = DatabaseConfig(
            database_id="test",
            connection_string="postgresql://localhost/db",
            dialect=SQLDialect.POSTGRESQL,
        )
        assert config.dialect == SQLDialect.POSTGRESQL

    def test_to_dict_excludes_connection_string(self) -> None:
        """Test that to_dict excludes sensitive connection string."""
        config = DatabaseConfig(
            database_id="test",
            connection_string="postgresql://user:secret@localhost/db",
        )
        config_dict = config.to_dict()

        assert "connection_string" not in config_dict
        assert config_dict["database_id"] == "test"

    def test_custom_pool_settings(self) -> None:
        """Test custom pool configuration."""
        config = DatabaseConfig(
            database_id="test",
            connection_string="postgresql://localhost/db",
            pool_size=10,
            max_overflow=20,
            pool_timeout=60,
        )

        assert config.pool_size == 10
        assert config.max_overflow == 20
        assert config.pool_timeout == 60

    def test_tags(self) -> None:
        """Test tags configuration."""
        config = DatabaseConfig(
            database_id="test",
            connection_string="postgresql://localhost/db",
            tags=["analytics", "readonly"],
        )

        assert "analytics" in config.tags
        assert "readonly" in config.tags


class TestDatabaseHealth:
    """Tests for DatabaseHealth dataclass."""

    def test_default_status(self) -> None:
        """Test default health status."""
        health = DatabaseHealth(database_id="test")

        assert health.status == DatabaseStatus.UNKNOWN
        assert health.last_check is None
        assert health.latency_ms is None
        assert health.consecutive_failures == 0

    def test_connected_status(self) -> None:
        """Test connected health status."""
        health = DatabaseHealth(
            database_id="test",
            status=DatabaseStatus.CONNECTED,
            last_check=datetime.now(),
            latency_ms=5.2,
        )

        assert health.status == DatabaseStatus.CONNECTED
        assert health.latency_ms == 5.2

    def test_to_dict_includes_healthy_flag(self) -> None:
        """Test to_dict includes healthy boolean."""
        health = DatabaseHealth(
            database_id="test",
            status=DatabaseStatus.CONNECTED,
        )
        health_dict = health.to_dict()

        assert health_dict["healthy"] is True

        unhealthy = DatabaseHealth(
            database_id="test",
            status=DatabaseStatus.ERROR,
        )
        assert unhealthy.to_dict()["healthy"] is False


class TestDatabaseRegistry:
    """Tests for DatabaseRegistry class."""

    @pytest.fixture
    def registry(self) -> DatabaseRegistry:
        """Create fresh registry for each test."""
        return DatabaseRegistry()

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.database.url = None
        settings.database.pool_size = 5
        settings.database.max_overflow = 10
        settings.database.pool_timeout = 30
        return settings

    def test_init_empty_registry(self, registry: DatabaseRegistry) -> None:
        """Test empty registry initialization."""
        assert registry.database_count == 0
        assert registry.database_ids == []

    def test_is_registered_false(self, registry: DatabaseRegistry) -> None:
        """Test is_registered returns False for unknown database."""
        assert registry.is_registered("unknown") is False

    @pytest.mark.asyncio
    async def test_register_database(self, registry: DatabaseRegistry) -> None:
        """Test registering a database."""
        config = DatabaseConfig(
            database_id="test_sqlite",
            connection_string="sqlite+aiosqlite:///:memory:",
            dialect=SQLDialect.SQLITE,
        )

        registered = await registry.register_database(config, test_connection=False)

        assert registered.config.database_id == "test_sqlite"
        assert registry.is_registered("test_sqlite")
        assert registry.database_count == 1

        # Cleanup
        await registry.close_all()

    @pytest.mark.asyncio
    async def test_register_duplicate_raises_error(
        self, registry: DatabaseRegistry
    ) -> None:
        """Test registering duplicate database ID raises error."""
        config = DatabaseConfig(
            database_id="test_db",
            connection_string="sqlite+aiosqlite:///:memory:",
        )

        await registry.register_database(config, test_connection=False)

        with pytest.raises(DatabaseAlreadyExistsException):
            await registry.register_database(config, test_connection=False)

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_unregister_database(self, registry: DatabaseRegistry) -> None:
        """Test unregistering a database."""
        config = DatabaseConfig(
            database_id="to_remove",
            connection_string="sqlite+aiosqlite:///:memory:",
        )

        await registry.register_database(config, test_connection=False)
        assert registry.is_registered("to_remove")

        await registry.unregister_database("to_remove")
        assert not registry.is_registered("to_remove")

    @pytest.mark.asyncio
    async def test_unregister_unknown_raises_error(
        self, registry: DatabaseRegistry
    ) -> None:
        """Test unregistering unknown database raises error."""
        with pytest.raises(DatabaseNotRegisteredException):
            await registry.unregister_database("unknown")

    @pytest.mark.asyncio
    async def test_get_database(self, registry: DatabaseRegistry) -> None:
        """Test getting registered database."""
        config = DatabaseConfig(
            database_id="my_db",
            connection_string="sqlite+aiosqlite:///:memory:",
        )

        await registry.register_database(config, test_connection=False)

        registered = registry.get_database("my_db")
        assert registered.config.database_id == "my_db"

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_get_database_not_found(self, registry: DatabaseRegistry) -> None:
        """Test getting unknown database raises error."""
        with pytest.raises(DatabaseNotRegisteredException):
            registry.get_database("unknown")

    @pytest.mark.asyncio
    async def test_get_engine(self, registry: DatabaseRegistry) -> None:
        """Test getting engine for database."""
        config = DatabaseConfig(
            database_id="engine_test",
            connection_string="sqlite+aiosqlite:///:memory:",
        )

        await registry.register_database(config, test_connection=False)

        engine = registry.get_engine("engine_test")
        assert engine is not None

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_get_adapter(self, registry: DatabaseRegistry) -> None:
        """Test getting adapter for database."""
        config = DatabaseConfig(
            database_id="adapter_test",
            connection_string="sqlite+aiosqlite:///:memory:",
        )

        await registry.register_database(config, test_connection=False)

        adapter = registry.get_adapter("adapter_test")
        assert adapter.dialect == SQLDialect.SQLITE

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_health_check(self, registry: DatabaseRegistry) -> None:
        """Test health check on database."""
        config = DatabaseConfig(
            database_id="health_test",
            connection_string="sqlite+aiosqlite:///:memory:",
        )

        await registry.register_database(config, test_connection=False)

        health = await registry.health_check("health_test")
        assert health.database_id == "health_test"
        assert health.status == DatabaseStatus.CONNECTED
        assert health.latency_ms is not None

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_health_check_all(self, registry: DatabaseRegistry) -> None:
        """Test health check on all databases."""
        config1 = DatabaseConfig(
            database_id="db1",
            connection_string="sqlite+aiosqlite:///:memory:",
        )
        config2 = DatabaseConfig(
            database_id="db2",
            connection_string="sqlite+aiosqlite:///:memory:",
        )

        await registry.register_database(config1, test_connection=False)
        await registry.register_database(config2, test_connection=False)

        results = await registry.health_check_all()

        assert "db1" in results
        assert "db2" in results
        assert len(results) == 2

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_list_databases(self, registry: DatabaseRegistry) -> None:
        """Test listing databases."""
        config1 = DatabaseConfig(
            database_id="sqlite1",
            connection_string="sqlite+aiosqlite:///:memory:",
            tags=["analytics"],
        )
        config2 = DatabaseConfig(
            database_id="sqlite2",
            connection_string="sqlite+aiosqlite:///:memory:",
            tags=["operations"],
        )

        await registry.register_database(config1, test_connection=False)
        await registry.register_database(config2, test_connection=False)

        # List all
        all_dbs = registry.list_databases()
        assert len(all_dbs) == 2

        # Filter by tag
        analytics_dbs = registry.list_databases(tags=["analytics"])
        assert len(analytics_dbs) == 1
        assert analytics_dbs[0].config.database_id == "sqlite1"

        # Filter by dialect
        sqlite_dbs = registry.list_databases(dialect=SQLDialect.SQLITE)
        assert len(sqlite_dbs) == 2

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_close_all(self, registry: DatabaseRegistry) -> None:
        """Test closing all database connections."""
        config = DatabaseConfig(
            database_id="close_test",
            connection_string="sqlite+aiosqlite:///:memory:",
        )

        await registry.register_database(config, test_connection=False)
        assert registry.database_count == 1

        await registry.close_all()
        assert registry.database_count == 0


class TestGlobalRegistry:
    """Tests for global registry management."""

    @pytest.fixture(autouse=True)
    def reset_global_registry(self) -> None:
        """Reset global registry before each test."""
        reset_database_registry()

    @pytest.mark.asyncio
    async def test_get_database_registry_creates_instance(self) -> None:
        """Test get_database_registry creates singleton."""
        with patch("db.registry.get_settings") as mock_settings:
            mock_settings.return_value.database.url = None
            mock_settings.return_value.database.pool_size = 5
            mock_settings.return_value.database.max_overflow = 10
            mock_settings.return_value.database.pool_timeout = 30

            registry1 = await get_database_registry()
            registry2 = await get_database_registry()

            assert registry1 is registry2

    @pytest.mark.asyncio
    async def test_reset_database_registry(self) -> None:
        """Test resetting global registry."""
        with patch("db.registry.get_settings") as mock_settings:
            mock_settings.return_value.database.url = None
            mock_settings.return_value.database.pool_size = 5
            mock_settings.return_value.database.max_overflow = 10
            mock_settings.return_value.database.pool_timeout = 30

            registry1 = await get_database_registry()
            reset_database_registry()
            registry2 = await get_database_registry()

            assert registry1 is not registry2
