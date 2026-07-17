"""Transaction-level trace artifact repository."""

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import TransactionTraceArtifact


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransactionTraceArtifactData:
    chain_id: int
    tx_hash: str
    block_number: int
    root_succeeded: bool
    write_events: list[dict]
    prestate_diff: dict
    preimage_lookup: dict[str, str]
    capabilities: dict
    transaction_from: str | None = None
    transaction_to: str | None = None
    created_contract: str | None = None
    trace_step_count: int | None = None


class TraceCacheRepository:
    """Store raw transaction evidence once; contract projections stay derived."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(
        self,
        chain_id: int,
        tx_hash: str,
    ) -> TransactionTraceArtifactData | None:
        tx_hash_lower = tx_hash.lower()
        stmt = select(TransactionTraceArtifact).where(
            TransactionTraceArtifact.chain_id == chain_id,
            TransactionTraceArtifact.tx_hash == tx_hash_lower,
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None

        logger.info(
            "Trace artifact HIT for tx %s (%s writes)",
            tx_hash_lower[:10],
            row.write_count,
        )
        return TransactionTraceArtifactData(
            chain_id=row.chain_id,
            tx_hash=row.tx_hash,
            block_number=row.block_number,
            root_succeeded=row.root_succeeded,
            transaction_from=row.transaction_from,
            transaction_to=row.transaction_to,
            created_contract=row.created_contract,
            write_events=row.write_events,
            prestate_diff=row.prestate_diff,
            preimage_lookup=row.preimage_lookup,
            capabilities=row.capabilities,
            trace_step_count=row.trace_step_count,
        )

    async def save(self, data: TransactionTraceArtifactData) -> None:
        tx_hash_lower = data.tx_hash.lower()
        values = {
            "chain_id": data.chain_id,
            "tx_hash": tx_hash_lower,
            "block_number": data.block_number,
            "root_succeeded": data.root_succeeded,
            "transaction_from": data.transaction_from,
            "transaction_to": data.transaction_to,
            "created_contract": data.created_contract,
            "write_events": data.write_events,
            "prestate_diff": data.prestate_diff,
            "preimage_lookup": data.preimage_lookup,
            "capabilities": data.capabilities,
            "trace_step_count": data.trace_step_count,
            "write_count": len(data.write_events),
        }
        stmt = insert(TransactionTraceArtifact).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["chain_id", "tx_hash"],
            set_={
                **values,
                "created_at": datetime.utcnow(),
            },
        )
        await self.session.execute(stmt)
        await self.session.commit()
        logger.info(
            "Trace artifact SAVE for tx %s (%s writes)",
            tx_hash_lower[:10],
            len(data.write_events),
        )
