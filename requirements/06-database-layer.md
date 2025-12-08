# Database Layer

## Overview

The Database Layer handles all persistence for StorageScan: contract metadata and storage layouts. For testing, storage-level caching (snapshots and tx diffs) is disabled; every request is computed fresh. Postgres remains the only persistence layer; no Redis or background workers.

## Location

```
backend/app/models/database.py      # SQLAlchemy models
backend/app/repositories/           # Repository classes
backend/alembic/                    # Migrations
```

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `sqlalchemy[asyncio]` | Async ORM |
| `asyncpg` | PostgreSQL async driver |
| `alembic` | Database migrations |

## Database Schema

### Contracts Table

Stores resolved contract metadata including proxy info and storage layout.

```sql
CREATE TABLE contracts (
    id SERIAL PRIMARY KEY,
    chain_id INTEGER NOT NULL,
    address VARCHAR(100) NOT NULL,

    -- Basic info
    name VARCHAR(200),
    code_hash VARCHAR(100),

    -- Proxy info
    is_proxy BOOLEAN DEFAULT FALSE,
    proxy_type VARCHAR(50),                -- 'eip1967', 'eip1822', NULL
    implementation_address VARCHAR(100),

    -- Verification info
    is_verified BOOLEAN DEFAULT FALSE,
    verification_source VARCHAR(50),       -- 'sourcify', 'etherscan', NULL
    compiler_version VARCHAR(50),

    -- Storage layout (JSONB)
    storage_layout JSONB,                  -- Normalized StorageLayout

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    verified_at TIMESTAMP,                 -- When verification was last checked

    -- Constraints
    UNIQUE(chain_id, address)
);

CREATE INDEX idx_contracts_chain_address ON contracts(chain_id, address);
CREATE INDEX idx_contracts_impl ON contracts(implementation_address) WHERE implementation_address IS NOT NULL;
```

### Storage Snapshots Cache (disabled for testing)

Cache tables may exist but reads/writes are skipped during testing; every request recomputes storage.

```sql
CREATE TABLE storage_snapshots_cache (
    id SERIAL PRIMARY KEY,
    chain_id INTEGER NOT NULL,
    contract_address VARCHAR(100) NOT NULL,
    block_number BIGINT NOT NULL,

    -- Cached data (JSONB)
    payload JSONB NOT NULL,               -- StorageSnapshot as JSON

    -- Cache metadata
    is_complete BOOLEAN DEFAULT TRUE,     -- False if truncated
    slot_count INTEGER,                   -- Number of slots in snapshot

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,                 -- Optional TTL for cleanup

    -- Constraints
    UNIQUE(chain_id, contract_address, block_number)
);

CREATE INDEX idx_snapshots_lookup
    ON storage_snapshots_cache(chain_id, contract_address, block_number);
CREATE INDEX idx_snapshots_expiry
    ON storage_snapshots_cache(expires_at)
    WHERE expires_at IS NOT NULL;
```

### Transaction Diffs Cache (disabled for testing)

Cache tables may exist but reads/writes are skipped during testing; every request re-traces transactions.

```sql
CREATE TABLE tx_diffs_cache (
    id SERIAL PRIMARY KEY,
    chain_id INTEGER NOT NULL,
    contract_address VARCHAR(100) NOT NULL,
    tx_hash VARCHAR(100) NOT NULL,
    block_number BIGINT NOT NULL,

    -- Cached data (JSONB)
    payload JSONB NOT NULL,               -- TransactionDiff as JSON

    -- Cache metadata
    is_complete BOOLEAN DEFAULT TRUE,     -- False if truncated
    change_count INTEGER,                 -- Number of changes

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,                 -- Optional TTL

    -- Constraints
    UNIQUE(chain_id, contract_address, tx_hash)
);

CREATE INDEX idx_tx_diffs_lookup
    ON tx_diffs_cache(chain_id, contract_address, tx_hash);
CREATE INDEX idx_tx_diffs_block
    ON tx_diffs_cache(chain_id, contract_address, block_number);
CREATE INDEX idx_tx_diffs_expiry
    ON tx_diffs_cache(expires_at)
    WHERE expires_at IS NOT NULL;
```

## SQLAlchemy Models

