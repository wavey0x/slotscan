"""Trace cache repository for raw trace data."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import CachedTrace

logger = logging.getLogger(__name__)


@dataclass
class CachedTraceData:
    """Raw trace data to cache (before decoding)."""

    chain_id: int
    tx_hash: str
    contract_address: str
    block_number: int
    raw_changes: list[tuple[str, str, str, int | None, int]]  # (slot, old, new, pc, index)
    preimage_lookup: dict[str, str]  # hash -> preimage
    trace_step_count: int = 0


class TraceCacheRepository:
    """Repository for cached raw trace data.

    Caches the raw-ish trace data (after RPC, before decoding) to avoid
    expensive RPC calls on repeated requests.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(
        self, chain_id: int, tx_hash: str, contract_address: str
    ) -> Optional[CachedTraceData]:
        """Get cached trace data if exists."""
        tx_hash_lower = tx_hash.lower()
        address_lower = contract_address.lower()

        stmt = select(CachedTrace).where(
            CachedTrace.chain_id == chain_id,
            CachedTrace.tx_hash == tx_hash_lower,
            CachedTrace.contract_address == address_lower,
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()

        if row is None:
            return None

        logger.info(
            f"Cache HIT for tx {tx_hash_lower[:10]}... contract {address_lower[:10]}... "
            f"({row.change_count} changes, {row.trace_step_count} steps)"
        )

        # Convert JSONB lists back to tuples
        raw_changes = [
            (c[0], c[1], c[2], c[3], c[4]) for c in row.raw_changes
        ]

        return CachedTraceData(
            chain_id=row.chain_id,
            tx_hash=row.tx_hash,
            contract_address=row.contract_address,
            block_number=row.block_number,
            raw_changes=raw_changes,
            preimage_lookup=row.preimage_lookup,
            trace_step_count=row.trace_step_count or 0,
        )

    async def save(self, data: CachedTraceData) -> None:
        """Save trace data to cache (upsert)."""
        tx_hash_lower = data.tx_hash.lower()
        address_lower = data.contract_address.lower()

        # Convert tuples to lists for JSONB storage
        raw_changes_json = [list(c) for c in data.raw_changes]

        stmt = insert(CachedTrace).values(
            chain_id=data.chain_id,
            tx_hash=tx_hash_lower,
            contract_address=address_lower,
            block_number=data.block_number,
            raw_changes=raw_changes_json,
            preimage_lookup=data.preimage_lookup,
            trace_step_count=data.trace_step_count,
            change_count=len(data.raw_changes),
        )

        # On conflict, update the data
        stmt = stmt.on_conflict_do_update(
            index_elements=["chain_id", "tx_hash", "contract_address"],
            set_={
                "raw_changes": raw_changes_json,
                "preimage_lookup": data.preimage_lookup,
                "trace_step_count": data.trace_step_count,
                "change_count": len(data.raw_changes),
                "created_at": datetime.utcnow(),
            },
        )

        await self.session.execute(stmt)
        await self.session.commit()

        logger.info(
            f"Cache SAVE for tx {tx_hash_lower[:10]}... contract {address_lower[:10]}... "
            f"({len(data.raw_changes)} changes, {data.trace_step_count} steps)"
        )
