"""
Database schema introspection utilities.

This module provides functionality to extract and serialize
database schema information for use in SQL generation prompts.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.exceptions import SchemaNotFoundException, TableNotFoundException
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ColumnInfo:
    """Information about a database column."""

    name: str
    data_type: str
    nullable: bool
    primary_key: bool = False
    foreign_key: str | None = None
    default: str | None = None
    comment: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "data_type": self.data_type,
            "nullable": self.nullable,
            "primary_key": self.primary_key,
            "foreign_key": self.foreign_key,
            "default": self.default,
            "comment": self.comment,
        }


@dataclass
class ForeignKeyInfo:
    """Information about a foreign key relationship."""

    column: str
    references_table: str
    references_column: str
    constraint_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "column": self.column,
            "references_table": self.references_table,
            "references_column": self.references_column,
            "constraint_name": self.constraint_name,
        }


@dataclass
class TableInfo:
    """Information about a database table."""

    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=list)
    row_count: int | None = None
    comment: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "columns": [col.to_dict() for col in self.columns],
            "foreign_keys": [fk.to_dict() for fk in self.foreign_keys],
            "primary_keys": self.primary_keys,
            "row_count": self.row_count,
            "comment": self.comment,
        }


@dataclass
class SchemaInfo:
    """Complete database schema information."""

    database_id: str
    dialect: str
    tables: list[TableInfo] = field(default_factory=list)
    last_updated: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "database_id": self.database_id,
            "dialect": self.dialect,
            "tables": [table.to_dict() for table in self.tables],
            "table_count": len(self.tables),
            "last_updated": self.last_updated.isoformat(),
        }

    def get_table(self, table_name: str) -> TableInfo:
        """Get table by name."""
        for table in self.tables:
            if table.name.lower() == table_name.lower():
                return table
        raise TableNotFoundException(table_name)


class SchemaIntrospector:
    """
    Extract and manage database schema information.

    Usage:
        introspector = SchemaIntrospector(engine)
        schema = await introspector.get_schema("my_database")
        prompt_text = introspector.serialize_for_prompt(schema)
    """

    def __init__(self, engine: AsyncEngine) -> None:
        """
        Initialize schema introspector.

        Args:
            engine: SQLAlchemy async engine
        """
        self._engine = engine
        self._cache: dict[str, SchemaInfo] = {}

    async def get_schema(
        self,
        database_id: str,
        use_cache: bool = True,
        include_row_counts: bool = False,
    ) -> SchemaInfo:
        """
        Get complete schema information for a database.

        Args:
            database_id: Database identifier
            use_cache: Whether to use cached schema
            include_row_counts: Include row counts (can be slow)

        Returns:
            SchemaInfo: Complete schema information
        """
        if use_cache and database_id in self._cache:
            return self._cache[database_id]

        logger.info("introspecting_schema", database_id=database_id)

        try:
            async with self._engine.connect() as conn:
                schema = await self._extract_schema(
                    conn, database_id, include_row_counts
                )
                self._cache[database_id] = schema
                return schema

        except Exception as e:
            logger.error(
                "schema_introspection_failed",
                database_id=database_id,
                error=str(e),
            )
            raise SchemaNotFoundException(
                database_id=database_id,
                details={"error": str(e)},
            ) from e

    async def _extract_schema(
        self,
        conn: AsyncConnection,
        database_id: str,
        include_row_counts: bool,
    ) -> SchemaInfo:
        """Extract schema from database connection."""

        # Run inspection in sync context
        def sync_inspect(connection: Any) -> dict[str, Any]:
            inspector = inspect(connection)
            tables = []

            for table_name in inspector.get_table_names():
                columns = []
                primary_keys = []

                # Get column information
                for col in inspector.get_columns(table_name):
                    column_info = ColumnInfo(
                        name=col["name"],
                        data_type=str(col["type"]),
                        nullable=col.get("nullable", True),
                        primary_key=False,
                        default=str(col.get("default")) if col.get("default") else None,
                        comment=col.get("comment"),
                    )
                    columns.append(column_info)

                # Get primary key information
                pk_constraint = inspector.get_pk_constraint(table_name)
                if pk_constraint:
                    primary_keys = pk_constraint.get("constrained_columns", [])
                    for col in columns:
                        if col.name in primary_keys:
                            col.primary_key = True

                # Get foreign key information
                foreign_keys = []
                for fk in inspector.get_foreign_keys(table_name):
                    for i, col in enumerate(fk.get("constrained_columns", [])):
                        referred_cols = fk.get("referred_columns", [])
                        fk_info = ForeignKeyInfo(
                            column=col,
                            references_table=fk.get("referred_table", ""),
                            references_column=(
                                referred_cols[i] if i < len(referred_cols) else ""
                            ),
                            constraint_name=fk.get("name"),
                        )
                        foreign_keys.append(fk_info)
                        # Update column with FK reference
                        for c in columns:
                            if c.name == col:
                                c.foreign_key = f"{fk_info.references_table}.{fk_info.references_column}"

                tables.append(
                    TableInfo(
                        name=table_name,
                        columns=columns,
                        foreign_keys=foreign_keys,
                        primary_keys=primary_keys,
                    )
                )

            return {"tables": tables}

        # Execute sync inspection
        result = await conn.run_sync(sync_inspect)
        tables = result["tables"]

        # Optionally get row counts
        if include_row_counts:
            for table in tables:
                try:
                    count_result = await conn.execute(
                        text(f"SELECT COUNT(*) FROM {table.name}")  # noqa: S608
                    )
                    row = count_result.fetchone()
                    table.row_count = row[0] if row else 0
                except Exception as e:
                    logger.warning(
                        "row_count_failed",
                        table=table.name,
                        error=str(e),
                    )

        # Get dialect
        dialect = self._engine.dialect.name

        return SchemaInfo(
            database_id=database_id,
            dialect=dialect,
            tables=tables,
        )

    def serialize_for_prompt(
        self,
        schema: SchemaInfo,
        include_foreign_keys: bool = True,
        include_types: bool = True,
        max_tables: int | None = None,
    ) -> str:
        """
        Serialize schema for use in model prompts.

        Args:
            schema: Schema information
            include_foreign_keys: Include FK relationships
            include_types: Include column data types
            max_tables: Maximum tables to include

        Returns:
            str: Formatted schema string for prompts
        """
        lines = [f"Database Schema ({schema.dialect}):", ""]

        tables = schema.tables[:max_tables] if max_tables else schema.tables

        for table in tables:
            lines.append(f"Table: {table.name}")

            for col in table.columns:
                col_str = f"  - {col.name}"
                if include_types:
                    col_str += f" ({col.data_type})"
                if col.primary_key:
                    col_str += " [PK]"
                if col.foreign_key and include_foreign_keys:
                    col_str += f" [FK -> {col.foreign_key}]"
                if not col.nullable:
                    col_str += " [NOT NULL]"
                lines.append(col_str)

            if include_foreign_keys and table.foreign_keys:
                lines.append("  Foreign Keys:")
                for fk in table.foreign_keys:
                    lines.append(
                        f"    {fk.column} -> {fk.references_table}.{fk.references_column}"
                    )

            lines.append("")

        return "\n".join(lines)

    def invalidate_cache(self, database_id: str | None = None) -> None:
        """
        Invalidate cached schema.

        Args:
            database_id: Specific database to invalidate, or None for all
        """
        if database_id:
            self._cache.pop(database_id, None)
        else:
            self._cache.clear()

        logger.info(
            "schema_cache_invalidated",
            database_id=database_id or "all",
        )


async def get_sample_data(
    engine: AsyncEngine,
    table_name: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Get sample rows from a table.

    Useful for few-shot prompting and data format understanding.

    Args:
        engine: Database engine
        table_name: Table to sample from
        limit: Maximum rows to return

    Returns:
        List of sample rows as dictionaries
    """
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(f"SELECT * FROM {table_name} LIMIT :limit"),  # noqa: S608
                {"limit": limit},
            )
            columns = result.keys()
            rows = result.fetchall()

            return [dict(zip(columns, row, strict=False)) for row in rows]

    except Exception as e:
        logger.warning(
            "sample_data_failed",
            table=table_name,
            error=str(e),
        )
        return []
