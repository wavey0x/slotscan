"""Cache repository for snapshots and transaction diffs."""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.database import StorageSnapshotCache, TxDiffCache
from app.models.domain import StorageSnapshot, TransactionDiff


class CacheRepository:
    """Repository for cached snapshots and diffs."""

    def __init__(
        self,
        session: AsyncSession,
        snapshot_ttl_minutes: int = 30,
        tx_diff_ttl_minutes: int = 0,
    ):
        self.session = session
        self.snapshot_ttl_minutes = snapshot_ttl_minutes
        self.tx_diff_ttl_minutes = tx_diff_ttl_minutes

    # Storage Snapshots

    async def get_snapshot(
        self, chain_id: int, contract_address: str, block_number: int
    ) -> Optional[StorageSnapshot]:
        """Get cached storage snapshot (disabled for testing; always miss)."""
        return None

    async def save_snapshot(
        self, snapshot: StorageSnapshot, ttl_minutes: Optional[int] = None
    ) -> None:
        """Disabled for testing; do not cache snapshots."""
        return None

    # Transaction Diffs

    async def get_tx_diff(
        self, chain_id: int, contract_address: str, tx_hash: str
    ) -> Optional[TransactionDiff]:
        """Get cached transaction diff (disabled for testing; always miss)."""
        return None

    async def save_tx_diff(
        self, diff: TransactionDiff, ttl_minutes: Optional[int] = None
    ) -> None:
        """Disabled for testing; do not cache diffs."""
        return None

    # Cache Cleanup

    async def cleanup_expired(self) -> int:
        """Remove expired cache entries. Returns count deleted."""
        now = datetime.utcnow()

        result1 = await self.session.execute(
            delete(StorageSnapshotCache).where(StorageSnapshotCache.expires_at < now)
        )

        result2 = await self.session.execute(
            delete(TxDiffCache).where(TxDiffCache.expires_at < now)
        )

        await self.session.commit()
        return result1.rowcount + result2.rowcount
