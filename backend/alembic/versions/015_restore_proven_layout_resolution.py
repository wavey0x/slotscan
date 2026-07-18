"""Restore proven layout resolution with explicit provenance.

Revision ID: 015
Revises: 014
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "contracts",
        sa.Column("layout_provenance", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "contracts",
        sa.Column("layout_source_address", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "historical_contract_resolutions",
        sa.Column("layout_provenance", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "historical_contract_resolutions",
        sa.Column("layout_source_address", sa.String(length=100), nullable=True),
    )

    # These tables are reproducible caches. Clear them once so every retained
    # row has explicit layout provenance and every trace contains observed
    # dynamic-array length evidence.
    op.execute("DELETE FROM transaction_trace_artifacts")
    op.execute("DELETE FROM historical_contract_resolutions")
    op.execute("DELETE FROM contracts")


def downgrade() -> None:
    op.drop_column(
        "historical_contract_resolutions",
        "layout_source_address",
    )
    op.drop_column(
        "historical_contract_resolutions",
        "layout_provenance",
    )
    op.drop_column("contracts", "layout_source_address")
    op.drop_column("contracts", "layout_provenance")
