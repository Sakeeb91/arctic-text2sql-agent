"""Add few-shot examples table (Issue #16).

Revision ID: 002
Revises: 001
Create Date: 2025-01-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic
revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply migration upgrade."""
    op.create_table(
        "few_shot_examples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("example_id", sa.String(36), nullable=False, unique=True),
        sa.Column("natural_query", sa.Text(), nullable=False),
        sa.Column("sql_query", sa.Text(), nullable=False),
        sa.Column("database_id", sa.String(100), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
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
        "ix_few_shot_examples_example_id",
        "few_shot_examples",
        ["example_id"],
    )
    op.create_index(
        "ix_few_shot_examples_database_id",
        "few_shot_examples",
        ["database_id"],
    )
    op.create_index(
        "ix_few_shot_examples_verified",
        "few_shot_examples",
        ["verified"],
    )
    op.create_index(
        "ix_few_shot_examples_created_at",
        "few_shot_examples",
        ["created_at"],
    )


def downgrade() -> None:
    """Apply migration downgrade."""
    op.drop_index("ix_few_shot_examples_created_at", table_name="few_shot_examples")
    op.drop_index("ix_few_shot_examples_verified", table_name="few_shot_examples")
    op.drop_index("ix_few_shot_examples_database_id", table_name="few_shot_examples")
    op.drop_index("ix_few_shot_examples_example_id", table_name="few_shot_examples")
    op.drop_table("few_shot_examples")
