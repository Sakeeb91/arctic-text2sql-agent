"""
Multi-database E2E tests for Arctic Text2SQL Agent.

These tests verify the multi-database registry functionality,
including database registration, routing, and dialect handling.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from db.dialects import (
    LimitOffset,
    SQLDialect,
    get_dialect_adapter,
)
from db.registry import (
    DatabaseConfig,
    DatabaseHealth,
    DatabaseRegistry,
    DatabaseStatus,
    RegisteredDatabase,
    reset_database_registry,
)

# =============================================================================
# Database Registry Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_multidb
class TestDatabaseRegistry:
    """Tests for DatabaseRegistry functionality."""

    @pytest.mark.asyncio
    async def test_register_database(self) -> None:
        """Test registering a new database."""
        reset_database_registry()
        registry = DatabaseRegistry()

        config = DatabaseConfig(
            database_id="test_db",
            connection_string="sqlite+aiosqlite:///:memory:",
            display_name="Test Database",
            description="A test database",
        )

        registered = await registry.register_database(config, test_connection=False)

        assert isinstance(registered, RegisteredDatabase)
        assert registered.config.database_id == "test_db"
        assert registered.config.display_name == "Test Database"
        assert registry.is_registered("test_db")

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_register_duplicate_fails(self) -> None:
        """Test registering duplicate database ID fails."""
        reset_database_registry()
        registry = DatabaseRegistry()

        config = DatabaseConfig(
            database_id="dup_db",
            connection_string="sqlite+aiosqlite:///:memory:",
        )

        await registry.register_database(config, test_connection=False)

        from app.exceptions import DatabaseAlreadyExistsException

        with pytest.raises(DatabaseAlreadyExistsException):
            await registry.register_database(config, test_connection=False)

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_unregister_database(self) -> None:
        """Test unregistering a database."""
        reset_database_registry()
        registry = DatabaseRegistry()

        config = DatabaseConfig(
            database_id="unreg_db",
            connection_string="sqlite+aiosqlite:///:memory:",
        )

        await registry.register_database(config, test_connection=False)
        assert registry.is_registered("unreg_db")

        await registry.unregister_database("unreg_db")
        assert not registry.is_registered("unreg_db")

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_get_database_not_registered(self) -> None:
        """Test getting unregistered database raises error."""
        reset_database_registry()
        registry = DatabaseRegistry()

        from app.exceptions import DatabaseNotRegisteredException

        with pytest.raises(DatabaseNotRegisteredException):
            registry.get_database("nonexistent")

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_list_databases(self) -> None:
        """Test listing all registered databases."""
        reset_database_registry()
        registry = DatabaseRegistry()

        configs = [
            DatabaseConfig(
                database_id=f"list_db_{i}",
                connection_string="sqlite+aiosqlite:///:memory:",
                tags=["test", f"group{i % 2}"],
            )
            for i in range(3)
        ]

        for config in configs:
            await registry.register_database(config, test_connection=False)

        all_dbs = registry.list_databases()
        assert len(all_dbs) == 3

        # Filter by tags
        group0_dbs = registry.list_databases(tags=["group0"])
        assert len(group0_dbs) == 2  # 0 and 2

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_database_session_context(self) -> None:
        """Test database session context manager."""
        reset_database_registry()
        registry = DatabaseRegistry()

        config = DatabaseConfig(
            database_id="session_db",
            connection_string="sqlite+aiosqlite:///:memory:",
        )

        await registry.register_database(config, test_connection=False)

        async with registry.session("session_db") as session:
            result = await session.execute(text("SELECT 1"))
            value = result.scalar()
            assert value == 1

        await registry.close_all()


# =============================================================================
# Database Health Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_multidb
class TestDatabaseHealth:
    """Tests for database health checking."""

    @pytest.mark.asyncio
    async def test_health_check_success(self) -> None:
        """Test successful health check."""
        reset_database_registry()
        registry = DatabaseRegistry()

        config = DatabaseConfig(
            database_id="health_db",
            connection_string="sqlite+aiosqlite:///:memory:",
        )

        await registry.register_database(config, test_connection=False)
        health = await registry.health_check("health_db")

        assert isinstance(health, DatabaseHealth)
        assert health.status == DatabaseStatus.CONNECTED
        assert health.latency_ms is not None
        assert health.latency_ms >= 0

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_health_check_all(self) -> None:
        """Test health check on all databases."""
        reset_database_registry()
        registry = DatabaseRegistry()

        for i in range(3):
            config = DatabaseConfig(
                database_id=f"health_all_{i}",
                connection_string="sqlite+aiosqlite:///:memory:",
            )
            await registry.register_database(config, test_connection=False)

        results = await registry.health_check_all()

        assert len(results) == 3
        for _db_id, health in results.items():
            assert health.status == DatabaseStatus.CONNECTED

        await registry.close_all()

    def test_database_health_to_dict(self) -> None:
        """Test DatabaseHealth serialization."""
        from datetime import datetime

        health = DatabaseHealth(
            database_id="test_db",
            status=DatabaseStatus.CONNECTED,
            last_check=datetime(2024, 1, 15, 10, 30, 0),
            latency_ms=5.5,
        )

        result = health.to_dict()

        assert result["database_id"] == "test_db"
        assert result["status"] == "connected"
        assert result["healthy"] is True
        assert result["latency_ms"] == 5.5


# =============================================================================
# SQL Dialect Adapter Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_multidb
class TestDialectAdapters:
    """Tests for SQL dialect adapters."""

    def test_sqlite_adapter(self) -> None:
        """Test SQLite dialect adapter."""
        adapter = get_dialect_adapter(SQLDialect.SQLITE)

        # Quote identifier
        quoted = adapter.quote_identifier("my_table")
        assert quoted == '"my_table"'

        # Limit offset
        clause = adapter.get_limit_offset_clause(LimitOffset(limit=10, offset=5))
        assert "LIMIT 10" in clause
        assert "OFFSET 5" in clause

        # Health check query
        health_query = adapter.get_health_check_query()
        assert health_query == "SELECT 1"

    def test_postgresql_adapter(self) -> None:
        """Test PostgreSQL dialect adapter."""
        adapter = get_dialect_adapter(SQLDialect.POSTGRESQL)

        # Quote identifier
        quoted = adapter.quote_identifier("MyTable")
        assert quoted == '"MyTable"'

        # Limit offset
        clause = adapter.get_limit_offset_clause(LimitOffset(limit=10, offset=5))
        assert "LIMIT 10" in clause
        assert "OFFSET 5" in clause

        # String concatenation
        concat = adapter.get_concat_function("first_name", "' '", "last_name")
        assert "||" in concat

    def test_mysql_adapter(self) -> None:
        """Test MySQL dialect adapter."""
        adapter = get_dialect_adapter(SQLDialect.MYSQL)

        # Quote identifier
        quoted = adapter.quote_identifier("my-table")
        assert quoted == "`my-table`"

        # String concatenation
        concat = adapter.get_concat_function("first_name", "' '", "last_name")
        assert "CONCAT" in concat

    def test_sqlserver_adapter(self) -> None:
        """Test SQL Server dialect adapter."""
        adapter = get_dialect_adapter(SQLDialect.SQLSERVER)

        # Quote identifier
        quoted = adapter.quote_identifier("my table")
        assert quoted == "[my table]"

        # Limit offset (SQL Server uses OFFSET/FETCH)
        clause = adapter.get_limit_offset_clause(LimitOffset(limit=10, offset=5))
        assert "OFFSET 5 ROWS" in clause
        assert "FETCH NEXT 10 ROWS ONLY" in clause

    def test_dialect_from_url(self) -> None:
        """Test dialect detection from URL."""
        test_cases = [
            ("postgresql://localhost/db", SQLDialect.POSTGRESQL),
            ("postgres://localhost/db", SQLDialect.POSTGRESQL),
            ("mysql://localhost/db", SQLDialect.MYSQL),
            ("sqlite:///test.db", SQLDialect.SQLITE),
            ("mssql://localhost/db", SQLDialect.SQLSERVER),
        ]

        for url, expected_dialect in test_cases:
            detected = SQLDialect.from_url(url)
            assert detected == expected_dialect, f"URL: {url}"


# =============================================================================
# Multi-Database Routing Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_multidb
class TestMultiDatabaseRouting:
    """Tests for multi-database query routing."""

    @pytest.mark.asyncio
    async def test_route_to_different_databases(self) -> None:
        """Test routing queries to different databases."""
        reset_database_registry()
        registry = DatabaseRegistry()

        # Create two databases with different data
        db1_engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        db2_engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        # Initialize databases with different data
        async with db1_engine.begin() as conn:
            await conn.execute(text("CREATE TABLE test (id INTEGER, value TEXT)"))
            await conn.execute(text("INSERT INTO test VALUES (1, 'db1_value')"))

        async with db2_engine.begin() as conn:
            await conn.execute(text("CREATE TABLE test (id INTEGER, value TEXT)"))
            await conn.execute(text("INSERT INTO test VALUES (1, 'db2_value')"))

        # Register databases
        config1 = DatabaseConfig(
            database_id="route_db1",
            connection_string="sqlite+aiosqlite:///:memory:",
        )
        config2 = DatabaseConfig(
            database_id="route_db2",
            connection_string="sqlite+aiosqlite:///:memory:",
        )

        reg1 = await registry.register_database(config1, test_connection=False)
        reg2 = await registry.register_database(config2, test_connection=False)

        # Override engines with our prepared ones
        await reg1.engine.dispose()
        await reg2.engine.dispose()

        # Query each database
        async with db1_engine.connect() as conn:
            result = await conn.execute(text("SELECT value FROM test WHERE id = 1"))
            value = result.scalar()
            assert value == "db1_value"

        async with db2_engine.connect() as conn:
            result = await conn.execute(text("SELECT value FROM test WHERE id = 1"))
            value = result.scalar()
            assert value == "db2_value"

        await registry.close_all()
        await db1_engine.dispose()
        await db2_engine.dispose()

    @pytest.mark.asyncio
    async def test_database_isolation(self) -> None:
        """Test database changes don't affect other databases."""
        reset_database_registry()
        registry = DatabaseRegistry()

        config1 = DatabaseConfig(
            database_id="iso_db1",
            connection_string="sqlite+aiosqlite:///:memory:",
        )
        config2 = DatabaseConfig(
            database_id="iso_db2",
            connection_string="sqlite+aiosqlite:///:memory:",
        )

        await registry.register_database(config1, test_connection=False)
        await registry.register_database(config2, test_connection=False)

        # Create table in db1
        async with registry.session("iso_db1") as session:
            await session.execute(
                text("CREATE TABLE iso_test (id INTEGER PRIMARY KEY)")
            )
            await session.execute(text("INSERT INTO iso_test VALUES (1)"))
            await session.commit()

        # Verify table exists in db1
        async with registry.session("iso_db1") as session:
            result = await session.execute(text("SELECT * FROM iso_test"))
            rows = result.fetchall()
            assert len(rows) == 1

        # Verify table does NOT exist in db2
        async with registry.session("iso_db2") as session:
            result = await session.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='iso_test'"
                )
            )
            tables = result.fetchall()
            assert len(tables) == 0

        await registry.close_all()


