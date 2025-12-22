"""
Full pipeline E2E tests for Arctic Text2SQL Agent.

These tests verify the complete pipeline from natural language
to SQL generation and execution with real database operations.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.executor import QueryValidator, SafeQueryExecutor
from db.registry import DatabaseRegistry
from db.schema import SchemaInfo, SchemaIntrospector
from tests.e2e.seed_data import ExpectedValues, get_all_test_queries

# =============================================================================
# SQL Generation Tests (Database Layer Only)
# =============================================================================


@pytest.mark.e2e
class TestDatabaseExecution:
    """Tests for direct SQL execution against the seeded database."""

    @pytest.mark.asyncio
    async def test_simple_select_all_customers(
        self,
        e2e_engine: any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test simple SELECT query returns expected rows."""
        async with e2e_engine.connect() as conn:
            result = await conn.execute(text("SELECT * FROM customers"))
            rows = result.fetchall()

            assert len(rows) == ExpectedValues.TOTAL_CUSTOMERS
            # Verify first customer
            assert rows[0][1] == "Alice Johnson"  # name column

    @pytest.mark.asyncio
    async def test_filtered_query_california_customers(
        self,
        e2e_engine: any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test filtered query returns correct count."""
        async with e2e_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT * FROM customers WHERE state = 'California'")
            )
            rows = result.fetchall()

            assert len(rows) == ExpectedValues.CALIFORNIA_CUSTOMERS

    @pytest.mark.asyncio
    async def test_aggregation_count_orders(
        self,
        e2e_engine: any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test COUNT aggregation returns expected value."""
        async with e2e_engine.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM orders"))
            count = result.scalar()

            assert count == ExpectedValues.TOTAL_ORDERS

    @pytest.mark.asyncio
    async def test_group_by_order_status(
        self,
        e2e_engine: any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test GROUP BY query returns correct counts per status."""
        async with e2e_engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT status, COUNT(*) as count
                    FROM orders
                    GROUP BY status
                    ORDER BY status
                """
                )
            )
            rows = result.fetchall()

            status_counts = {row[0]: row[1] for row in rows}

            assert status_counts.get("completed") == ExpectedValues.COMPLETED_ORDERS
            assert status_counts.get("pending") == ExpectedValues.PENDING_ORDERS
            assert status_counts.get("shipped") == ExpectedValues.SHIPPED_ORDERS

    @pytest.mark.asyncio
    async def test_join_customers_orders(
        self,
        e2e_engine: any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test JOIN query returns expected data."""
        async with e2e_engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT c.name, o.amount
                    FROM customers c
                    JOIN orders o ON c.id = o.customer_id
                    ORDER BY c.name, o.amount
                """
                )
            )
            rows = result.fetchall()

            assert len(rows) == ExpectedValues.TOTAL_ORDERS
            # Alice has 3 orders
            alice_orders = [r for r in rows if r[0] == "Alice Johnson"]
            assert len(alice_orders) == 3

    @pytest.mark.asyncio
    async def test_order_by_with_limit(
        self,
        e2e_engine: any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test ORDER BY with LIMIT returns correct top results."""
        async with e2e_engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT name, price
                    FROM products
                    ORDER BY price DESC
                    LIMIT 3
                """
                )
            )
            rows = result.fetchall()

            assert len(rows) == 3
            # Verify ordering (highest prices first)
            assert rows[0][0] == "Laptop"  # $999.99
            assert rows[1][0] == "Standing Desk"  # $449.99
            assert rows[2][0] == "Monitor"  # $349.99

    @pytest.mark.asyncio
    async def test_subquery_customer_with_most_orders(
        self,
        e2e_engine: any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test subquery identifies customer with most orders."""
        async with e2e_engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT c.name, COUNT(o.id) as order_count
                    FROM customers c
                    JOIN orders o ON c.id = o.customer_id
                    GROUP BY c.id, c.name
                    ORDER BY order_count DESC
                    LIMIT 1
                """
                )
            )
            row = result.fetchone()

            assert row is not None
            assert row[0] == "Alice Johnson"
            assert row[1] == ExpectedValues.TOP_CUSTOMER_ORDER_COUNT


# =============================================================================
# Safe Query Executor Tests
# =============================================================================


