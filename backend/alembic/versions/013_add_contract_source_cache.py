"""Add the persistent source-verification cache.

Revision ID: 013
Revises: 012
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contract_source_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("code_address", sa.String(length=42), nullable=False),
        sa.Column("code_hash", sa.String(length=66), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "checked_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('verified', 'not_found')",
            name="ck_contract_source_cache_status",
        ),
        sa.UniqueConstraint(
            "chain_id",
            "code_address",
            "code_hash",
            name="uq_contract_source_cache_identity",
        ),
    )


def downgrade() -> None:
    op.drop_table("contract_source_cache")
