"""Add index on code_hash for bytecode cache lookups

Revision ID: 003
Revises: 002
Create Date: 2024-12-09

"""
from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_contracts_code_hash",
        "contracts",
        ["code_hash"],
    )


def downgrade() -> None:
    op.drop_index("idx_contracts_code_hash", "contracts")
