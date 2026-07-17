"""Create the current SlotScan schema.

Revision ID: 011
Revises:
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "011"
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
        sa.Column(
            "storage_layout",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
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
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("root_succeeded", sa.Boolean(), nullable=False),
        sa.Column("transaction_from", sa.String(length=42), nullable=True),
        sa.Column("transaction_to", sa.String(length=42), nullable=True),
        sa.Column("created_contract", sa.String(length=42), nullable=True),
        sa.Column(
            "write_events",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "prestate_diff",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "preimage_lookup",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("trace_step_count", sa.Integer(), nullable=True),
        sa.Column("write_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
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
        sa.Column(
            "standard_input",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "compiler_output",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "source_hashes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
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
        sa.Column(
            "storage_layout",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
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


def downgrade() -> None:
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
