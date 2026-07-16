"""Track conclusive source verification checks.

Revision ID: 010
Revises: 009
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "contracts",
        sa.Column("source_checked_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "historical_contract_resolutions",
        sa.Column("source_checked_at", sa.DateTime(), nullable=True),
    )
    op.execute(
        """
        UPDATE contracts
        SET source_checked_at = COALESCE(verified_at, updated_at, created_at)
        WHERE is_verified IS TRUE
        """
    )
    op.execute(
        """
        UPDATE historical_contract_resolutions
        SET source_checked_at = created_at
        WHERE is_verified IS TRUE
        """
    )


def downgrade() -> None:
    op.drop_column("historical_contract_resolutions", "source_checked_at")
    op.drop_column("contracts", "source_checked_at")
