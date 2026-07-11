"""Retain transaction envelope metadata with shared trace artifacts.

Revision ID: 009
Revises: 008
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transaction_trace_artifacts",
        sa.Column("transaction_from", sa.String(length=42), nullable=True),
    )
    op.add_column(
        "transaction_trace_artifacts",
        sa.Column("transaction_to", sa.String(length=42), nullable=True),
    )
    op.add_column(
        "transaction_trace_artifacts",
        sa.Column("created_contract", sa.String(length=42), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transaction_trace_artifacts", "created_contract")
    op.drop_column("transaction_trace_artifacts", "transaction_to")
    op.drop_column("transaction_trace_artifacts", "transaction_from")
