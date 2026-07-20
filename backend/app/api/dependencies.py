"""FastAPI dependency injection."""

from functools import lru_cache

from fastapi import Depends
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.repositories.contracts import ContractRepository
from app.repositories.compiler_artifacts import CompilerArtifactRepository
from app.repositories.source_cache import SourceCacheRepository
from app.repositories.trace_cache import TraceCacheRepository
from app.services.decoder import TypeDecoder
from app.services.layout import LayoutParser
from app.services.layout_compatibility.compare import LayoutComparator
from app.services.layout_compatibility.normalize import LayoutNormalizer
from app.services.layout_compatibility.service import LayoutComparisonService
from app.services.resolver import ContractResolver
from app.services.storage_view import StorageViewService
from app.services.tracer import TransactionAnalysisService
from app.services.tracer.tracer import TraceSingleFlight
from app.services.transaction_history import TransactionHistoryService
from app.services.transaction_response_cache import TransactionResponseCache
from app.services.verification import VerificationService
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


@lru_cache()
def get_verification_service() -> VerificationService:
    return VerificationService(
        settings=get_settings(),
        http_client=get_verification_http_client(),
    )


async def get_contract_repository(
    session: AsyncSession = Depends(get_session),
) -> ContractRepository:
    """Get ContractRepository with session."""
    return ContractRepository(session)


async def get_compiler_artifact_repository(
    session: AsyncSession = Depends(get_session),
) -> CompilerArtifactRepository:
    return CompilerArtifactRepository(session)


async def get_source_cache_repository(
    session: AsyncSession = Depends(get_session),
) -> SourceCacheRepository:
    return SourceCacheRepository(session)


async def get_trace_cache_repository(
    session: AsyncSession = Depends(get_session),
) -> TraceCacheRepository:
    """Get TraceCacheRepository with session."""
    return TraceCacheRepository(session)


@lru_cache()
def get_trace_single_flight() -> TraceSingleFlight:
    return TraceSingleFlight()


@lru_cache()
def get_transaction_response_cache() -> TransactionResponseCache:
    settings = get_settings()
    return TransactionResponseCache(
        settings.transaction_response_cache_bytes,
        terminal_response_ttl_seconds=(
            settings.terminal_response_cache_ttl_seconds
        ),
    )


async def get_contract_resolver(
    web3_provider: Web3Provider = Depends(get_web3_provider),
    settings: Settings = Depends(get_settings),
    contract_repo: ContractRepository = Depends(get_contract_repository),
    source_cache_repo: SourceCacheRepository = Depends(
        get_source_cache_repository
    ),
    layout_parser: LayoutParser = Depends(get_layout_parser),
    verification_service: VerificationService = Depends(
        get_verification_service
    ),
    compiler_artifact_repo: CompilerArtifactRepository = Depends(
        get_compiler_artifact_repository
    ),
) -> ContractResolver:
    """Get ContractResolver with dependencies."""
    return ContractResolver(
        web3_provider=web3_provider,
        settings=settings,
        verification_service=verification_service,
        source_cache_repo=source_cache_repo,
        contract_repo=contract_repo,
        layout_parser=layout_parser,
        compiler_artifact_repo=compiler_artifact_repo,
    )


async def get_storage_view_service(
    web3_provider: Web3Provider = Depends(get_web3_provider),
    resolver: ContractResolver = Depends(get_contract_resolver),
    layout_parser: LayoutParser = Depends(get_layout_parser),
    settings: Settings = Depends(get_settings),
    decoder: TypeDecoder = Depends(get_decoder),
) -> StorageViewService:
    return StorageViewService(
        web3_provider=web3_provider,
        resolver=resolver,
        layout_parser=layout_parser,
        settings=settings,
        decoder=decoder,
    )


async def get_layout_comparison_service(
    web3_provider: Web3Provider = Depends(get_web3_provider),
    storage_view_service: StorageViewService = Depends(get_storage_view_service),
    settings: Settings = Depends(get_settings),
) -> LayoutComparisonService:
    normalizer = LayoutNormalizer(
        max_depth=settings.comparison_max_depth,
        max_visited_types=settings.comparison_max_type_visits,
    )
    comparator = LayoutComparator(
        normalizer=normalizer,
        max_entries=settings.comparison_max_entries,
        max_details_per_entry=settings.comparison_max_detail_lines,
        max_detail_length=settings.comparison_max_detail_chars,
    )
    return LayoutComparisonService(
        web3_provider=web3_provider,
        storage_view_service=storage_view_service,
        normalizer=normalizer,
        comparator=comparator,
    )


async def get_transaction_analysis_service(
    web3_provider: Web3Provider = Depends(get_web3_provider),
    settings: Settings = Depends(get_settings),
    decoder: TypeDecoder = Depends(get_decoder),
    trace_cache_repo: TraceCacheRepository = Depends(get_trace_cache_repository),
    single_flight: TraceSingleFlight = Depends(get_trace_single_flight),
) -> TransactionAnalysisService:
    """Get the transaction analysis service with dependencies."""
    return TransactionAnalysisService(
        web3_provider=web3_provider,
        settings=settings,
        decoder=decoder,
        trace_cache_repo=trace_cache_repo,
        single_flight=single_flight,
    )


async def get_transaction_history_service(
    tracer: TransactionAnalysisService = Depends(get_transaction_analysis_service),
    web3_provider: Web3Provider = Depends(get_web3_provider),
    settings: Settings = Depends(get_settings),
    layout_parser: LayoutParser = Depends(get_layout_parser),
    verification_service: VerificationService = Depends(
        get_verification_service
    ),
) -> TransactionHistoryService:
    return TransactionHistoryService(
        tracer=tracer,
        web3_provider=web3_provider,
        settings=settings,
        layout_parser=layout_parser,
        verification_service=verification_service,
    )
