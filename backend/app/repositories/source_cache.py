"""Persistence for normalized source-verification results."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import ContractSourceCache
from app.models.domain import VerificationResult


class SourceCacheRepository:
    """Read and upsert source results by exact runtime-code identity."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(
        self,
        chain_id: int,
        code_address: str,
        code_hash: str,
    ) -> ContractSourceCache | None:
        statement = (
            select(ContractSourceCache)
            .where(
                ContractSourceCache.chain_id == chain_id,
                ContractSourceCache.code_address == code_address.lower(),
                ContractSourceCache.code_hash == code_hash.lower(),
            )
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def save_verified(
        self,
        chain_id: int,
        code_address: str,
        code_hash: str,
        result: VerificationResult,
    ) -> None:
        await self._upsert(
            chain_id=chain_id,
            code_address=code_address,
            code_hash=code_hash,
            status="verified",
            result=result.to_dict(),
        )

    async def save_not_found(
        self,
        chain_id: int,
        code_address: str,
        code_hash: str,
    ) -> None:
        await self._upsert(
            chain_id=chain_id,
            code_address=code_address,
            code_hash=code_hash,
            status="not_found",
            result=None,
        )

    async def _upsert(
        self,
        *,
        chain_id: int,
        code_address: str,
        code_hash: str,
        status: str,
        result: dict | None,
    ) -> None:
        checked_at = datetime.utcnow()
        values = {
            "chain_id": chain_id,
            "code_address": code_address.lower(),
            "code_hash": code_hash.lower(),
            "status": status,
            "result": result,
            "checked_at": checked_at,
        }
        statement = insert(ContractSourceCache).values(**values)
        statement = statement.on_conflict_do_update(
            constraint="uq_contract_source_cache_identity",
            set_={
                "status": status,
                "result": result,
                "checked_at": checked_at,
            },
        )
        await self.session.execute(statement)
        await self.session.commit()
