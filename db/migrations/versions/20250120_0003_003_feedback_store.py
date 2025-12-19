"""Add feedback collection table (Issue #16).

Revision ID: 003
Revises: 002
Create Date: 2025-01-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic
revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply migration upgrade."""
    op.create_table(
        "query_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("feedback_id", sa.String(36), nullable=False, unique=True),
        sa.Column("database_id", sa.String(100), nullable=False),
        sa.Column("natural_query", sa.Text(), nullable=False),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column("corrected_sql", sa.Text(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, default="pending"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=True),
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

    op.create_index(
        "ix_query_feedback_feedback_id",
        "query_feedback",
        ["feedback_id"],
    )
    op.create_index(
        "ix_query_feedback_database_id",
        "query_feedback",
        ["database_id"],
    )
    op.create_index(
        "ix_query_feedback_status",
        "query_feedback",
        ["status"],
    )
    op.create_index(
        "ix_query_feedback_created_at",
        "query_feedback",
        ["created_at"],
    )


def downgrade() -> None:
    """Apply migration downgrade."""
    op.drop_index("ix_query_feedback_created_at", table_name="query_feedback")
    op.drop_index("ix_query_feedback_status", table_name="query_feedback")
    op.drop_index("ix_query_feedback_database_id", table_name="query_feedback")
    op.drop_index("ix_query_feedback_feedback_id", table_name="query_feedback")
    op.drop_table("query_feedback")