```python
# backend/app/models/database.py

from sqlalchemy import Column, Integer, String, Boolean, DateTime, BigInteger, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
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

    # Storage layout
    storage_layout = Column(JSONB)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    verified_at = Column(DateTime)

    __table_args__ = (
        Index('idx_contracts_chain_address', chain_id, address, unique=True),
        Index('idx_contracts_impl', implementation_address,
              postgresql_where=(implementation_address.isnot(None))),
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
        Index('idx_snapshots_lookup', chain_id, contract_address, block_number, unique=True),
        Index('idx_snapshots_expiry', expires_at,
              postgresql_where=(expires_at.isnot(None))),
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
        Index('idx_tx_diffs_lookup', chain_id, contract_address, tx_hash, unique=True),
        Index('idx_tx_diffs_block', chain_id, contract_address, block_number),
        Index('idx_tx_diffs_expiry', expires_at,
              postgresql_where=(expires_at.isnot(None))),
    )
```

## Repository Interfaces

### Contract Repository

```python
# backend/app/repositories/contracts.py

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

class ContractRepository:
    """Repository for contract metadata."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(
        self,
        chain_id: int,
        address: str
    ) -> Optional[Contract]:
        """Get contract by chain and address."""
        result = await self.session.execute(
            select(Contract).where(
                Contract.chain_id == chain_id,
                Contract.address == address.lower()
            )
        )
        return result.scalar_one_or_none()

    async def get_by_implementation(
        self,
        chain_id: int,
        implementation_address: str
    ) -> list[Contract]:
        """Get all proxies pointing to an implementation."""
        result = await self.session.execute(
            select(Contract).where(
                Contract.chain_id == chain_id,
                Contract.implementation_address == implementation_address.lower()
            )
        )
        return result.scalars().all()

    async def save(self, contract: ContractMetadata) -> Contract:
        """
        Save or update contract metadata.

        Uses upsert (INSERT ... ON CONFLICT UPDATE).
        """
        db_contract = Contract(
            chain_id=contract.chain_id,
            address=contract.address.lower(),
            name=contract.name,
            code_hash=contract.code_hash,
            is_proxy=contract.is_proxy,
            proxy_type=contract.proxy_type,
            implementation_address=contract.implementation_address.lower() if contract.implementation_address else None,
            is_verified=contract.is_verified,
            verification_source=contract.verification_source,
            compiler_version=contract.compiler_version,
            storage_layout=contract.storage_layout.to_dict() if contract.storage_layout else None,
            verified_at=datetime.utcnow() if contract.is_verified else None
        )

        # Upsert
        from sqlalchemy.dialects.postgresql import insert
        stmt = insert(Contract).values(
            chain_id=db_contract.chain_id,
            address=db_contract.address,
            name=db_contract.name,
            code_hash=db_contract.code_hash,
            is_proxy=db_contract.is_proxy,
            proxy_type=db_contract.proxy_type,
            implementation_address=db_contract.implementation_address,
            is_verified=db_contract.is_verified,
            verification_source=db_contract.verification_source,
            compiler_version=db_contract.compiler_version,
            storage_layout=db_contract.storage_layout,
            verified_at=db_contract.verified_at
        ).on_conflict_do_update(
            index_elements=['chain_id', 'address'],
            set_={
                'name': db_contract.name,
                'code_hash': db_contract.code_hash,
                'is_proxy': db_contract.is_proxy,
                'proxy_type': db_contract.proxy_type,
                'implementation_address': db_contract.implementation_address,
                'is_verified': db_contract.is_verified,
                'verification_source': db_contract.verification_source,
                'compiler_version': db_contract.compiler_version,
                'storage_layout': db_contract.storage_layout,
                'verified_at': db_contract.verified_at,
                'updated_at': func.now()
            }
        )

        await self.session.execute(stmt)
        await self.session.commit()

        return await self.get(contract.chain_id, contract.address)

    async def needs_verification_refresh(
        self,
        chain_id: int,
        address: str,
        max_age_hours: int = 24
    ) -> bool:
        """Check if verification status should be rechecked."""
        contract = await self.get(chain_id, address)
        if not contract:
            return True

        if contract.is_verified:
            return False  # Already verified, no need to recheck

        if not contract.verified_at:
            return True  # Never checked

        age = datetime.utcnow() - contract.verified_at
        return age.total_seconds() > (max_age_hours * 3600)
```

### Cache Repository

