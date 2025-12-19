"""
SQL dialect adapters for multi-database support (Issue #14).

This module provides dialect-specific SQL generation and schema
introspection for PostgreSQL, MySQL, SQLite, and SQL Server.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from app.exceptions import UnsupportedDialectException
from app.logging_config import get_logger

logger = get_logger(__name__)


class SQLDialect(str, Enum):
    """Supported SQL dialects."""

    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    SQLITE = "sqlite"
    SQLSERVER = "sqlserver"
    MARIADB = "mariadb"

    @classmethod
    def from_url(cls, url: str) -> "SQLDialect":
        """
        Detect dialect from database URL.

        Args:
            url: Database connection URL

        Returns:
            SQLDialect for the URL

        Raises:
            UnsupportedDialectException: If dialect not supported
        """
        url_lower = url.lower()

        # Handle both sync and async driver URLs
        if url_lower.startswith(("postgresql://", "postgres://", "postgresql+")):
            return cls.POSTGRESQL
        elif url_lower.startswith(("mysql://", "mysql+")):
            return cls.MYSQL
        elif url_lower.startswith(("mariadb://", "mariadb+")):
            return cls.MARIADB
        elif url_lower.startswith(("sqlite:///", "sqlite+")):
            return cls.SQLITE
        elif url_lower.startswith(("mssql://", "sqlserver://", "mssql+")):
            return cls.SQLSERVER
        else:
            raise UnsupportedDialectException(
                dialect=url.split("://")[0] if "://" in url else "unknown",
                supported_dialects=[d.value for d in cls],
            )

    @classmethod
    def supported_dialects(cls) -> list[str]:
        """Return list of supported dialect names."""
        return [d.value for d in cls]


@dataclass
class LimitOffset:
    """Represents LIMIT/OFFSET clause components."""

    limit: int | None = None
    offset: int | None = None


class DialectAdapter(ABC):
    """
    Abstract base class for SQL dialect adapters.

    Provides dialect-specific SQL generation for common operations
    that differ between database engines.
    """

    @property
    @abstractmethod
    def dialect(self) -> SQLDialect:
        """Return the dialect this adapter handles."""
        pass

    @property
    @abstractmethod
    def identifier_quote(self) -> str:
        """Return the character used to quote identifiers."""
        pass

    @property
    @abstractmethod
    def string_quote(self) -> str:
        """Return the character used to quote strings."""
        pass

    @abstractmethod
    def quote_identifier(self, identifier: str) -> str:
        """
        Quote a database identifier (table/column name).

        Args:
            identifier: The identifier to quote

        Returns:
            Properly quoted identifier
        """
        pass

    @abstractmethod
    def get_limit_offset_clause(self, limit_offset: LimitOffset) -> str:
        """
        Generate LIMIT/OFFSET clause for the dialect.

        Args:
            limit_offset: Limit and offset values

        Returns:
            SQL clause string
        """
        pass

    @abstractmethod
    def get_current_timestamp(self) -> str:
        """Return dialect-specific current timestamp function."""
        pass

    @abstractmethod
    def get_concat_function(self, *args: str) -> str:
        """
        Generate string concatenation for the dialect.

        Args:
            args: Strings/columns to concatenate

        Returns:
            Dialect-specific concatenation expression
        """
        pass

    @abstractmethod
    def get_boolean_literal(self, value: bool) -> str:
        """
        Get the boolean literal for the dialect.

        Args:
            value: Boolean value

        Returns:
            Dialect-specific boolean literal
        """
        pass

    @abstractmethod
    def get_schema_query(self) -> str:
        """Return query to list all tables in the database."""
        pass

    @abstractmethod
    def get_columns_query(self, table_name: str) -> str:
        """
        Return query to get column information for a table.

        Args:
            table_name: Name of the table

        Returns:
            SQL query string
        """
        pass

    @abstractmethod
    def get_primary_key_query(self, table_name: str) -> str:
        """
        Return query to get primary key information for a table.

        Args:
            table_name: Name of the table

        Returns:
            SQL query string
        """
        pass

    @abstractmethod
    def get_foreign_key_query(self, table_name: str) -> str:
        """
        Return query to get foreign key relationships for a table.

        Args:
            table_name: Name of the table

        Returns:
            SQL query string
        """
        pass

    @abstractmethod
    def get_health_check_query(self) -> str:
        """Return a simple query to verify database connectivity."""
        pass

    def adapt_sql(self, sql: str) -> str:
        """
        Adapt generic SQL to this dialect's syntax.

        This method can be overridden to handle dialect-specific
        transformations.

        Args:
            sql: SQL query to adapt

        Returns:
            Adapted SQL query
        """
        return sql


class PostgreSQLAdapter(DialectAdapter):
    """PostgreSQL dialect adapter."""

    @property
    def dialect(self) -> SQLDialect:
        return SQLDialect.POSTGRESQL

    @property
    def identifier_quote(self) -> str:
        return '"'

    @property
    def string_quote(self) -> str:
        return "'"

    def quote_identifier(self, identifier: str) -> str:
        escaped = identifier.replace('"', '""')
        return f'"{escaped}"'

    def get_limit_offset_clause(self, limit_offset: LimitOffset) -> str:
        parts = []
        if limit_offset.limit is not None:
            parts.append(f"LIMIT {limit_offset.limit}")
        if limit_offset.offset is not None:
            parts.append(f"OFFSET {limit_offset.offset}")
        return " ".join(parts)

    def get_current_timestamp(self) -> str:
        return "CURRENT_TIMESTAMP"

    def get_concat_function(self, *args: str) -> str:
        return " || ".join(args)

    def get_boolean_literal(self, value: bool) -> str:
        return "TRUE" if value else "FALSE"

    def get_schema_query(self) -> str:
        return """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """

    def get_columns_query(self, table_name: str) -> str:
        return f"""
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default,
                character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = '{table_name}'
            ORDER BY ordinal_position
        """

    def get_primary_key_query(self, table_name: str) -> str:
        return f"""
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
            AND tc.table_name = '{table_name}'
            AND tc.table_schema = 'public'
        """

    def get_foreign_key_query(self, table_name: str) -> str:
        return f"""
            SELECT
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name,
                tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_name = '{table_name}'
        """

    def get_health_check_query(self) -> str:
        return "SELECT 1"


class MySQLAdapter(DialectAdapter):
    """MySQL dialect adapter."""

    @property
    def dialect(self) -> SQLDialect:
        return SQLDialect.MYSQL

    @property
    def identifier_quote(self) -> str:
        return "`"

    @property
    def string_quote(self) -> str:
        return "'"

    def quote_identifier(self, identifier: str) -> str:
        escaped = identifier.replace("`", "``")
        return f"`{escaped}`"

    def get_limit_offset_clause(self, limit_offset: LimitOffset) -> str:
        if limit_offset.limit is not None and limit_offset.offset is not None:
            return f"LIMIT {limit_offset.offset}, {limit_offset.limit}"
        elif limit_offset.limit is not None:
            return f"LIMIT {limit_offset.limit}"
        elif limit_offset.offset is not None:
            return f"LIMIT {limit_offset.offset}, 18446744073709551615"
        return ""

    def get_current_timestamp(self) -> str:
        return "NOW()"

    def get_concat_function(self, *args: str) -> str:
        return f"CONCAT({', '.join(args)})"

    def get_boolean_literal(self, value: bool) -> str:
        return "1" if value else "0"

    def get_schema_query(self) -> str:
        return """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """

    def get_columns_query(self, table_name: str) -> str:
        return f"""
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default,
                character_maximum_length,
                column_key
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
            AND table_name = '{table_name}'
            ORDER BY ordinal_position
        """

    def get_primary_key_query(self, table_name: str) -> str:
        return f"""
            SELECT column_name
            FROM information_schema.key_column_usage
            WHERE table_schema = DATABASE()
            AND table_name = '{table_name}'
            AND constraint_name = 'PRIMARY'
        """

    def get_foreign_key_query(self, table_name: str) -> str:
        return f"""
            SELECT
                column_name,
                referenced_table_name AS foreign_table_name,
                referenced_column_name AS foreign_column_name,
                constraint_name
            FROM information_schema.key_column_usage
            WHERE table_schema = DATABASE()
            AND table_name = '{table_name}'
            AND referenced_table_name IS NOT NULL
        """

    def get_health_check_query(self) -> str:
        return "SELECT 1"


class SQLiteAdapter(DialectAdapter):
    """SQLite dialect adapter."""

    @property
    def dialect(self) -> SQLDialect:
        return SQLDialect.SQLITE

    @property
    def identifier_quote(self) -> str:
        return '"'

    @property
    def string_quote(self) -> str:
        return "'"

    def quote_identifier(self, identifier: str) -> str:
        escaped = identifier.replace('"', '""')
        return f'"{escaped}"'

    def get_limit_offset_clause(self, limit_offset: LimitOffset) -> str:
        parts = []
        if limit_offset.limit is not None:
            parts.append(f"LIMIT {limit_offset.limit}")
        if limit_offset.offset is not None:
            parts.append(f"OFFSET {limit_offset.offset}")
        return " ".join(parts)

    def get_current_timestamp(self) -> str:
        return "datetime('now')"

    def get_concat_function(self, *args: str) -> str:
        return " || ".join(args)

    def get_boolean_literal(self, value: bool) -> str:
        return "1" if value else "0"

    def get_schema_query(self) -> str:
        return """
            SELECT name AS table_name
            FROM sqlite_master
            WHERE type = 'table'
            AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """

    def get_columns_query(self, table_name: str) -> str:
        return f"PRAGMA table_info('{table_name}')"

    def get_primary_key_query(self, table_name: str) -> str:
        return f"PRAGMA table_info('{table_name}')"

    def get_foreign_key_query(self, table_name: str) -> str:
        return f"PRAGMA foreign_key_list('{table_name}')"

    def get_health_check_query(self) -> str:
        return "SELECT 1"


class SQLServerAdapter(DialectAdapter):
    """SQL Server dialect adapter."""

    @property
    def dialect(self) -> SQLDialect:
        return SQLDialect.SQLSERVER

    @property
    def identifier_quote(self) -> str:
        return "["

    @property
    def string_quote(self) -> str:
        return "'"

    def quote_identifier(self, identifier: str) -> str:
        escaped = identifier.replace("]", "]]")
        return f"[{escaped}]"

    def get_limit_offset_clause(self, limit_offset: LimitOffset) -> str:
        if limit_offset.offset is not None and limit_offset.limit is not None:
            return (
                f"OFFSET {limit_offset.offset} ROWS "
                f"FETCH NEXT {limit_offset.limit} ROWS ONLY"
            )
        elif limit_offset.limit is not None:
            return f"OFFSET 0 ROWS FETCH NEXT {limit_offset.limit} ROWS ONLY"
        elif limit_offset.offset is not None:
            return f"OFFSET {limit_offset.offset} ROWS"
        return ""

    def get_current_timestamp(self) -> str:
        return "GETDATE()"

    def get_concat_function(self, *args: str) -> str:
        return f"CONCAT({', '.join(args)})"

    def get_boolean_literal(self, value: bool) -> str:
        return "1" if value else "0"

    def get_schema_query(self) -> str:
        return """
            SELECT TABLE_NAME as table_name
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
            AND TABLE_SCHEMA = 'dbo'
            ORDER BY TABLE_NAME
        """

    def get_columns_query(self, table_name: str) -> str:
        return f"""
            SELECT
                COLUMN_NAME as column_name,
                DATA_TYPE as data_type,
                IS_NULLABLE as is_nullable,
                COLUMN_DEFAULT as column_default,
                CHARACTER_MAXIMUM_LENGTH as character_maximum_length
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = '{table_name}'
            AND TABLE_SCHEMA = 'dbo'
            ORDER BY ORDINAL_POSITION
        """

    def get_primary_key_query(self, table_name: str) -> str:
        return f"""
            SELECT COLUMN_NAME as column_name
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE OBJECTPROPERTY(OBJECT_ID(CONSTRAINT_SCHEMA + '.' + CONSTRAINT_NAME),
                                 'IsPrimaryKey') = 1
            AND TABLE_NAME = '{table_name}'
        """

    def get_foreign_key_query(self, table_name: str) -> str:
        return f"""
            SELECT
                fk.name AS constraint_name,
                COL_NAME(fc.parent_object_id, fc.parent_column_id) AS column_name,
                OBJECT_NAME(fc.referenced_object_id) AS foreign_table_name,
                COL_NAME(fc.referenced_object_id, fc.referenced_column_id)
                    AS foreign_column_name
            FROM sys.foreign_keys fk
            INNER JOIN sys.foreign_key_columns fc
                ON fk.object_id = fc.constraint_object_id
            WHERE OBJECT_NAME(fc.parent_object_id) = '{table_name}'
        """

    def get_health_check_query(self) -> str:
        return "SELECT 1"


class MariaDBAdapter(MySQLAdapter):
    """MariaDB dialect adapter (extends MySQL)."""

    @property
    def dialect(self) -> SQLDialect:
        return SQLDialect.MARIADB


def get_dialect_adapter(dialect: SQLDialect | str) -> DialectAdapter:
    """
    Factory function to get the appropriate dialect adapter.

    Args:
        dialect: SQLDialect enum or string dialect name

    Returns:
        DialectAdapter for the specified dialect

    Raises:
        UnsupportedDialectException: If dialect not supported
    """
    if isinstance(dialect, str):
        try:
            dialect = SQLDialect(dialect.lower())
        except ValueError:
            raise UnsupportedDialectException(
                dialect=dialect,
                supported_dialects=SQLDialect.supported_dialects(),
            ) from None

    adapters: dict[SQLDialect, type[DialectAdapter]] = {
        SQLDialect.POSTGRESQL: PostgreSQLAdapter,
        SQLDialect.MYSQL: MySQLAdapter,
        SQLDialect.SQLITE: SQLiteAdapter,
        SQLDialect.SQLSERVER: SQLServerAdapter,
        SQLDialect.MARIADB: MariaDBAdapter,
    }

    adapter_class = adapters.get(dialect)
    if not adapter_class:
        raise UnsupportedDialectException(
            dialect=dialect.value,
            supported_dialects=SQLDialect.supported_dialects(),
        )

    return adapter_class()


def get_async_driver(dialect: SQLDialect) -> str:
    """
    Get the async driver prefix for a dialect.

    Args:
        dialect: SQLDialect enum

    Returns:
        Async driver string (e.g., 'postgresql+asyncpg')
    """
    drivers: dict[SQLDialect, str] = {
        SQLDialect.POSTGRESQL: "postgresql+asyncpg",
        SQLDialect.MYSQL: "mysql+aiomysql",
        SQLDialect.MARIADB: "mysql+aiomysql",
        SQLDialect.SQLITE: "sqlite+aiosqlite",
        SQLDialect.SQLSERVER: "mssql+aioodbc",
    }
    return drivers.get(dialect, dialect.value)


def convert_url_to_async(url: str) -> str:
    """
    Convert a standard database URL to async-compatible URL.

    Args:
        url: Standard database URL

    Returns:
        Async-compatible database URL
    """
    dialect = SQLDialect.from_url(url)
    async_driver = get_async_driver(dialect)

    if url.startswith("postgresql://"):
        return url.replace("postgresql://", f"{async_driver}://", 1)
    elif url.startswith("postgres://"):
        return url.replace("postgres://", f"{async_driver}://", 1)
    elif url.startswith("mysql://"):
        return url.replace("mysql://", f"{async_driver}://", 1)
    elif url.startswith("mariadb://"):
        return url.replace("mariadb://", f"{async_driver}://", 1)
    elif url.startswith("sqlite:///"):
        return url.replace("sqlite:///", f"{async_driver}:///", 1)
    elif url.startswith("mssql://"):
        return url.replace("mssql://", f"{async_driver}://", 1)
    elif url.startswith("sqlserver://"):
        return url.replace("sqlserver://", f"{async_driver}://", 1)

    return url
