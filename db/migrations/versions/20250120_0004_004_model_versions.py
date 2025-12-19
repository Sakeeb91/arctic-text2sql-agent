"""Add model version registry table (Issue #16).

Revision ID: 004
Revises: 003
Create Date: 2025-01-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic
revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply migration upgrade."""
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version_id", sa.String(36), nullable=False, unique=True),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("base_model", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("metrics", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, default="inactive"),
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
        "ix_model_versions_version_id",
        "model_versions",
        ["version_id"],
    )
    op.create_index(
        "ix_model_versions_status",
        "model_versions",
        ["status"],
    )
    op.create_index(
        "ix_model_versions_created_at",
        "model_versions",
        ["created_at"],
    )


def downgrade() -> None:
    """Apply migration downgrade."""
    op.drop_index("ix_model_versions_created_at", table_name="model_versions")
    op.drop_index("ix_model_versions_status", table_name="model_versions")
    op.drop_index("ix_model_versions_version_id", table_name="model_versions")
    op.drop_table("model_versions")