```python
# backend/app/repositories/cache.py

from typing import Optional
from datetime import datetime, timedelta

class CacheRepository:
    """Repository for cached snapshots and diffs."""

    def __init__(self, session: AsyncSession, config: CacheConfig):
        self.session = session
        self.config = config

    # Storage Snapshots

    async def get_snapshot(
        self,
        chain_id: int,
        contract_address: str,
        block_number: int
    ) -> Optional[StorageSnapshot]:
        """Get cached storage snapshot."""
        result = await self.session.execute(
            select(StorageSnapshotCache).where(
                StorageSnapshotCache.chain_id == chain_id,
                StorageSnapshotCache.contract_address == contract_address.lower(),
                StorageSnapshotCache.block_number == block_number
            )
        )
        cache_entry = result.scalar_one_or_none()

        if not cache_entry:
            return None

        # Check expiry
        if cache_entry.expires_at and cache_entry.expires_at < datetime.utcnow():
            return None

        # Deserialize
        return StorageSnapshot.from_dict(cache_entry.payload)

    async def save_snapshot(
        self,
        snapshot: StorageSnapshot,
        ttl_minutes: Optional[int] = None
    ) -> None:
        """Save storage snapshot to cache."""
        ttl = ttl_minutes or self.config.snapshot_ttl_minutes
        expires_at = datetime.utcnow() + timedelta(minutes=ttl) if ttl else None

        from sqlalchemy.dialects.postgresql import insert
        stmt = insert(StorageSnapshotCache).values(
            chain_id=snapshot.chain_id,
            contract_address=snapshot.address.lower(),
            block_number=snapshot.block_number,
            payload=snapshot.to_dict(),
            is_complete=snapshot.is_complete,
            slot_count=len(snapshot.slots),
            expires_at=expires_at
        ).on_conflict_do_update(
            index_elements=['chain_id', 'contract_address', 'block_number'],
            set_={
                'payload': snapshot.to_dict(),
                'is_complete': snapshot.is_complete,
                'slot_count': len(snapshot.slots),
                'expires_at': expires_at,
                'created_at': func.now()
            }
        )

        await self.session.execute(stmt)
        await self.session.commit()

    # Transaction Diffs

    async def get_tx_diff(
        self,
        chain_id: int,
        contract_address: str,
        tx_hash: str
    ) -> Optional[TransactionDiff]:
        """Get cached transaction diff."""
        result = await self.session.execute(
            select(TxDiffCache).where(
                TxDiffCache.chain_id == chain_id,
                TxDiffCache.contract_address == contract_address.lower(),
                TxDiffCache.tx_hash == tx_hash.lower()
            )
        )
        cache_entry = result.scalar_one_or_none()

        if not cache_entry:
            return None

        # Check expiry
        if cache_entry.expires_at and cache_entry.expires_at < datetime.utcnow():
            return None

        return TransactionDiff.from_dict(cache_entry.payload)

    async def save_tx_diff(
        self,
        diff: TransactionDiff,
        ttl_minutes: Optional[int] = None
    ) -> None:
        """Save transaction diff to cache."""
        # Transaction diffs are immutable, so longer TTL or no expiry
        ttl = ttl_minutes or self.config.tx_diff_ttl_minutes
        expires_at = datetime.utcnow() + timedelta(minutes=ttl) if ttl else None

        from sqlalchemy.dialects.postgresql import insert
        stmt = insert(TxDiffCache).values(
            chain_id=diff.chain_id,
            contract_address=diff.contract_address.lower(),
            tx_hash=diff.tx_hash.lower(),
            block_number=diff.block_number,
            payload=diff.to_dict(),
            is_complete=diff.is_complete,
            change_count=len(diff.changes),
            expires_at=expires_at
        ).on_conflict_do_update(
            index_elements=['chain_id', 'contract_address', 'tx_hash'],
            set_={
                'payload': diff.to_dict(),
                'is_complete': diff.is_complete,
                'change_count': len(diff.changes),
                'expires_at': expires_at
            }
        )

        await self.session.execute(stmt)
        await self.session.commit()

    # Cache Cleanup

    async def cleanup_expired(self) -> int:
        """Remove expired cache entries. Returns count deleted."""
        now = datetime.utcnow()

        # Delete expired snapshots
        result1 = await self.session.execute(
            StorageSnapshotCache.__table__.delete().where(
                StorageSnapshotCache.expires_at < now
            )
        )

        # Delete expired tx diffs
        result2 = await self.session.execute(
            TxDiffCache.__table__.delete().where(
                TxDiffCache.expires_at < now
            )
        )

        await self.session.commit()
        return result1.rowcount + result2.rowcount
```

## Database Connection

