"""Invalidate cached layouts after adding first-class storage scopes.

Revision ID: 012
Revises: 011
"""

from typing import Sequence, Union

from alembic import op


revision: str = "012"
down_revision: Union[str, None] = "011"
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
