"""Transaction-wide storage-owner resolution and projection."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.config import Settings
from app.db import async_session_factory
from app.models.domain import ContractMetadata, StorageLayout, TransactionDiff
from app.models.errors import NotAContractError
from app.repositories.compiler_artifacts import CompilerArtifactRepository
from app.repositories.contracts import ContractRepository
from app.repositories.source_cache import SourceCacheRepository
from app.repositories.trace_cache import TransactionTraceArtifactData
from app.services.layout import LayoutParser
from app.services.resolver import ContractResolver
from app.services.tracer import TransactionAnalysisService
from app.services.tracer.journal import StorageJournal
from app.services.verification import VerificationService
from app.services.web3_provider import Web3Provider


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContractHistoryProjection:
    storage_address: str
    metadata: ContractMetadata | None
    diff: TransactionDiff
    code_addresses: tuple[str, ...]
    display_name: str | None
    layouts_by_code_address: dict[str, StorageLayout]
    resolution_status: str
    errors: tuple[str, ...]


@dataclass(frozen=True)
class TransactionHistoryAnalysis:
    artifact: TransactionTraceArtifactData
    journal: StorageJournal
    contracts: tuple[ContractHistoryProjection, ...]


@dataclass(frozen=True)
class MetadataResolution:
    metadata: ContractMetadata | None
    status: str
    error: str | None = None


class TransactionHistoryService:
    """Resolve and decode every persistent storage owner from one trace."""

    def __init__(
        self,
        tracer: TransactionAnalysisService,
        web3_provider: Web3Provider,
        settings: Settings,
        layout_parser: LayoutParser,
        verification_service: VerificationService,
    ):
        self.tracer = tracer
        self.web3_provider = web3_provider
        self.settings = settings
        self.layout_parser = layout_parser
        self.verification_service = verification_service

    async def analyze(
        self,
        chain_id: int,
        tx_hash: str,
        *,
        storage_addresses: tuple[str, ...] | None = None,
    ) -> TransactionHistoryAnalysis:
        artifact = await self.tracer.load_trace_artifact(chain_id, tx_hash)
        journal = self.tracer.build_journal(artifact)
        owners = storage_addresses or self.tracer.persistent_storage_owners(
            artifact,
            journal,
        )
        code_addresses_by_owner: dict[str, tuple[str, ...]] = {}
        if artifact.capabilities.get("code_attribution_complete", False):
            for event in journal.events:
                if event.namespace.value != "persistent" or not event.code_address:
                    continue
                current = list(code_addresses_by_owner.get(event.address, ()))
                if event.code_address not in current:
                    current.append(event.code_address)
                    code_addresses_by_owner[event.address] = tuple(current)

        semaphore = asyncio.Semaphore(
            max(1, self.settings.max_parallel_contract_resolutions)
        )
        retry_semaphore = asyncio.Semaphore(
            max(1, self.settings.contract_resolution_retry_concurrency)
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.transaction_resolution_budget_seconds

        async def resolve_target(
            target: str,
            *,
            follow_proxy: bool,
            follow_delegation: bool = True,
        ) -> MetadataResolution:
            last_error: Exception | None = None
            for attempt in range(2):
                remaining = deadline - loop.time()
                if remaining <= 0:
                    last_error = TimeoutError("transaction resolution budget exhausted")
                    break
                if attempt:
                    await asyncio.sleep(min(
                        self.settings.contract_resolution_retry_delay_seconds,
                        max(0, remaining),
                    ))
                limiter = semaphore if attempt == 0 else retry_semaphore
                try:
                    async with limiter:
                        remaining = deadline - loop.time()
                        if remaining <= 0:
                            raise TimeoutError(
                                "transaction resolution budget exhausted"
                            )
                        timeout = min(
                            self.settings.contract_resolution_timeout_seconds,
                            remaining,
                        )
                        metadata = await asyncio.wait_for(
                            self._resolve_metadata(
                                chain_id,
                                target,
                                artifact.block_number,
                                follow_proxy=follow_proxy,
                                follow_delegation=follow_delegation,
                            ),
                            timeout=timeout,
                        )
                    return MetadataResolution(
                        metadata=metadata,
                        status=(
                            "resolved"
                            if metadata.is_verified
                            else "no_verified_source"
                        ),
                    )
                except Exception as exc:
                    last_error = exc
                    if isinstance(exc, NotAContractError):
                        break

            assert last_error is not None
            timed_out = isinstance(last_error, (asyncio.TimeoutError, TimeoutError))
            status = "timed_out" if timed_out else "failed"
            return MetadataResolution(
                metadata=None,
                status=status,
                error=(
                    f"{target.lower()}: {type(last_error).__name__}: "
                    "historical resolution failed"
                ),
            )

        owner_results = await asyncio.gather(*(
            resolve_target(owner, follow_proxy=True) for owner in owners
        ))
        owner_resolutions = dict(zip(owners, owner_results))

        direct_resolutions: dict[str, MetadataResolution] = {}
        direct_targets: list[str] = []
        for owner in owners:
            owner_result = owner_resolutions[owner]
            for target in code_addresses_by_owner.get(owner.lower(), ()):
                # Do not repeat an exhausted self-address lookup. A successfully
                # identified proxy still needs a direct pass for its own code.
                if (
                    target == owner.lower()
                    and (
                        owner_result.metadata is None
                        or not owner_result.metadata.is_proxy
                    )
                ):
                    direct_resolutions[target] = owner_result
                elif target not in direct_targets:
                    direct_targets.append(target)

        if direct_targets:
            direct_results = await asyncio.gather(*(
                resolve_target(
                    target,
                    follow_proxy=False,
                    follow_delegation=False,
                )
                for target in direct_targets
            ))
            direct_resolutions.update(zip(direct_targets, direct_results))

        async def project(address: str) -> ContractHistoryProjection:
            owner_resolution = owner_resolutions[address]
            metadata = owner_resolution.metadata
            code_addresses = code_addresses_by_owner.get(address.lower(), ())
            direct_metadata = {
                target: resolution.metadata
                for target in code_addresses
                if (
                    (resolution := direct_resolutions.get(target)) is not None
                    and resolution.metadata is not None
                )
            }

            layouts_by_code_address = {
                target: layout
                for target, resolved in direct_metadata.items()
                if (layout := self._layout(resolved)) is not None and layout.variables
            }
            sources_by_code_address = {
                target: resolved.sources
                for target, resolved in direct_metadata.items()
                if resolved.sources
            }

            diff = self.tracer.project_trace_artifact(
                artifact,
                address,
                layouts_by_code_address=layouts_by_code_address,
                sources_by_code_address=sources_by_code_address,
                journal=journal,
            )
            code_layout_names = [
                layouts_by_code_address[target].contract_name
                for target in code_addresses
                if target in layouts_by_code_address
            ]
            matching_proxy_name = (
                metadata.name
                if metadata
                and metadata.name
                and any(
                    self._names_match(metadata.name, layout_name)
                    for layout_name in code_layout_names
                )
                else None
            )
            display_names = [
                (
                    direct_metadata[address.lower()].name
                    if address.lower() in direct_metadata
                    and not (metadata and metadata.is_proxy)
                    else None
                ),
                matching_proxy_name,
                *code_layout_names,
                *(
                    direct_metadata[target].name
                    if target in direct_metadata
                    else None
                    for target in code_addresses
                ),
                metadata.name if metadata else None,
            ]
            display_name = self._preferred_name(display_names)
            relevant_resolutions = [
                owner_resolution,
                *(
                    direct_resolutions[target]
                    for target in code_addresses
                    if target in direct_resolutions
                    and direct_resolutions[target] is not owner_resolution
                ),
            ]
            errors = tuple(dict.fromkeys(
                resolution.error
                for resolution in relevant_resolutions
                if resolution.error
            ))
            statuses = {resolution.status for resolution in relevant_resolutions}
            if "timed_out" in statuses:
                resolution_status = "timed_out"
            elif "failed" in statuses:
                resolution_status = "failed"
            elif "resolved" in statuses:
                resolution_status = "resolved"
            else:
                resolution_status = "no_verified_source"
            return ContractHistoryProjection(
                storage_address=address.lower(),
                metadata=metadata,
                diff=diff,
                code_addresses=code_addresses,
                display_name=display_name,
                layouts_by_code_address=layouts_by_code_address,
                resolution_status=resolution_status,
                errors=errors,
            )

        projections = await asyncio.gather(*(project(owner) for owner in owners))
        logger.info(
            "Resolved %s storage owners with %s additional unique code addresses",
            len(owner_resolutions),
            len(direct_targets),
        )
        first_steps = {
            event.address: event.step
            for event in reversed(journal.events)
            if event.namespace.value == "persistent"
        }
        projections.sort(
            key=lambda item: (
                first_steps.get(item.storage_address, 2**63 - 1),
                item.storage_address,
            )
        )
        return TransactionHistoryAnalysis(
            artifact=artifact,
            journal=journal,
            contracts=tuple(projections),
        )

    async def _resolve_metadata(
        self,
        chain_id: int,
        address: str,
        block_number: int,
        *,
        follow_proxy: bool = True,
        follow_delegation: bool = True,
    ) -> ContractMetadata:
        # Each concurrent owner receives its own AsyncSession. SQLAlchemy does
        # not permit concurrent operations on one request-scoped session.
        async with async_session_factory() as session:
            resolver = ContractResolver(
                web3_provider=self.web3_provider,
                settings=self.settings,
                verification_service=self.verification_service,
                source_cache_repo=SourceCacheRepository(session),
                contract_repo=ContractRepository(session),
                layout_parser=self.layout_parser,
                compiler_artifact_repo=CompilerArtifactRepository(session),
            )
            return await resolver.resolve(
                chain_id,
                address,
                block_number=block_number,
                follow_proxy=follow_proxy,
                follow_delegation=follow_delegation,
            )

    @staticmethod
    def _preferred_name(candidates: list[str | None]) -> str | None:
        generic = {
            "proxy",
            "appproxyupgradeable",
            "erc1967proxy",
            "fiattokenproxy",
            "ossifiableproxy",
            "vyper_contract",
        }
        return next(
            (name for name in candidates if name and name.lower() not in generic),
            next((name for name in candidates if name), None),
        )

    @staticmethod
    def _names_match(left: str, right: str) -> bool:
        def normalize(value: str) -> str:
            return "".join(
                character.lower() for character in value if character.isalnum()
            )

        return normalize(left) == normalize(right)

    @staticmethod
    def _layout(metadata: ContractMetadata | None) -> StorageLayout | None:
        if not metadata or not metadata.storage_layout:
            return None
        if isinstance(metadata.storage_layout, StorageLayout):
            return metadata.storage_layout
        try:
            return StorageLayout.from_dict(metadata.storage_layout)
        except Exception:
            return None