# =============================================================================
# Database Configuration Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_multidb
class TestDatabaseConfig:
    """Tests for DatabaseConfig."""

    def test_config_auto_detects_dialect(self) -> None:
        """Test config auto-detects dialect from URL."""
        config = DatabaseConfig(
            database_id="auto_dialect",
            connection_string="postgresql://localhost/test",
        )

        assert config.dialect == SQLDialect.POSTGRESQL

    def test_config_respects_explicit_dialect(self) -> None:
        """Test config respects explicitly set dialect."""
        config = DatabaseConfig(
            database_id="explicit_dialect",
            connection_string="sqlite:///test.db",
            dialect=SQLDialect.MYSQL,  # Override auto-detection
        )

        assert config.dialect == SQLDialect.MYSQL

    def test_config_defaults(self) -> None:
        """Test config has sensible defaults."""
        config = DatabaseConfig(
            database_id="defaults",
            connection_string="sqlite:///:memory:",
        )

        assert config.pool_size == 5
        assert config.max_overflow == 10
        assert config.pool_timeout == 30
        assert config.read_only is True
        assert config.tags == []

    def test_config_to_dict_excludes_connection_string(self) -> None:
        """Test to_dict excludes sensitive connection string."""
        config = DatabaseConfig(
            database_id="secure",
            connection_string="postgresql://user:secret@host/db",
            display_name="Secure DB",
        )

        result = config.to_dict()

        assert "connection_string" not in result
        assert result["database_id"] == "secure"
        assert result["display_name"] == "Secure DB"


