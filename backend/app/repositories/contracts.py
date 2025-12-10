"""Contract repository for database operations."""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.database import Contract
from app.models.domain import ContractMetadata, StorageLayout


class ContractRepository:
    """Repository for contract metadata."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, chain_id: int, address: str) -> Optional[Contract]:
        """Get contract by chain and address."""
        result = await self.session.execute(
            select(Contract).where(
                Contract.chain_id == chain_id,
                Contract.address == address.lower(),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_implementation(
        self, chain_id: int, implementation_address: str
    ) -> list[Contract]:
        """Get all proxies pointing to an implementation."""
        result = await self.session.execute(
            select(Contract).where(
                Contract.chain_id == chain_id,
                Contract.implementation_address == implementation_address.lower(),
            )
        )
        return list(result.scalars().all())

    async def get_layout_by_code_hash(self, code_hash: str) -> Optional[Contract]:
        """Find any verified contract with this bytecode hash that has a layout."""
        result = await self.session.execute(
            select(Contract).where(
                Contract.code_hash == code_hash,
                Contract.is_verified == True,
                Contract.storage_layout.isnot(None),
            ).limit(1)
        )
        return result.scalar_one_or_none()

    async def save(self, metadata: ContractMetadata) -> Contract:
        """Save or update contract metadata using upsert."""
        storage_layout_dict = None
        if metadata.storage_layout:
            if isinstance(metadata.storage_layout, dict):
                storage_layout_dict = metadata.storage_layout
            else:
                storage_layout_dict = metadata.storage_layout.to_dict()

        impl_address = None
        if metadata.implementation_address:
            impl_address = metadata.implementation_address.lower()

        values = {
            "chain_id": metadata.chain_id,
            "address": metadata.address.lower(),
            "name": metadata.name,
            "code_hash": metadata.code_hash,
            "is_proxy": metadata.is_proxy,
            "proxy_type": metadata.proxy_type,
            "implementation_address": impl_address,
            "is_verified": metadata.is_verified,
            "verification_source": metadata.verification_source,
            "compiler_version": metadata.compiler_version,
            "storage_layout": storage_layout_dict,
            "verified_at": datetime.utcnow() if metadata.is_verified else None,
        }

        stmt = insert(Contract).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["chain_id", "address"],
            set_={
                "name": values["name"],
                "code_hash": values["code_hash"],
                "is_proxy": values["is_proxy"],
                "proxy_type": values["proxy_type"],
                "implementation_address": values["implementation_address"],
                "is_verified": values["is_verified"],
                "verification_source": values["verification_source"],
                "compiler_version": values["compiler_version"],
                "storage_layout": values["storage_layout"],
                "verified_at": values["verified_at"],
                "updated_at": func.now(),
            },
        )

        await self.session.execute(stmt)
        await self.session.commit()

        return await self.get(metadata.chain_id, metadata.address)

    async def needs_verification_refresh(
        self, chain_id: int, address: str, max_age_hours: int = 24
    ) -> bool:
        """Check if verification status should be rechecked."""
        contract = await self.get(chain_id, address)
        if not contract:
            return True

        if contract.is_verified:
            return False

        if not contract.verified_at:
            return True

        age = datetime.utcnow() - contract.verified_at
        return age.total_seconds() > (max_age_hours * 3600)

    def to_metadata(self, contract: Contract) -> ContractMetadata:
        """Convert database model to domain model."""
        storage_layout = None
        if contract.storage_layout:
            storage_layout = StorageLayout.from_dict(contract.storage_layout)

        return ContractMetadata(
            chain_id=contract.chain_id,
            address=contract.address,
            code_hash=contract.code_hash,
            is_proxy=contract.is_proxy,
            proxy_type=contract.proxy_type,
            implementation_address=contract.implementation_address,
            is_verified=contract.is_verified,
            verification_source=contract.verification_source,
            name=contract.name,
            compiler_version=contract.compiler_version,
            storage_layout=storage_layout,
        )
