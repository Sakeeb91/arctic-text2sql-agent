"""
Unit tests for SQL dialect adapters (Issue #14: Multi-Database Support).
"""

import pytest

from app.exceptions import UnsupportedDialectException
from db.dialects import (
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


class TestSQLDialect:
    """Tests for SQLDialect enum."""

    def test_supported_dialects(self) -> None:
        """Test listing supported dialects."""
        dialects = SQLDialect.supported_dialects()

        assert "postgresql" in dialects
        assert "mysql" in dialects
        assert "sqlite" in dialects
        assert "sqlserver" in dialects
        assert "mariadb" in dialects
        assert len(dialects) == 5

    def test_from_url_postgresql(self) -> None:
        """Test detecting PostgreSQL from URL."""
        assert SQLDialect.from_url("postgresql://localhost/db") == SQLDialect.POSTGRESQL
        assert SQLDialect.from_url("postgres://localhost/db") == SQLDialect.POSTGRESQL

    def test_from_url_mysql(self) -> None:
        """Test detecting MySQL from URL."""
        assert SQLDialect.from_url("mysql://localhost/db") == SQLDialect.MYSQL

    def test_from_url_mariadb(self) -> None:
        """Test detecting MariaDB from URL."""
        assert SQLDialect.from_url("mariadb://localhost/db") == SQLDialect.MARIADB

    def test_from_url_sqlite(self) -> None:
        """Test detecting SQLite from URL."""
        assert SQLDialect.from_url("sqlite:///./test.db") == SQLDialect.SQLITE

    def test_from_url_sqlserver(self) -> None:
        """Test detecting SQL Server from URL."""
        assert SQLDialect.from_url("mssql://localhost/db") == SQLDialect.SQLSERVER
        assert SQLDialect.from_url("sqlserver://localhost/db") == SQLDialect.SQLSERVER

    def test_from_url_unsupported(self) -> None:
        """Test unsupported dialect raises exception."""
        with pytest.raises(UnsupportedDialectException) as exc_info:
            SQLDialect.from_url("oracle://localhost/db")

        assert "oracle" in str(exc_info.value.message)


class TestPostgreSQLAdapter:
    """Tests for PostgreSQL dialect adapter."""

    @pytest.fixture
    def adapter(self) -> PostgreSQLAdapter:
        """Create PostgreSQL adapter."""
        return PostgreSQLAdapter()

    def test_dialect(self, adapter: PostgreSQLAdapter) -> None:
        """Test dialect property."""
        assert adapter.dialect == SQLDialect.POSTGRESQL

    def test_quote_identifier(self, adapter: PostgreSQLAdapter) -> None:
        """Test identifier quoting."""
        assert adapter.quote_identifier("table_name") == '"table_name"'
        assert adapter.quote_identifier('col"name') == '"col""name"'

    def test_limit_offset_both(self, adapter: PostgreSQLAdapter) -> None:
        """Test LIMIT with OFFSET."""
        result = adapter.get_limit_offset_clause(LimitOffset(limit=10, offset=5))
        assert result == "LIMIT 10 OFFSET 5"

    def test_limit_only(self, adapter: PostgreSQLAdapter) -> None:
        """Test LIMIT only."""
        result = adapter.get_limit_offset_clause(LimitOffset(limit=10))
        assert result == "LIMIT 10"

    def test_offset_only(self, adapter: PostgreSQLAdapter) -> None:
        """Test OFFSET only."""
        result = adapter.get_limit_offset_clause(LimitOffset(offset=5))
        assert result == "OFFSET 5"

    def test_concat_function(self, adapter: PostgreSQLAdapter) -> None:
        """Test string concatenation."""
        result = adapter.get_concat_function("a", "b", "c")
        assert result == "a || b || c"

    def test_boolean_literal(self, adapter: PostgreSQLAdapter) -> None:
        """Test boolean literals."""
        assert adapter.get_boolean_literal(True) == "TRUE"
        assert adapter.get_boolean_literal(False) == "FALSE"

    def test_health_check_query(self, adapter: PostgreSQLAdapter) -> None:
        """Test health check query."""
        assert adapter.get_health_check_query() == "SELECT 1"


class TestMySQLAdapter:
    """Tests for MySQL dialect adapter."""

    @pytest.fixture
    def adapter(self) -> MySQLAdapter:
        """Create MySQL adapter."""
        return MySQLAdapter()

    def test_dialect(self, adapter: MySQLAdapter) -> None:
        """Test dialect property."""
        assert adapter.dialect == SQLDialect.MYSQL

    def test_quote_identifier(self, adapter: MySQLAdapter) -> None:
        """Test identifier quoting."""
        assert adapter.quote_identifier("table_name") == "`table_name`"
        assert adapter.quote_identifier("col`name") == "`col``name`"

    def test_limit_offset_both(self, adapter: MySQLAdapter) -> None:
        """Test MySQL LIMIT syntax with offset."""
        result = adapter.get_limit_offset_clause(LimitOffset(limit=10, offset=5))
        assert result == "LIMIT 5, 10"

    def test_limit_only(self, adapter: MySQLAdapter) -> None:
        """Test LIMIT only."""
        result = adapter.get_limit_offset_clause(LimitOffset(limit=10))
        assert result == "LIMIT 10"

    def test_concat_function(self, adapter: MySQLAdapter) -> None:
        """Test CONCAT function."""
        result = adapter.get_concat_function("a", "b", "c")
        assert result == "CONCAT(a, b, c)"

    def test_boolean_literal(self, adapter: MySQLAdapter) -> None:
        """Test boolean literals."""
        assert adapter.get_boolean_literal(True) == "1"
        assert adapter.get_boolean_literal(False) == "0"


class TestSQLiteAdapter:
    """Tests for SQLite dialect adapter."""

    @pytest.fixture
    def adapter(self) -> SQLiteAdapter:
        """Create SQLite adapter."""
        return SQLiteAdapter()

    def test_dialect(self, adapter: SQLiteAdapter) -> None:
        """Test dialect property."""
        assert adapter.dialect == SQLDialect.SQLITE

    def test_quote_identifier(self, adapter: SQLiteAdapter) -> None:
        """Test identifier quoting."""
        assert adapter.quote_identifier("table_name") == '"table_name"'

    def test_current_timestamp(self, adapter: SQLiteAdapter) -> None:
        """Test current timestamp function."""
        assert adapter.get_current_timestamp() == "datetime('now')"

    def test_schema_query(self, adapter: SQLiteAdapter) -> None:
        """Test schema query uses sqlite_master."""
        query = adapter.get_schema_query()
        assert "sqlite_master" in query


class TestSQLServerAdapter:
    """Tests for SQL Server dialect adapter."""

    @pytest.fixture
    def adapter(self) -> SQLServerAdapter:
        """Create SQL Server adapter."""
        return SQLServerAdapter()

    def test_dialect(self, adapter: SQLServerAdapter) -> None:
        """Test dialect property."""
        assert adapter.dialect == SQLDialect.SQLSERVER

    def test_quote_identifier(self, adapter: SQLServerAdapter) -> None:
        """Test identifier quoting."""
        assert adapter.quote_identifier("table_name") == "[table_name]"
        assert adapter.quote_identifier("col]name") == "[col]]name]"

    def test_limit_offset_both(self, adapter: SQLServerAdapter) -> None:
        """Test SQL Server OFFSET FETCH syntax."""
        result = adapter.get_limit_offset_clause(LimitOffset(limit=10, offset=5))
        assert "OFFSET 5 ROWS" in result
        assert "FETCH NEXT 10 ROWS ONLY" in result

    def test_limit_only(self, adapter: SQLServerAdapter) -> None:
        """Test LIMIT only translates to OFFSET 0 FETCH."""
        result = adapter.get_limit_offset_clause(LimitOffset(limit=10))
        assert "OFFSET 0 ROWS" in result
        assert "FETCH NEXT 10 ROWS ONLY" in result


class TestMariaDBAdapter:
    """Tests for MariaDB dialect adapter."""

    @pytest.fixture
    def adapter(self) -> MariaDBAdapter:
        """Create MariaDB adapter."""
        return MariaDBAdapter()

    def test_dialect(self, adapter: MariaDBAdapter) -> None:
        """Test dialect property."""
        assert adapter.dialect == SQLDialect.MARIADB

    def test_inherits_mysql(self, adapter: MariaDBAdapter) -> None:
        """Test MariaDB inherits MySQL functionality."""
        assert adapter.quote_identifier("test") == "`test`"
        assert adapter.get_concat_function("a", "b") == "CONCAT(a, b)"


class TestGetDialectAdapter:
    """Tests for get_dialect_adapter factory function."""

    def test_get_postgresql_adapter(self) -> None:
        """Test getting PostgreSQL adapter."""
        adapter = get_dialect_adapter(SQLDialect.POSTGRESQL)
        assert isinstance(adapter, PostgreSQLAdapter)

    def test_get_mysql_adapter(self) -> None:
        """Test getting MySQL adapter."""
        adapter = get_dialect_adapter(SQLDialect.MYSQL)
        assert isinstance(adapter, MySQLAdapter)

    def test_get_adapter_from_string(self) -> None:
        """Test getting adapter from string dialect."""
        adapter = get_dialect_adapter("postgresql")
        assert isinstance(adapter, PostgreSQLAdapter)

    def test_unsupported_dialect(self) -> None:
        """Test unsupported dialect raises exception."""
        with pytest.raises(UnsupportedDialectException):
            get_dialect_adapter("oracle")


class TestGetAsyncDriver:
    """Tests for get_async_driver function."""

    def test_postgresql_driver(self) -> None:
        """Test PostgreSQL async driver."""
        driver = get_async_driver(SQLDialect.POSTGRESQL)
        assert driver == "postgresql+asyncpg"

    def test_mysql_driver(self) -> None:
        """Test MySQL async driver."""
        driver = get_async_driver(SQLDialect.MYSQL)
        assert driver == "mysql+aiomysql"

    def test_sqlite_driver(self) -> None:
        """Test SQLite async driver."""
        driver = get_async_driver(SQLDialect.SQLITE)
        assert driver == "sqlite+aiosqlite"


class TestConvertUrlToAsync:
    """Tests for convert_url_to_async function."""

    def test_convert_postgresql(self) -> None:
        """Test PostgreSQL URL conversion."""
        url = "postgresql://user:pass@localhost/db"
        result = convert_url_to_async(url)
        assert result == "postgresql+asyncpg://user:pass@localhost/db"

    def test_convert_postgres_alias(self) -> None:
        """Test postgres:// URL conversion."""
        url = "postgres://user:pass@localhost/db"
        result = convert_url_to_async(url)
        assert result == "postgresql+asyncpg://user:pass@localhost/db"

    def test_convert_mysql(self) -> None:
        """Test MySQL URL conversion."""
        url = "mysql://user:pass@localhost/db"
        result = convert_url_to_async(url)
        assert result == "mysql+aiomysql://user:pass@localhost/db"

    def test_convert_sqlite(self) -> None:
        """Test SQLite URL conversion."""
        url = "sqlite:///./test.db"
        result = convert_url_to_async(url)
        assert result == "sqlite+aiosqlite:///./test.db"
