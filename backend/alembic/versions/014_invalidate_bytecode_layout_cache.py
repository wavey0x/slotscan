"""Invalidate layouts that may have been reused by bytecode hash.

Revision ID: 014
Revises: 013
"""

from typing import Sequence, Union

from alembic import op


revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE contracts SET storage_layout = NULL")
    op.execute(
        "UPDATE historical_contract_resolutions SET storage_layout = NULL"
    )


def downgrade() -> None:
    # Cached layouts are reproducible and cannot be restored after invalidation.
    pass
