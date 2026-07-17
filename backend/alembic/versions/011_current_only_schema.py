"""Discard obsolete caches and internal payload generations.

Revision ID: 011
Revises: 010
"""

from typing import Sequence, Union

from alembic import op


revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("cached_traces_legacy")

    # Trace artifacts are disposable caches. Current code reads exactly one
    # payload shape, so invalidate existing rows instead of carrying a format
    # generation in every key and deserializer.
    op.execute("TRUNCATE TABLE transaction_trace_artifacts")
    op.drop_index(
        "idx_transaction_trace_artifacts_lookup",
        table_name="transaction_trace_artifacts",
    )
    op.drop_column("transaction_trace_artifacts", "trace_schema_version")
    op.create_index(
        "idx_transaction_trace_artifacts_lookup",
        "transaction_trace_artifacts",
        ["chain_id", "tx_hash"],
        unique=True,
    )

    # Layout inference is current-only as well. Re-resolve layouts on demand
    # rather than teaching the resolver how to preserve old payload variants.
    op.execute(
        "UPDATE contracts "
        "SET storage_layout = NULL, source_checked_at = NULL"
    )
    op.execute(
        "UPDATE historical_contract_resolutions "
        "SET storage_layout = NULL, source_checked_at = NULL"
    )


def downgrade() -> None:
    raise RuntimeError("SlotScan development cache resets are intentionally irreversible")
