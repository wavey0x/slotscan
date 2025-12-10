"""SQLAlchemy database models."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, BigInteger, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class Contract(Base):
    """Contract metadata and storage layout."""

    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True)
    chain_id = Column(Integer, nullable=False)
    address = Column(String(100), nullable=False)

    # Basic info
    name = Column(String(200))
    code_hash = Column(String(100))

    # Proxy info
    is_proxy = Column(Boolean, default=False)
    proxy_type = Column(String(50))
    implementation_address = Column(String(100))

    # Verification info
    is_verified = Column(Boolean, default=False)
    verification_source = Column(String(50))
    compiler_version = Column(String(50))

    # Storage layout (JSONB)
    storage_layout = Column(JSONB)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    verified_at = Column(DateTime)

    __table_args__ = (
        Index("idx_contracts_chain_address", chain_id, address, unique=True),
    )


class StorageSnapshotCache(Base):
    """Cached storage state at a block."""

    __tablename__ = "storage_snapshots_cache"

    id = Column(Integer, primary_key=True)
    chain_id = Column(Integer, nullable=False)
    contract_address = Column(String(100), nullable=False)
    block_number = Column(BigInteger, nullable=False)

    payload = Column(JSONB, nullable=False)
    is_complete = Column(Boolean, default=True)
    slot_count = Column(Integer)

    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime)

    __table_args__ = (
        Index(
            "idx_snapshots_lookup",
            chain_id,
            contract_address,
            block_number,
            unique=True,
        ),
    )


class TxDiffCache(Base):
    """Cached transaction storage diff."""

    __tablename__ = "tx_diffs_cache"

    id = Column(Integer, primary_key=True)
    chain_id = Column(Integer, nullable=False)
    contract_address = Column(String(100), nullable=False)
    tx_hash = Column(String(100), nullable=False)
    block_number = Column(BigInteger, nullable=False)

    payload = Column(JSONB, nullable=False)
    is_complete = Column(Boolean, default=True)
    change_count = Column(Integer)

    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime)

    __table_args__ = (
        Index("idx_tx_diffs_lookup", chain_id, contract_address, tx_hash, unique=True),
        Index("idx_tx_diffs_block", chain_id, contract_address, block_number),
    )


class CachedTrace(Base):
    """Cached raw trace data (before decoding).

    Stores the raw-ish trace data after RPC calls but before variable resolution.
    This is future-proof: decoding logic changes don't invalidate cache.
    """

    __tablename__ = "cached_traces"

    id = Column(Integer, primary_key=True)
    chain_id = Column(Integer, nullable=False)
    tx_hash = Column(String(66), nullable=False)
    contract_address = Column(String(42), nullable=False)
    block_number = Column(BigInteger, nullable=False)

    # Raw trace data (JSONB for flexibility)
    # raw_changes: List of [slot, old_value, new_value, pc, exec_index]
    raw_changes = Column(JSONB, nullable=False)
    # preimage_lookup: Dict of {hash: preimage} for mapping key resolution
    preimage_lookup = Column(JSONB, nullable=False)

    # Metadata
    trace_step_count = Column(Integer)  # For debugging/monitoring
    change_count = Column(Integer)

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index(
            "idx_cached_traces_lookup",
            chain_id,
            tx_hash,
            contract_address,
            unique=True,
        ),
    )
