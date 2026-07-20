"""Key trace artifacts by exact receipt identity.

Revision ID: 016
Revises: 015
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Trace artifacts are reproducible caches. Clearing them avoids nullable
    # identity columns or a compatibility reader for pre-identity rows.
    op.execute("DELETE FROM transaction_trace_artifacts")
    op.add_column(
        "transaction_trace_artifacts",
        sa.Column("block_hash", sa.String(length=66), nullable=False),
    )
    op.add_column(
        "transaction_trace_artifacts",
        sa.Column("transaction_index", sa.BigInteger(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("transaction_trace_artifacts", "transaction_index")
    op.drop_column("transaction_trace_artifacts", "block_hash")
