"""Replace contract-scoped trace cache with versioned transaction artifacts.

Revision ID: 004
Revises: 003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transaction_trace_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column("trace_schema_version", sa.Integer(), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("root_succeeded", sa.Boolean(), nullable=False),
        sa.Column("write_events", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prestate_diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("preimage_lookup", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trace_step_count", sa.Integer(), nullable=True),
        sa.Column("write_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_transaction_trace_artifacts_lookup",
        "transaction_trace_artifacts",
        ["chain_id", "tx_hash", "trace_schema_version"],
        unique=True,
    )
    # Rows in the old cache cannot be upgraded: they discarded frame outcomes,
    # root status, per-write namespaces, and transaction-wide address evidence.
    # Keep them as an explicitly legacy backup instead of destroying research
    # data during the migration.
    op.rename_table("cached_traces", "cached_traces_legacy")


def downgrade() -> None:
    op.drop_index(
        "idx_transaction_trace_artifacts_lookup",
        table_name="transaction_trace_artifacts",
    )
    op.drop_table("transaction_trace_artifacts")
    op.rename_table("cached_traces_legacy", "cached_traces")
