"""
Integration tests for database operations.

These tests use a real SQLite in-memory database to verify
the full database layer functionality.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from db.connection import DatabaseManager
from db.executor import SafeQueryExecutor
from db.schema import SchemaIntrospector, get_sample_data


@pytest.fixture
async def test_engine() -> AsyncEngine:
    """Create an in-memory SQLite engine for integration tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Create test tables
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(255),
                state VARCHAR(50)
            )
        """
            )
        )

        await conn.execute(
            text(
                """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                amount DECIMAL(10, 2) NOT NULL,
                order_date DATE NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            )
        """
            )
        )

        # Insert test data
        await conn.execute(
            text(
                """
            INSERT INTO customers (name, email, state) VALUES
                ('Alice', 'alice@example.com', 'California'),
                ('Bob', 'bob@example.com', 'New York'),
                ('Charlie', 'charlie@example.com', 'California')
        """
            )
        )

        await conn.execute(
            text(
                """
            INSERT INTO orders (customer_id, amount, order_date) VALUES
                (1, 100.50, '2024-01-15'),
                (1, 200.00, '2024-02-20'),
                (2, 150.75, '2024-01-20'),
                (3, 75.25, '2024-03-01')
        """
            )
        )

    yield engine

    await engine.dispose()


@pytest.fixture
async def test_session(test_engine: AsyncEngine) -> AsyncSession:
    """Create a session from the test engine."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session


