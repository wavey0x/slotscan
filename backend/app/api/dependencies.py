"""FastAPI dependency injection."""

from functools import lru_cache

from fastapi import Depends
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.repositories.contracts import ContractRepository
from app.repositories.trace_cache import TraceCacheRepository
from app.repositories.compiler_artifacts import CompilerArtifactRepository
from app.services.decoder import TypeDecoder
from app.services.layout import LayoutParser
from app.services.resolver import ContractResolver
from app.services.storage import StorageReader
from app.services.tracer import TransactionTracer
from app.services.transaction_history import TransactionHistoryService
from app.services.web3_provider import Web3Provider


@lru_cache()
def get_web3_provider() -> Web3Provider:
    """Get cached Web3Provider instance."""
    settings = get_settings()
    return Web3Provider(settings)


def get_decoder() -> TypeDecoder:
    """Get a request-scoped decoder; registries are contract-specific."""
    return TypeDecoder()


@lru_cache()
def get_layout_parser() -> LayoutParser:
    """Get cached LayoutParser instance."""
    return LayoutParser(get_settings())


@lru_cache()
def get_verification_http_client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(timeout=settings.request_timeout_seconds)


async def get_contract_repository(
    session: AsyncSession = Depends(get_session),
) -> ContractRepository:
    """Get ContractRepository with session."""
    return ContractRepository(session)


async def get_compiler_artifact_repository(
    session: AsyncSession = Depends(get_session),
) -> CompilerArtifactRepository:
    return CompilerArtifactRepository(session)


async def get_trace_cache_repository(
    session: AsyncSession = Depends(get_session),
) -> TraceCacheRepository:
    """Get TraceCacheRepository with session."""
    return TraceCacheRepository(session)


async def get_contract_resolver(
    web3_provider: Web3Provider = Depends(get_web3_provider),
    settings: Settings = Depends(get_settings),
    contract_repo: ContractRepository = Depends(get_contract_repository),
    layout_parser: LayoutParser = Depends(get_layout_parser),
    http_client: httpx.AsyncClient = Depends(get_verification_http_client),
    compiler_artifact_repo: CompilerArtifactRepository = Depends(
        get_compiler_artifact_repository
    ),
) -> ContractResolver:
    """Get ContractResolver with dependencies."""
    return ContractResolver(
        web3_provider=web3_provider,
        settings=settings,
        contract_repo=contract_repo,
        layout_parser=layout_parser,
        http_client=http_client,
        compiler_artifact_repo=compiler_artifact_repo,
    )


async def get_storage_reader(
    web3_provider: Web3Provider = Depends(get_web3_provider),
    settings: Settings = Depends(get_settings),
    decoder: TypeDecoder = Depends(get_decoder),
) -> StorageReader:
    """Get StorageReader with dependencies."""
    return StorageReader(
        web3_provider=web3_provider,
        settings=settings,
        decoder=decoder,
    )


async def get_transaction_tracer(
    web3_provider: Web3Provider = Depends(get_web3_provider),
    settings: Settings = Depends(get_settings),
    decoder: TypeDecoder = Depends(get_decoder),
    trace_cache_repo: TraceCacheRepository = Depends(get_trace_cache_repository),
) -> TransactionTracer:
    """Get TransactionTracer with dependencies."""
    return TransactionTracer(
        web3_provider=web3_provider,
        settings=settings,
        decoder=decoder,
        trace_cache_repo=trace_cache_repo,
    )


async def get_transaction_history_service(
    tracer: TransactionTracer = Depends(get_transaction_tracer),
    web3_provider: Web3Provider = Depends(get_web3_provider),
    settings: Settings = Depends(get_settings),
    layout_parser: LayoutParser = Depends(get_layout_parser),
    http_client: httpx.AsyncClient = Depends(get_verification_http_client),
) -> TransactionHistoryService:
    return TransactionHistoryService(
        tracer=tracer,
        web3_provider=web3_provider,
        settings=settings,
        layout_parser=layout_parser,
        http_client=http_client,
    )
