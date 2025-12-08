"""Initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Contracts table
    op.create_table(
        "contracts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200)),
        sa.Column("code_hash", sa.String(100)),
        sa.Column("is_proxy", sa.Boolean(), default=False),
        sa.Column("proxy_type", sa.String(50)),
        sa.Column("implementation_address", sa.String(100)),
        sa.Column("is_verified", sa.Boolean(), default=False),
        sa.Column("verification_source", sa.String(50)),
        sa.Column("compiler_version", sa.String(50)),
        sa.Column("storage_layout", JSONB()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("verified_at", sa.DateTime()),
    )

    op.create_index(
        "idx_contracts_chain_address", "contracts", ["chain_id", "address"], unique=True
    )

    # Storage snapshots cache
    op.create_table(
        "storage_snapshots_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("contract_address", sa.String(100), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), default=True),
        sa.Column("slot_count", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime()),
    )

    op.create_index(
        "idx_snapshots_lookup",
        "storage_snapshots_cache",
        ["chain_id", "contract_address", "block_number"],
        unique=True,
    )

    # Transaction diffs cache
    op.create_table(
        "tx_diffs_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("contract_address", sa.String(100), nullable=False),
        sa.Column("tx_hash", sa.String(100), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), default=True),
        sa.Column("change_count", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime()),
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
    )


def downgrade() -> None:
    op.drop_table("tx_diffs_cache")
    op.drop_table("storage_snapshots_cache")
    op.drop_table("contracts")
