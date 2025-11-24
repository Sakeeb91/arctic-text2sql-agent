"""
Unit tests for database schema introspection utilities.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncEngine

from app.exceptions import SchemaNotFoundException, TableNotFoundException
from db.schema import (
    ColumnInfo,
    ForeignKeyInfo,
    TableInfo,
    SchemaInfo,
    SchemaIntrospector,
    get_sample_data,
)


class TestColumnInfo:
    """Tests for ColumnInfo dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic column info creation."""
        col = ColumnInfo(
            name="id",
            data_type="INTEGER",
            nullable=False,
            primary_key=True,
        )

        assert col.name == "id"
        assert col.data_type == "INTEGER"
        assert col.nullable is False
        assert col.primary_key is True

    def test_to_dict(self) -> None:
        """Test column info serialization."""
        col = ColumnInfo(
            name="email",
            data_type="VARCHAR(255)",
            nullable=True,
            foreign_key="users.id",
            default="NULL",
        )

        result = col.to_dict()

        assert result["name"] == "email"
        assert result["data_type"] == "VARCHAR(255)"
        assert result["nullable"] is True
        assert result["foreign_key"] == "users.id"
        assert result["default"] == "NULL"

    def test_default_values(self) -> None:
        """Test default values for optional fields."""
        col = ColumnInfo(name="test", data_type="TEXT", nullable=True)

        assert col.primary_key is False
        assert col.foreign_key is None
        assert col.default is None
        assert col.comment is None


class TestForeignKeyInfo:
    """Tests for ForeignKeyInfo dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic foreign key info creation."""
        fk = ForeignKeyInfo(
            column="customer_id",
            references_table="customers",
            references_column="id",
        )

        assert fk.column == "customer_id"
        assert fk.references_table == "customers"
        assert fk.references_column == "id"

    def test_to_dict(self) -> None:
        """Test foreign key info serialization."""
        fk = ForeignKeyInfo(
            column="order_id",
            references_table="orders",
            references_column="id",
            constraint_name="fk_order_id",
        )

        result = fk.to_dict()

        assert result["column"] == "order_id"
        assert result["references_table"] == "orders"
        assert result["references_column"] == "id"
        assert result["constraint_name"] == "fk_order_id"


class TestTableInfo:
    """Tests for TableInfo dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic table info creation."""
        table = TableInfo(name="users")

        assert table.name == "users"
        assert table.columns == []
        assert table.foreign_keys == []
        assert table.primary_keys == []

    def test_to_dict_with_columns(self) -> None:
        """Test table info serialization with columns."""
        table = TableInfo(
            name="customers",
            columns=[
                ColumnInfo(
                    name="id", data_type="INTEGER", nullable=False, primary_key=True
                ),
                ColumnInfo(name="name", data_type="VARCHAR(100)", nullable=False),
            ],
            primary_keys=["id"],
            row_count=1000,
        )

        result = table.to_dict()

        assert result["name"] == "customers"
        assert len(result["columns"]) == 2
        assert result["primary_keys"] == ["id"]
        assert result["row_count"] == 1000


class TestSchemaInfo:
    """Tests for SchemaInfo dataclass."""

    @pytest.fixture
    def sample_schema(self) -> SchemaInfo:
        """Create sample schema for tests."""
        return SchemaInfo(
            database_id="test_db",
            dialect="postgresql",
            tables=[
                TableInfo(
                    name="users",
                    columns=[
                        ColumnInfo(
                            name="id",
                            data_type="INTEGER",
                            nullable=False,
                            primary_key=True,
                        ),
                        ColumnInfo(
                            name="email", data_type="VARCHAR(255)", nullable=False
                        ),
                    ],
                    primary_keys=["id"],
                ),
                TableInfo(
                    name="orders",
                    columns=[
                        ColumnInfo(
                            name="id",
                            data_type="INTEGER",
                            nullable=False,
                            primary_key=True,
                        ),
                        ColumnInfo(
                            name="user_id",
                            data_type="INTEGER",
                            nullable=False,
                            foreign_key="users.id",
                        ),
                    ],
                    primary_keys=["id"],
                ),
            ],
        )

    def test_to_dict(self, sample_schema: SchemaInfo) -> None:
        """Test schema info serialization."""
        result = sample_schema.to_dict()

        assert result["database_id"] == "test_db"
        assert result["dialect"] == "postgresql"
        assert result["table_count"] == 2
        assert len(result["tables"]) == 2
        assert "last_updated" in result

    def test_get_table_found(self, sample_schema: SchemaInfo) -> None:
        """Test getting an existing table."""
        table = sample_schema.get_table("users")

        assert table.name == "users"
        assert len(table.columns) == 2

    def test_get_table_case_insensitive(self, sample_schema: SchemaInfo) -> None:
        """Test table lookup is case insensitive."""
        table = sample_schema.get_table("USERS")

        assert table.name == "users"

    def test_get_table_not_found(self, sample_schema: SchemaInfo) -> None:
        """Test getting a non-existent table."""
        with pytest.raises(TableNotFoundException):
            sample_schema.get_table("nonexistent")


class TestSchemaIntrospector:
    """Tests for SchemaIntrospector class."""

    @pytest.fixture
    def mock_engine(self) -> MagicMock:
        """Create mock SQLAlchemy engine."""
        engine = MagicMock(spec=AsyncEngine)
        engine.dialect = MagicMock()
        engine.dialect.name = "postgresql"
        return engine

    def test_initialization(self, mock_engine: MagicMock) -> None:
        """Test introspector initialization."""
        introspector = SchemaIntrospector(mock_engine)

        assert introspector._engine is mock_engine
        assert introspector._cache == {}

    @pytest.mark.asyncio
    async def test_get_schema_uses_cache(self, mock_engine: MagicMock) -> None:
        """Test that get_schema uses cached schema."""
        introspector = SchemaIntrospector(mock_engine)

        # Pre-populate cache
        cached_schema = SchemaInfo(
            database_id="test_db",
            dialect="postgresql",
            tables=[],
        )
        introspector._cache["test_db"] = cached_schema

        result = await introspector.get_schema("test_db", use_cache=True)

        assert result is cached_schema

    @pytest.mark.asyncio
    async def test_get_schema_skips_cache_when_disabled(
        self, mock_engine: MagicMock
    ) -> None:
        """Test that get_schema bypasses cache when disabled."""
        introspector = SchemaIntrospector(mock_engine)

        # Pre-populate cache
        cached_schema = SchemaInfo(
            database_id="test_db",
            dialect="postgresql",
            tables=[],
        )
        introspector._cache["test_db"] = cached_schema

        # Mock the engine connection
        mock_connection = AsyncMock()
        mock_engine.connect.return_value.__aenter__.return_value = mock_connection

        # Mock run_sync to return empty schema
        mock_connection.run_sync.return_value = {"tables": []}

        result = await introspector.get_schema("test_db", use_cache=False)

        # Should have called connect (not used cache)
        mock_engine.connect.assert_called_once()

    def test_serialize_for_prompt_basic(self, mock_engine: MagicMock) -> None:
        """Test basic prompt serialization."""
        introspector = SchemaIntrospector(mock_engine)
        schema = SchemaInfo(
            database_id="test_db",
            dialect="postgresql",
            tables=[
                TableInfo(
                    name="users",
                    columns=[
                        ColumnInfo(
                            name="id",
                            data_type="INTEGER",
                            nullable=False,
                            primary_key=True,
                        ),
                        ColumnInfo(
                            name="name", data_type="VARCHAR(100)", nullable=True
                        ),
                    ],
                    primary_keys=["id"],
                ),
            ],
        )

        result = introspector.serialize_for_prompt(schema)

        assert "Database Schema (postgresql):" in result
        assert "Table: users" in result
        assert "id (INTEGER)" in result
        assert "[PK]" in result
        assert "[NOT NULL]" in result
        assert "name (VARCHAR(100))" in result

    def test_serialize_for_prompt_with_foreign_keys(
        self, mock_engine: MagicMock
    ) -> None:
        """Test prompt serialization includes foreign keys."""
        introspector = SchemaIntrospector(mock_engine)
        schema = SchemaInfo(
            database_id="test_db",
            dialect="sqlite",
            tables=[
                TableInfo(
                    name="orders",
                    columns=[
                        ColumnInfo(
                            name="user_id",
                            data_type="INTEGER",
                            nullable=False,
                            foreign_key="users.id",
                        ),
                    ],
                    foreign_keys=[
                        ForeignKeyInfo(
                            column="user_id",
                            references_table="users",
                            references_column="id",
                        )
                    ],
                ),
            ],
        )

        result = introspector.serialize_for_prompt(schema, include_foreign_keys=True)

        assert "FK -> users.id" in result
        assert "Foreign Keys:" in result

    def test_serialize_for_prompt_without_types(self, mock_engine: MagicMock) -> None:
        """Test prompt serialization without types."""
        introspector = SchemaIntrospector(mock_engine)
        schema = SchemaInfo(
            database_id="test_db",
            dialect="postgresql",
            tables=[
                TableInfo(
                    name="users",
                    columns=[
                        ColumnInfo(name="id", data_type="INTEGER", nullable=False),
                    ],
                ),
            ],
        )

        result = introspector.serialize_for_prompt(schema, include_types=False)

        assert "(INTEGER)" not in result
        assert "id" in result

    def test_serialize_for_prompt_max_tables(self, mock_engine: MagicMock) -> None:
        """Test prompt serialization with table limit."""
        introspector = SchemaIntrospector(mock_engine)
        schema = SchemaInfo(
            database_id="test_db",
            dialect="postgresql",
            tables=[
                TableInfo(name="table1", columns=[]),
                TableInfo(name="table2", columns=[]),
                TableInfo(name="table3", columns=[]),
            ],
        )

        result = introspector.serialize_for_prompt(schema, max_tables=2)

        assert "table1" in result
        assert "table2" in result
        assert "table3" not in result

    def test_invalidate_cache_specific(self, mock_engine: MagicMock) -> None:
        """Test invalidating specific database cache."""
        introspector = SchemaIntrospector(mock_engine)
        introspector._cache["db1"] = MagicMock()
        introspector._cache["db2"] = MagicMock()

        introspector.invalidate_cache("db1")

        assert "db1" not in introspector._cache
        assert "db2" in introspector._cache

    def test_invalidate_cache_all(self, mock_engine: MagicMock) -> None:
        """Test invalidating all cached schemas."""
        introspector = SchemaIntrospector(mock_engine)
        introspector._cache["db1"] = MagicMock()
        introspector._cache["db2"] = MagicMock()

        introspector.invalidate_cache()

        assert introspector._cache == {}


class TestGetSampleData:
    """Tests for get_sample_data function."""

    @pytest.mark.asyncio
    async def test_get_sample_data_success(self) -> None:
        """Test successful sample data retrieval."""
        mock_engine = MagicMock(spec=AsyncEngine)
        mock_connection = AsyncMock()
        mock_engine.connect.return_value.__aenter__.return_value = mock_connection

        # Mock query result
        mock_result = MagicMock()
        mock_result.keys.return_value = ["id", "name"]
        mock_result.fetchall.return_value = [(1, "Alice"), (2, "Bob")]
        mock_connection.execute.return_value = mock_result

        result = await get_sample_data(mock_engine, "users", limit=5)

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[0]["name"] == "Alice"
        assert result[1]["id"] == 2
        assert result[1]["name"] == "Bob"

    @pytest.mark.asyncio
    async def test_get_sample_data_error(self) -> None:
        """Test sample data retrieval with error."""
        mock_engine = MagicMock(spec=AsyncEngine)
        mock_engine.connect.return_value.__aenter__.side_effect = Exception(
            "Connection failed"
        )

        result = await get_sample_data(mock_engine, "users")

        # Should return empty list on error
        assert result == []

