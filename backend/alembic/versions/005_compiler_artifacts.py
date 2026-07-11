"""Preserve raw compiler artifacts by build fingerprint.

Revision ID: 005
Revises: 004
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compiler_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("compiler_version", sa.String(length=100), nullable=False),
        sa.Column("pipeline", sa.String(length=50), nullable=False),
        sa.Column("standard_input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("compiler_output", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_hashes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_compiler_artifacts_fingerprint",
        "compiler_artifacts",
        ["fingerprint"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_compiler_artifacts_fingerprint", table_name="compiler_artifacts")
    op.drop_table("compiler_artifacts")