class TestDatabaseManagerIntegration:
    """Integration tests for DatabaseManager."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self) -> None:
        """Test complete database manager lifecycle."""
        # Use in-memory SQLite for testing
        manager = DatabaseManager(url="sqlite:///:memory:")

        # Initialize
        await manager.initialize()
        assert manager._is_initialized is True

        # Health check
        is_healthy = await manager.health_check()
        assert is_healthy is True

        # Use session
        async with manager.session() as session:
            result = await session.execute(text("SELECT 1"))
            row = result.fetchone()
            assert row[0] == 1

        # Close
        await manager.close()
        assert manager._is_initialized is False

    @pytest.mark.asyncio
    async def test_session_commit(self) -> None:
        """Test session automatically commits on success."""
        manager = DatabaseManager(url="sqlite:///:memory:")
        await manager.initialize()

        try:
            # Create table
            async with manager.session() as session:
                await session.execute(
                    text("CREATE TABLE test_table (id INTEGER PRIMARY KEY)")
                )

            # Verify table exists in new session
            async with manager.session() as session:
                result = await session.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
                tables = [row[0] for row in result.fetchall()]
                assert "test_table" in tables
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_session_rollback_on_error(self) -> None:
        """Test session rollback on error."""
        manager = DatabaseManager(url="sqlite:///:memory:")
        await manager.initialize()

        try:
            # Create table first
            async with manager.session() as session:
                await session.execute(
                    text(
                        "CREATE TABLE rollback_test (id INTEGER PRIMARY KEY, val TEXT)"
                    )
                )

            # Try to cause an error mid-transaction
            try:
                async with manager.session() as session:
                    await session.execute(
                        text("INSERT INTO rollback_test VALUES (1, 'test')")
                    )
                    # This should fail - invalid SQL
                    await session.execute(text("INVALID SQL SYNTAX"))
            except Exception:
                pass  # Expected

            # Verify the insert was rolled back
            async with manager.session() as session:
                result = await session.execute(
                    text("SELECT COUNT(*) FROM rollback_test")
                )
                count = result.scalar()
                assert count == 0
        finally:
            await manager.close()


class TestSchemaIntrospectorIntegration:
    """Integration tests for SchemaIntrospector."""

    @pytest.mark.asyncio
    async def test_get_schema(self, test_engine: AsyncEngine) -> None:
        """Test schema introspection with real database."""
        introspector = SchemaIntrospector(test_engine)

        schema = await introspector.get_schema("test_db")

        assert schema.database_id == "test_db"
        assert schema.dialect == "sqlite"
        assert len(schema.tables) == 2

        # Check customers table
        customers_table = schema.get_table("customers")
        assert customers_table.name == "customers"
        assert len(customers_table.columns) == 4

        # Verify column details
        column_names = [col.name for col in customers_table.columns]
        assert "id" in column_names
        assert "name" in column_names
        assert "email" in column_names

        # Check orders table
        orders_table = schema.get_table("orders")
        assert orders_table.name == "orders"
        assert len(orders_table.foreign_keys) == 1
        assert orders_table.foreign_keys[0].references_table == "customers"

    @pytest.mark.asyncio
    async def test_get_schema_with_row_counts(self, test_engine: AsyncEngine) -> None:
        """Test schema introspection with row counts."""
        introspector = SchemaIntrospector(test_engine)

        schema = await introspector.get_schema(
            "test_db",
            include_row_counts=True,
            use_cache=False,
        )

        customers_table = schema.get_table("customers")
        assert customers_table.row_count == 3

        orders_table = schema.get_table("orders")
        assert orders_table.row_count == 4

    @pytest.mark.asyncio
    async def test_serialize_for_prompt(self, test_engine: AsyncEngine) -> None:
        """Test schema serialization for prompts."""
        introspector = SchemaIntrospector(test_engine)
        schema = await introspector.get_schema("test_db")

        prompt_text = introspector.serialize_for_prompt(schema)

        # Verify structure
        assert "Database Schema (sqlite):" in prompt_text
        assert "Table: customers" in prompt_text
        assert "Table: orders" in prompt_text

        # Verify column info
        assert "id" in prompt_text
        assert "[PK]" in prompt_text
        assert "VARCHAR" in prompt_text

        # Verify foreign key info
        assert "FK -> customers" in prompt_text

    @pytest.mark.asyncio
    async def test_cache_behavior(self, test_engine: AsyncEngine) -> None:
        """Test schema caching behavior."""
        introspector = SchemaIntrospector(test_engine)

        # First call should populate cache
        schema1 = await introspector.get_schema("test_db")
        assert "test_db" in introspector._cache

        # Second call should use cache
        schema2 = await introspector.get_schema("test_db", use_cache=True)
        assert schema1 is schema2

        # After invalidation, should fetch fresh
        introspector.invalidate_cache("test_db")
        assert "test_db" not in introspector._cache


class TestGetSampleDataIntegration:
    """Integration tests for get_sample_data function."""

    @pytest.mark.asyncio
    async def test_get_sample_data(self, test_engine: AsyncEngine) -> None:
        """Test getting sample data from table."""
        samples = await get_sample_data(test_engine, "customers", limit=2)

        assert len(samples) == 2
        assert "id" in samples[0]
        assert "name" in samples[0]
        assert "email" in samples[0]

    @pytest.mark.asyncio
    async def test_get_sample_data_all_rows(self, test_engine: AsyncEngine) -> None:
        """Test getting all sample data."""
        samples = await get_sample_data(test_engine, "customers", limit=10)

        # Should return all 3 rows
        assert len(samples) == 3

    @pytest.mark.asyncio
    async def test_get_sample_data_nonexistent_table(
        self, test_engine: AsyncEngine
    ) -> None:
        """Test getting sample data from nonexistent table."""
        samples = await get_sample_data(test_engine, "nonexistent_table")

        # Should return empty list on error
        assert samples == []


class TestSafeQueryExecutorIntegration:
    """Integration tests for SafeQueryExecutor."""

    @pytest.mark.asyncio
    async def test_simple_select(self, test_session: AsyncSession) -> None:
        """Test simple SELECT query."""
        executor = SafeQueryExecutor(test_session)

        result = await executor.execute("SELECT * FROM customers")

        assert result.success is True
        assert result.row_count == 3
        assert "id" in result.columns
        assert "name" in result.columns

    @pytest.mark.asyncio
    async def test_select_with_where(self, test_session: AsyncSession) -> None:
        """Test SELECT with WHERE clause."""
        executor = SafeQueryExecutor(test_session)

        result = await executor.execute(
            "SELECT * FROM customers WHERE state = 'California'"
        )

        assert result.success is True
        assert result.row_count == 2

        for row in result.rows:
            assert row["state"] == "California"

    @pytest.mark.asyncio
    async def test_parameterized_query(self, test_session: AsyncSession) -> None:
        """Test query with parameters."""
        executor = SafeQueryExecutor(test_session)

        result = await executor.execute(
            "SELECT * FROM customers WHERE state = :state",
            params={"state": "New York"},
        )

        assert result.success is True
        assert result.row_count == 1
        assert result.rows[0]["name"] == "Bob"

    @pytest.mark.asyncio
    async def test_aggregate_query(self, test_session: AsyncSession) -> None:
        """Test aggregate query."""
        executor = SafeQueryExecutor(test_session)

        result = await executor.execute(
            "SELECT COUNT(*) as customer_count FROM customers"
        )

        assert result.success is True
        assert result.rows[0]["customer_count"] == 3

    @pytest.mark.asyncio
    async def test_join_query(self, test_session: AsyncSession) -> None:
        """Test JOIN query."""
        executor = SafeQueryExecutor(test_session)

        result = await executor.execute(
            """
            SELECT c.name, SUM(o.amount) as total_orders
            FROM customers c
            JOIN orders o ON c.id = o.customer_id
            GROUP BY c.id
            ORDER BY total_orders DESC
        """
        )

        assert result.success is True
        assert result.row_count == 3

        # Alice should have highest total (300.50)
        assert result.rows[0]["name"] == "Alice"
        assert result.rows[0]["total_orders"] == 300.5

    @pytest.mark.asyncio
    async def test_cte_query(self, test_session: AsyncSession) -> None:
        """Test Common Table Expression (CTE) query."""
        executor = SafeQueryExecutor(test_session)

        result = await executor.execute(
            """
            WITH customer_totals AS (
                SELECT customer_id, SUM(amount) as total
                FROM orders
                GROUP BY customer_id
            )
            SELECT c.name, ct.total
            FROM customers c
            JOIN customer_totals ct ON c.id = ct.customer_id
        """
        )

        assert result.success is True
        assert result.row_count == 3

    @pytest.mark.asyncio
    async def test_max_rows_limit(self, test_session: AsyncSession) -> None:
        """Test max rows limit."""
        executor = SafeQueryExecutor(test_session, max_rows=2)

        result = await executor.execute("SELECT * FROM customers")

        assert result.row_count == 2
        assert any("truncated" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_execution_time_recorded(self, test_session: AsyncSession) -> None:
        """Test that execution time is recorded."""
        executor = SafeQueryExecutor(test_session)

        result = await executor.execute("SELECT * FROM customers")

        assert result.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_explain_query(self, test_session: AsyncSession) -> None:
        """Test EXPLAIN query."""
        executor = SafeQueryExecutor(test_session)

        result = await executor.execute_explain("SELECT * FROM customers")

        assert "sql" in result
        assert "plan" in result
        assert len(result["plan"]) > 0


class TestEndToEndDatabaseFlow:
    """End-to-end integration tests for complete database flows."""

    @pytest.mark.asyncio
    async def test_schema_to_query_flow(self, test_engine: AsyncEngine) -> None:
        """Test complete flow from schema introspection to query execution."""
        # Step 1: Introspect schema
        introspector = SchemaIntrospector(test_engine)
        schema = await introspector.get_schema("test_db")

        # Verify schema was retrieved
        assert len(schema.tables) == 2
        customers_table = schema.get_table("customers")
        assert customers_table is not None

        # Step 2: Generate prompt from schema
        prompt = introspector.serialize_for_prompt(schema)
        assert "customers" in prompt
        assert "orders" in prompt

        # Step 3: Execute a query (simulating what model would generate)
        from sqlalchemy.ext.asyncio import async_sessionmaker

        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with session_factory() as session:
            executor = SafeQueryExecutor(session)

            # Query based on schema
            result = await executor.execute(
                "SELECT c.name, COUNT(o.id) as order_count "
                "FROM customers c "
                "LEFT JOIN orders o ON c.id = o.customer_id "
                "GROUP BY c.id"
            )

            assert result.success is True
            assert result.row_count == 3

            # Verify data makes sense
            for row in result.rows:
                assert "name" in row
                assert "order_count" in row
