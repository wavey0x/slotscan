"""SQLAlchemy database models."""

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
    compiler_artifact_fingerprint = Column(String(64))

    # Storage layout (JSONB)
    storage_layout = Column(JSONB)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    verified_at = Column(DateTime)

    __table_args__ = (
        Index("idx_contracts_chain_address", chain_id, address, unique=True),
        Index("idx_contracts_code_hash", code_hash),
    )


class TransactionTraceArtifact(Base):
    """One versioned, contract-agnostic trace artifact per transaction."""

    __tablename__ = "transaction_trace_artifacts"

    id = Column(Integer, primary_key=True)
    chain_id = Column(Integer, nullable=False)
    tx_hash = Column(String(66), nullable=False)
    trace_schema_version = Column(Integer, nullable=False)
    block_number = Column(BigInteger, nullable=False)
    root_succeeded = Column(Boolean, nullable=False)

    write_events = Column(JSONB, nullable=False)
    prestate_diff = Column(JSONB, nullable=False)
    preimage_lookup = Column(JSONB, nullable=False)
    capabilities = Column(JSONB, nullable=False)

    # Metadata
    trace_step_count = Column(Integer)  # For debugging/monitoring
    write_count = Column(Integer)

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index(
            "idx_transaction_trace_artifacts_lookup",
            chain_id,
            tx_hash,
            trace_schema_version,
            unique=True,
        ),
    )


class LegacyCachedTrace(Base):
    """Read-only schema marker for pre-v2 trace rows retained by migration 004."""

    __tablename__ = "cached_traces_legacy"

    id = Column(Integer, primary_key=True)
    chain_id = Column(Integer, nullable=False)
    tx_hash = Column(String(66), nullable=False)
    contract_address = Column(String(42), nullable=False)
    block_number = Column(BigInteger, nullable=False)
    raw_changes = Column(JSONB, nullable=False)
    preimage_lookup = Column(JSONB, nullable=False)
    trace_step_count = Column(Integer)
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


class CompilerArtifact(Base):
    """Raw, versioned compiler input/output retained for reinterpretation."""

    __tablename__ = "compiler_artifacts"

    id = Column(Integer, primary_key=True)
    fingerprint = Column(String(64), nullable=False)
    language = Column(String(20), nullable=False)
    compiler_version = Column(String(100), nullable=False)
    pipeline = Column(String(50), nullable=False)
    standard_input = Column(JSONB, nullable=False)
    compiler_output = Column(JSONB, nullable=False)
    source_hashes = Column(JSONB, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_compiler_artifacts_fingerprint", fingerprint, unique=True),
    )


class HistoricalContractResolution(Base):
    """Block-specific address-to-implementation/layout association."""

    __tablename__ = "historical_contract_resolutions"

    id = Column(Integer, primary_key=True)
    chain_id = Column(Integer, nullable=False)
    address = Column(String(100), nullable=False)
    block_number = Column(BigInteger, nullable=False)
    code_hash = Column(String(100), nullable=False)
    is_proxy = Column(Boolean, default=False)
    proxy_type = Column(String(50))
    implementation_address = Column(String(100))
    is_verified = Column(Boolean, default=False)
    verification_source = Column(String(50))
    name = Column(String(200))
    compiler_version = Column(String(50))
    compiler_artifact_fingerprint = Column(String(64))
    storage_layout = Column(JSONB)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index(
            "idx_historical_contract_resolution_lookup",
            chain_id,
            address,
            block_number,
            unique=True,
        ),
    )
