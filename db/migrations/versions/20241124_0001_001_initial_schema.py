"""Initial schema with query history table.

Revision ID: 001
Revises:
Create Date: 2024-11-24

This migration creates the initial database schema for the Arctic Text2SQL Agent,
including a query_history table for tracking SQL generation requests.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply migration upgrade."""
    # Create query_history table
    op.create_table(
        "query_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("query_id", sa.String(36), nullable=False, unique=True),
        sa.Column("natural_language_query", sa.Text(), nullable=False),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column("database_id", sa.String(100), nullable=False),
        sa.Column("dialect", sa.String(50), nullable=False, default="postgresql"),
        sa.Column(
            "confidence_score", sa.Float(), nullable=True
        ),
        sa.Column("execution_time_ms", sa.Float(), nullable=True),
        sa.Column("is_valid", sa.Boolean(), nullable=True),
        sa.Column("validation_errors", sa.Text(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # Create index on query_id for fast lookups
    op.create_index("ix_query_history_query_id", "query_history", ["query_id"])

    # Create index on database_id for filtering
    op.create_index("ix_query_history_database_id", "query_history", ["database_id"])

    # Create index on created_at for time-based queries
    op.create_index("ix_query_history_created_at", "query_history", ["created_at"])

    # Create schema_cache table for storing introspected schemas
    op.create_table(
        "schema_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("database_id", sa.String(100), nullable=False, unique=True),
        sa.Column("dialect", sa.String(50), nullable=False),
        sa.Column("schema_json", sa.Text(), nullable=False),
        sa.Column("table_count", sa.Integer(), nullable=False, default=0),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # Create index on database_id for fast lookups
    op.create_index("ix_schema_cache_database_id", "schema_cache", ["database_id"])


def downgrade() -> None:
    """Apply migration downgrade."""
    # Drop indexes
    op.drop_index("ix_schema_cache_database_id", table_name="schema_cache")
    op.drop_index("ix_query_history_created_at", table_name="query_history")
    op.drop_index("ix_query_history_database_id", table_name="query_history")
    op.drop_index("ix_query_history_query_id", table_name="query_history")

    # Drop tables
    op.drop_table("schema_cache")
    op.drop_table("query_history")

