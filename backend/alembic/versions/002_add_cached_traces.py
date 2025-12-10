"""Add cached_traces table for raw trace data caching

Revision ID: 002
Revises: 001
Create Date: 2024-12-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cached traces table - stores raw trace data before decoding
    op.create_table(
        "cached_traces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("tx_hash", sa.String(66), nullable=False),
        sa.Column("contract_address", sa.String(42), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        # Raw trace data
        sa.Column("raw_changes", JSONB(), nullable=False),  # List of [slot, old, new, pc, index]
        sa.Column("preimage_lookup", JSONB(), nullable=False),  # Dict of {hash: preimage}
        # Metadata
        sa.Column("trace_step_count", sa.Integer()),
        sa.Column("change_count", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_index(
        "idx_cached_traces_lookup",
        "cached_traces",
        ["chain_id", "tx_hash", "contract_address"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("cached_traces")
