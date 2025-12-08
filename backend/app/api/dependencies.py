"""FastAPI dependency injection."""

from functools import lru_cache
from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.repositories.cache import CacheRepository
from app.repositories.contracts import ContractRepository
from app.services.decoder import TypeDecoder
from app.services.layout import LayoutParser
from app.services.resolver import ContractResolver
from app.services.storage import StorageReader
from app.services.tracer import TransactionTracer
from app.services.web3_provider import Web3Provider


@lru_cache()
def get_web3_provider() -> Web3Provider:
    """Get cached Web3Provider instance."""
    settings = get_settings()
    return Web3Provider(settings)


@lru_cache()
def get_decoder() -> TypeDecoder:
    """Get cached TypeDecoder instance."""
    return TypeDecoder()


@lru_cache()
def get_layout_parser() -> LayoutParser:
    """Get cached LayoutParser instance."""
    return LayoutParser()


async def get_contract_repository(
    session: AsyncSession = Depends(get_session),
) -> ContractRepository:
    """Get ContractRepository with session."""
    return ContractRepository(session)


async def get_cache_repository(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> CacheRepository:
    """Get CacheRepository with session."""
    return CacheRepository(
        session,
        snapshot_ttl_minutes=settings.cache_snapshot_ttl_minutes,
        tx_diff_ttl_minutes=settings.cache_tx_diff_ttl_minutes,
    )


async def get_contract_resolver(
    web3_provider: Web3Provider = Depends(get_web3_provider),
    settings: Settings = Depends(get_settings),
    contract_repo: ContractRepository = Depends(get_contract_repository),
    layout_parser: LayoutParser = Depends(get_layout_parser),
) -> ContractResolver:
    """Get ContractResolver with dependencies."""
    return ContractResolver(
        web3_provider=web3_provider,
        settings=settings,
        contract_repo=contract_repo,
        layout_parser=layout_parser,
    )


async def get_storage_reader(
    web3_provider: Web3Provider = Depends(get_web3_provider),
    settings: Settings = Depends(get_settings),
    decoder: TypeDecoder = Depends(get_decoder),
    cache_repo: CacheRepository = Depends(get_cache_repository),
) -> StorageReader:
    """Get StorageReader with dependencies."""
    return StorageReader(
        web3_provider=web3_provider,
        settings=settings,
        decoder=decoder,
        cache_repo=cache_repo,
    )


async def get_transaction_tracer(
    web3_provider: Web3Provider = Depends(get_web3_provider),
    settings: Settings = Depends(get_settings),
    decoder: TypeDecoder = Depends(get_decoder),
    cache_repo: CacheRepository = Depends(get_cache_repository),
) -> TransactionTracer:
    """Get TransactionTracer with dependencies."""
    return TransactionTracer(
        web3_provider=web3_provider,
        settings=settings,
        decoder=decoder,
        cache_repo=cache_repo,
    )