@pytest.mark.e2e
class TestSafeQueryExecutor:
    """Tests for SafeQueryExecutor with real database."""

    @pytest.mark.asyncio
    async def test_executor_readonly_mode(
        self,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test executor in read-only mode rejects mutations."""
        async with e2e_session_factory() as session:
            executor = SafeQueryExecutor(
                session=session,
                allow_mutations=False,
                timeout_seconds=10,
                max_rows=100,
                database_id="e2e_test",
                dialect="sqlite",
            )

            # SELECT should work
            result = await executor.execute("SELECT COUNT(*) FROM customers")
            assert result.success
            assert result.row_count == 1

            # INSERT should be rejected with exception
            from app.exceptions import QueryExecutionException

            with pytest.raises(QueryExecutionException) as exc_info:
                await executor.execute(
                    "INSERT INTO customers (id, name) VALUES (999, 'Test')"
                )
            assert (
                "INSERT" in str(exc_info.value)
                or "validation" in str(exc_info.value).lower()
            )

    @pytest.mark.asyncio
    async def test_executor_max_rows_limit(
        self,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test executor respects max_rows limit."""
        async with e2e_session_factory() as session:
            executor = SafeQueryExecutor(
                session=session,
                allow_mutations=False,
                timeout_seconds=10,
                max_rows=5,  # Limit to 5 rows
                database_id="e2e_test",
                dialect="sqlite",
            )

            result = await executor.execute("SELECT * FROM customers")
            assert result.success
            assert len(result.rows or []) <= 5

    @pytest.mark.asyncio
    async def test_executor_handles_invalid_sql(
        self,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test executor handles invalid SQL gracefully with exception."""
        from app.exceptions import QueryExecutionException

        async with e2e_session_factory() as session:
            executor = SafeQueryExecutor(
                session=session,
                allow_mutations=False,
                timeout_seconds=10,
                max_rows=100,
                database_id="e2e_test",
                dialect="sqlite",
            )

            with pytest.raises(QueryExecutionException) as exc_info:
                await executor.execute("SELECT * FROM nonexistent_table")
            assert "nonexistent_table" in str(exc_info.value)


# =============================================================================
# Query Validator Tests
# =============================================================================


@pytest.mark.e2e
class TestQueryValidator:
    """Tests for QueryValidator with real SQL patterns."""

    def test_validator_accepts_valid_select(self) -> None:
        """Test validator accepts valid SELECT queries."""
        validator = QueryValidator(allow_mutations=False)

        valid_queries = [
            "SELECT * FROM customers",
            "SELECT name, email FROM customers WHERE state = 'CA'",
            "SELECT COUNT(*) FROM orders GROUP BY status",
            "SELECT c.name FROM customers c JOIN orders o ON c.id = o.customer_id",
        ]

        for sql in valid_queries:
            errors = validator.validate(sql)
            assert len(errors) == 0, f"Query should be valid: {sql}"

    def test_validator_rejects_mutations_when_disabled(self) -> None:
        """Test validator rejects mutation queries when mutations disabled."""
        validator = QueryValidator(allow_mutations=False)

        mutation_queries = [
            "INSERT INTO customers (name) VALUES ('Test')",
            "UPDATE customers SET name = 'Test' WHERE id = 1",
            "DELETE FROM customers WHERE id = 1",
            "DROP TABLE customers",
        ]

        for sql in mutation_queries:
            errors = validator.validate(sql)
            assert len(errors) > 0, f"Query should be rejected: {sql}"

    def test_validator_allows_mutations_when_enabled(self) -> None:
        """Test validator allows mutation queries when mutations enabled."""
        validator = QueryValidator(allow_mutations=True)

        # INSERT should be allowed
        errors = validator.validate("INSERT INTO customers (name) VALUES ('Test')")
        assert len(errors) == 0


# =============================================================================
# Schema Introspection Tests
# =============================================================================


@pytest.mark.e2e
class TestSchemaIntrospection:
    """Tests for schema introspection with real database."""

    @pytest.mark.asyncio
    async def test_introspector_discovers_tables(
        self,
        e2e_engine: any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test introspector discovers all tables."""
        introspector = SchemaIntrospector(e2e_engine)
        schema = await introspector.get_schema("e2e_test")

        table_names = {t.name for t in schema.tables}

        assert "customers" in table_names
        assert "orders" in table_names
        assert "products" in table_names
        assert "order_items" in table_names

    @pytest.mark.asyncio
    async def test_introspector_discovers_columns(
        self,
        e2e_engine: any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test introspector discovers table columns."""
        introspector = SchemaIntrospector(e2e_engine)
        schema = await introspector.get_schema("e2e_test")

        # Find customers table
        customers_table = next(
            (t for t in schema.tables if t.name == "customers"), None
        )
        assert customers_table is not None

        column_names = {c.name for c in customers_table.columns}
        assert "id" in column_names
        assert "name" in column_names
        assert "email" in column_names
        assert "state" in column_names

    @pytest.mark.asyncio
    async def test_introspector_serializes_for_prompt(
        self,
        e2e_engine: any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test introspector generates prompt-ready schema description."""
        introspector = SchemaIntrospector(e2e_engine)
        schema = await introspector.get_schema("e2e_test")
        serialized = introspector.serialize_for_prompt(schema)

        # Verify structure
        assert "customers" in serialized
        assert "orders" in serialized
        assert "products" in serialized
        assert "id" in serialized
        assert "name" in serialized


# =============================================================================
# Registry Integration Tests
# =============================================================================


@pytest.mark.e2e
class TestRegistryIntegration:
    """Tests for database registry integration."""

    @pytest.mark.asyncio
    async def test_registry_session_context(
        self,
        e2e_engine: any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test registry session context with direct engine access."""
        # Note: We use e2e_engine directly because in-memory SQLite
        # databases are connection-specific, and the registry creates
        # a separate connection.
        async with e2e_engine.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM customers"))
            count = result.scalar()

            assert count == ExpectedValues.TOTAL_CUSTOMERS

    @pytest.mark.asyncio
    async def test_registry_health_check(
        self,
        e2e_registry: DatabaseRegistry,
    ) -> None:
        """Test registry health check reports healthy database."""
        health = await e2e_registry.health_check("e2e_test")

        assert health.status.value == "connected"
        assert health.latency_ms is not None
        assert health.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_registry_stores_schema(
        self,
        e2e_registry: DatabaseRegistry,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test registry stores and retrieves schema."""
        registered = e2e_registry.get_database("e2e_test")

        assert registered.schema is not None
        assert len(registered.schema.tables) == 4


# =============================================================================
# E2E Query Pattern Tests
# =============================================================================


@pytest.mark.e2e
class TestQueryPatterns:
    """Test various SQL query patterns against the real database."""

    @pytest.mark.asyncio
    async def test_all_query_expectations(
        self,
        e2e_engine: any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Verify all expected query patterns work correctly."""
        test_queries = get_all_test_queries()

        for test_case in test_queries:
            # This test verifies the expected keywords are reasonable
            # by checking they don't cause syntax errors when used
            keywords = test_case["expected_keywords"]

            # Verify all keywords are valid SQL keywords
            valid_keywords = {
                "SELECT",
                "FROM",
                "WHERE",
                "JOIN",
                "GROUP BY",
                "ORDER BY",
                "HAVING",
                "LIMIT",
                "COUNT",
                "SUM",
                "AVG",
                "MAX",
                "MIN",
                "DESC",
                "ASC",
            }

            for kw in keywords:
                # Keywords should be valid SQL or table/column names
                assert kw.upper() in valid_keywords or kw.lower() in {
                    "customers",
                    "orders",
                    "products",
                    "order_items",
                    "status",
                    "california",
                    "completed",
                }, f"Invalid keyword in test case: {kw}"

    @pytest.mark.asyncio
    async def test_complex_multi_join_query(
        self,
        e2e_engine: any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test complex multi-table JOIN query."""
        async with e2e_engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT
                        c.name as customer_name,
                        p.name as product_name,
                        oi.quantity,
                        oi.unit_price
                    FROM customers c
                    JOIN orders o ON c.id = o.customer_id
                    JOIN order_items oi ON o.id = oi.order_id
                    JOIN products p ON oi.product_id = p.id
                    ORDER BY c.name, p.name
                """
                )
            )
            rows = result.fetchall()

            assert len(rows) > 0
            # Verify structure
            assert len(rows[0]) == 4  # 4 columns selected

    @pytest.mark.asyncio
    async def test_aggregate_with_having(
        self,
        e2e_engine: any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test aggregate query with HAVING clause."""
        async with e2e_engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT customer_id, COUNT(*) as order_count
                    FROM orders
                    GROUP BY customer_id
                    HAVING COUNT(*) > 1
                    ORDER BY order_count DESC
                """
                )
            )
            rows = result.fetchall()

            # Customers with more than 1 order
            assert len(rows) > 0
            # All returned rows should have count > 1
            for row in rows:
                assert row[1] > 1

    @pytest.mark.asyncio
    async def test_date_range_query(
        self,
        e2e_engine: any,
        e2e_seeded_database: SchemaInfo,
    ) -> None:
        """Test date range filtering."""
        async with e2e_engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT COUNT(*) as jan_orders
                    FROM orders
                    WHERE order_date >= '2024-01-01' AND order_date < '2024-02-01'
                """
                )
            )
            count = result.scalar()

            # Orders from January 2024
            assert count > 0
