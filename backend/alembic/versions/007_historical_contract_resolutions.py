"""Cache block-specific contract implementation/layout associations.

Revision ID: 007
Revises: 006
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
        sa.Column("compiler_artifact_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("storage_layout", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
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
