"""Remove disabled snapshot and contract-projection caches.

Revision ID: 008
Revises: 007
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("tx_diffs_cache")
    op.drop_table("storage_snapshots_cache")


def downgrade() -> None:
    op.create_table(
        "storage_snapshots_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("contract_address", sa.String(length=100), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=True),
        sa.Column("slot_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_snapshots_lookup",
        "storage_snapshots_cache",
        ["chain_id", "contract_address", "block_number"],
        unique=True,
    )
    op.create_table(
        "tx_diffs_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("contract_address", sa.String(length=100), nullable=False),
        sa.Column("tx_hash", sa.String(length=100), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=True),
        sa.Column("change_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_tx_diffs_lookup",
        "tx_diffs_cache",
        ["chain_id", "contract_address", "tx_hash"],
        unique=True,
    )
    op.create_index(
        "idx_tx_diffs_block",
        "tx_diffs_cache",
        ["chain_id", "contract_address", "block_number"],
        unique=False,
    )
