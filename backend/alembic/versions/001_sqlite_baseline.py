"""Create the SQLite SlotScan cache schema.

Revision ID: 001
Revises:
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("code_hash", sa.String(length=100), nullable=True),
        sa.Column("is_proxy", sa.Boolean(), nullable=True),
        sa.Column("proxy_type", sa.String(length=50), nullable=True),
        sa.Column("implementation_address", sa.String(length=100), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=True),
        sa.Column("verification_source", sa.String(length=50), nullable=True),
        sa.Column("compiler_version", sa.String(length=50), nullable=True),
        sa.Column(
            "compiler_artifact_fingerprint",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column("layout_provenance", sa.String(length=32), nullable=True),
        sa.Column("layout_source_address", sa.String(length=100), nullable=True),
        sa.Column("storage_layout", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("source_checked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_contracts_chain_address",
        "contracts",
        ["chain_id", "address"],
        unique=True,
    )
    op.create_index(
        "idx_contracts_code_hash",
        "contracts",
        ["code_hash"],
        unique=False,
    )

    op.create_table(
        "transaction_trace_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column("block_hash", sa.String(length=66), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("transaction_index", sa.BigInteger(), nullable=False),
        sa.Column("root_succeeded", sa.Boolean(), nullable=False),
        sa.Column("transaction_from", sa.String(length=42), nullable=True),
        sa.Column("transaction_to", sa.String(length=42), nullable=True),
        sa.Column("created_contract", sa.String(length=42), nullable=True),
        sa.Column("write_events", sa.JSON(), nullable=False),
        sa.Column("prestate_diff", sa.JSON(), nullable=False),
        sa.Column("preimage_lookup", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("trace_step_count", sa.Integer(), nullable=True),
        sa.Column("write_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_transaction_trace_artifacts_lookup",
        "transaction_trace_artifacts",
        ["chain_id", "tx_hash"],
        unique=True,
    )

    op.create_table(
        "compiler_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("compiler_version", sa.String(length=100), nullable=False),
        sa.Column("pipeline", sa.String(length=50), nullable=False),
        sa.Column("standard_input", sa.JSON(), nullable=False),
        sa.Column("compiler_output", sa.JSON(), nullable=False),
        sa.Column("source_hashes", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_compiler_artifacts_fingerprint",
        "compiler_artifacts",
        ["fingerprint"],
        unique=True,
    )

    op.create_table(
        "historical_contract_resolutions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(length=100), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("code_hash", sa.String(length=100), nullable=False),
        sa.Column("is_proxy", sa.Boolean(), nullable=True),
        sa.Column("proxy_type", sa.String(length=50), nullable=True),
        sa.Column("implementation_address", sa.String(length=100), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=True),
        sa.Column("verification_source", sa.String(length=50), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("compiler_version", sa.String(length=50), nullable=True),
        sa.Column(
            "compiler_artifact_fingerprint",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column("layout_provenance", sa.String(length=32), nullable=True),
        sa.Column("layout_source_address", sa.String(length=100), nullable=True),
        sa.Column("storage_layout", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column("source_checked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_historical_contract_resolution_lookup",
        "historical_contract_resolutions",
        ["chain_id", "address", "block_number"],
        unique=True,
    )

    op.create_table(
        "contract_source_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("code_address", sa.String(length=42), nullable=False),
        sa.Column("code_hash", sa.String(length=66), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column(
            "checked_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
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
    op.drop_index(
        "idx_historical_contract_resolution_lookup",
        table_name="historical_contract_resolutions",
    )
    op.drop_table("historical_contract_resolutions")
    op.drop_index(
        "idx_compiler_artifacts_fingerprint",
        table_name="compiler_artifacts",
    )
    op.drop_table("compiler_artifacts")
    op.drop_index(
        "idx_transaction_trace_artifacts_lookup",
        table_name="transaction_trace_artifacts",
    )
    op.drop_table("transaction_trace_artifacts")
    op.drop_index("idx_contracts_code_hash", table_name="contracts")
    op.drop_index("idx_contracts_chain_address", table_name="contracts")
    op.drop_table("contracts")