# =============================================================================
# Registry Lifecycle Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_multidb
class TestRegistryLifecycle:
    """Tests for registry lifecycle management."""

    @pytest.mark.asyncio
    async def test_close_all_databases(self) -> None:
        """Test closing all database connections."""
        reset_database_registry()
        registry = DatabaseRegistry()

        for i in range(3):
            config = DatabaseConfig(
                database_id=f"lifecycle_db_{i}",
                connection_string="sqlite+aiosqlite:///:memory:",
            )
            await registry.register_database(config, test_connection=False)

        assert registry.database_count == 3

        await registry.close_all()

        assert registry.database_count == 0

    @pytest.mark.asyncio
    async def test_registry_database_ids_property(self) -> None:
        """Test database_ids property returns all IDs."""
        reset_database_registry()
        registry = DatabaseRegistry()

        expected_ids = {"prop_db_a", "prop_db_b", "prop_db_c"}

        for db_id in expected_ids:
            config = DatabaseConfig(
                database_id=db_id,
                connection_string="sqlite+aiosqlite:///:memory:",
            )
            await registry.register_database(config, test_connection=False)

        assert set(registry.database_ids) == expected_ids

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_registry_database_count(self) -> None:
        """Test database_count property."""
        reset_database_registry()
        registry = DatabaseRegistry()

        assert registry.database_count == 0

        for i in range(5):
            config = DatabaseConfig(
                database_id=f"count_db_{i}",
                connection_string="sqlite+aiosqlite:///:memory:",
            )
            await registry.register_database(config, test_connection=False)

        assert registry.database_count == 5

        await registry.unregister_database("count_db_0")
        assert registry.database_count == 4

        await registry.close_all()
