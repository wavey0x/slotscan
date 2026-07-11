"""Transaction-wide storage-owner resolution and projection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.config import Settings
from app.db import async_session_factory
from app.models.domain import ContractMetadata, StorageLayout, TransactionDiff
from app.repositories.compiler_artifacts import CompilerArtifactRepository
from app.repositories.contracts import ContractRepository
from app.repositories.trace_cache import TransactionTraceArtifactData
from app.services.layout import LayoutParser
from app.services.resolver import ContractResolver
from app.services.tracer import TransactionTracer
from app.services.tracer.journal import StorageJournal
from app.services.web3_provider import Web3Provider


@dataclass(frozen=True)
class ContractHistoryProjection:
    storage_address: str
    metadata: ContractMetadata | None
    diff: TransactionDiff
    code_addresses: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class TransactionHistoryAnalysis:
    artifact: TransactionTraceArtifactData
    journal: StorageJournal
    contracts: tuple[ContractHistoryProjection, ...]


class TransactionHistoryService:
    """Resolve and decode every persistent storage owner from one trace."""

    def __init__(
        self,
        tracer: TransactionTracer,
        web3_provider: Web3Provider,
        settings: Settings,
        layout_parser: LayoutParser,
        http_client,
    ):
        self.tracer = tracer
        self.web3_provider = web3_provider
        self.settings = settings
        self.layout_parser = layout_parser
        self.http_client = http_client

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

        async def project(address: str) -> ContractHistoryProjection:
            metadata: ContractMetadata | None = None
            errors: list[str] = []
            try:
                async with semaphore:
                    metadata = await asyncio.wait_for(
                        self._resolve_metadata(
                            chain_id,
                            address,
                            artifact.block_number,
                        ),
                        timeout=self.settings.contract_resolution_timeout_seconds,
                    )
            except Exception as exc:
                # Resolution is enrichment. Raw storage history for this owner
                # remains valid and must not make the transaction request fail.
                errors.append(
                    f"{type(exc).__name__}: historical resolution failed"
                )

            layout = self._layout(metadata)
            diff = self.tracer.project_trace_artifact(
                artifact,
                address,
                layout=layout,
                sources=metadata.sources if metadata else None,
                journal=journal,
            )
            return ContractHistoryProjection(
                storage_address=address.lower(),
                metadata=metadata,
                diff=diff,
                code_addresses=code_addresses_by_owner.get(address.lower(), ()),
                errors=tuple(errors),
            )

        projections = await asyncio.gather(*(project(owner) for owner in owners))
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
    ) -> ContractMetadata:
        # Each concurrent owner receives its own AsyncSession. SQLAlchemy does
        # not permit concurrent operations on one request-scoped session.
        async with async_session_factory() as session:
            resolver = ContractResolver(
                web3_provider=self.web3_provider,
                settings=self.settings,
                contract_repo=ContractRepository(session),
                layout_parser=self.layout_parser,
                http_client=self.http_client,
                compiler_artifact_repo=CompilerArtifactRepository(session),
            )
            return await resolver.resolve(
                chain_id,
                address,
                block_number=block_number,
                sourcify_layout_only=True,
            )

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