```python
# backend/app/config.py

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

class DatabaseConfig:
    def __init__(self):
        self.url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://wavey@localhost:5432/storagescan_dev"
        )
        self.pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
        self.max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "10"))


def create_engine(config: DatabaseConfig):
    return create_async_engine(
        config.url,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        echo=False  # Set True for SQL logging
    )


def create_session_factory(engine):
    return sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )


# Usage in FastAPI
async def get_session() -> AsyncSession:
    async with session_factory() as session:
        yield session
```

## Migrations

### Initial Migration

```python
# backend/alembic/versions/001_initial_schema.py

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def upgrade():
    # Contracts table
    op.create_table(
        'contracts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('chain_id', sa.Integer(), nullable=False),
        sa.Column('address', sa.String(100), nullable=False),
        sa.Column('name', sa.String(200)),
        sa.Column('code_hash', sa.String(100)),
        sa.Column('is_proxy', sa.Boolean(), default=False),
        sa.Column('proxy_type', sa.String(50)),
        sa.Column('implementation_address', sa.String(100)),
        sa.Column('is_verified', sa.Boolean(), default=False),
        sa.Column('verification_source', sa.String(50)),
        sa.Column('compiler_version', sa.String(50)),
        sa.Column('storage_layout', JSONB()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('verified_at', sa.DateTime()),
    )

    op.create_index('idx_contracts_chain_address', 'contracts',
                    ['chain_id', 'address'], unique=True)

    # Storage snapshots cache
    op.create_table(
        'storage_snapshots_cache',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('chain_id', sa.Integer(), nullable=False),
        sa.Column('contract_address', sa.String(100), nullable=False),
        sa.Column('block_number', sa.BigInteger(), nullable=False),
        sa.Column('payload', JSONB(), nullable=False),
        sa.Column('is_complete', sa.Boolean(), default=True),
        sa.Column('slot_count', sa.Integer()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime()),
    )

    op.create_index('idx_snapshots_lookup', 'storage_snapshots_cache',
                    ['chain_id', 'contract_address', 'block_number'], unique=True)

    # Transaction diffs cache
    op.create_table(
        'tx_diffs_cache',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('chain_id', sa.Integer(), nullable=False),
        sa.Column('contract_address', sa.String(100), nullable=False),
        sa.Column('tx_hash', sa.String(100), nullable=False),
        sa.Column('block_number', sa.BigInteger(), nullable=False),
        sa.Column('payload', JSONB(), nullable=False),
        sa.Column('is_complete', sa.Boolean(), default=True),
        sa.Column('change_count', sa.Integer()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime()),
    )

    op.create_index('idx_tx_diffs_lookup', 'tx_diffs_cache',
                    ['chain_id', 'contract_address', 'tx_hash'], unique=True)
    op.create_index('idx_tx_diffs_block', 'tx_diffs_cache',
                    ['chain_id', 'contract_address', 'block_number'])


def downgrade():
    op.drop_table('tx_diffs_cache')
    op.drop_table('storage_snapshots_cache')
    op.drop_table('contracts')
```

## Configuration

```python
@dataclass
class CacheConfig:
    # TTL settings (minutes), None = no expiry
    snapshot_ttl_minutes: Optional[int] = 30
    tx_diff_ttl_minutes: Optional[int] = None  # Immutable, no expiry

    # Cleanup settings
    cleanup_interval_minutes: int = 60
    cleanup_batch_size: int = 1000
```

## Cleanup Strategy

- Cache cleanup/TTLs are not used while caching is disabled for testing.

## Testing Strategy

### Unit Tests

1. **Repository methods**
   - CRUD operations
   - Upsert behavior
   - Cache expiry handling

2. **Serialization**
   - StorageLayout to/from JSONB
   - StorageSnapshot to/from JSONB
   - TransactionDiff to/from JSONB

### Integration Tests

1. **Database operations**
   - Connection handling
   - Transaction rollback
   - Concurrent access

2. **Cache behavior**
   - TTL expiration
   - Cleanup job
   - Cache hit/miss

## Example Usage

```python
# In service layer
async def get_contract_with_cache(
    chain_id: int,
    address: str,
    contract_repo: ContractRepository,
    resolver: ContractResolver
) -> ContractMetadata:
    """Get contract, using cache if available."""

    # Check cache
    cached = await contract_repo.get(chain_id, address)
    if cached and not await contract_repo.needs_verification_refresh(chain_id, address):
        return ContractMetadata.from_db(cached)

    # Resolve fresh
    metadata = await resolver.resolve(chain_id, address)

    # Save to cache
    await contract_repo.save(metadata)

    return metadata
```
