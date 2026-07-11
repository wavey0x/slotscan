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
    display_name: str | None
    layouts_by_code_address: dict[str, StorageLayout]
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
            code_addresses = code_addresses_by_owner.get(address.lower(), ())

            async def guarded_resolve(
                target: str,
                *,
                follow_proxy: bool,
            ) -> ContractMetadata | None:
                try:
                    async with semaphore:
                        return await asyncio.wait_for(
                            self._resolve_metadata(
                                chain_id,
                                target,
                                artifact.block_number,
                                follow_proxy=follow_proxy,
                            ),
                            timeout=self.settings.contract_resolution_timeout_seconds,
                        )
                except Exception as exc:
                    message = (
                        f"{target.lower()}: {type(exc).__name__}: "
                        "historical resolution failed"
                    )
                    if message not in errors:
                        errors.append(message)
                    return None

            metadata_task = guarded_resolve(address, follow_proxy=True)
            direct_addresses = tuple(dict.fromkeys((address.lower(), *code_addresses)))
            direct_results = await asyncio.gather(
                *(guarded_resolve(target, follow_proxy=False) for target in direct_addresses),
                metadata_task,
            )
            metadata = direct_results[-1]
            direct_metadata = {
                target: result
                for target, result in zip(direct_addresses, direct_results[:-1])
                if result is not None
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
            fallback_layout = self._layout(metadata)
            if fallback_layout and fallback_layout.variables:
                for target in code_addresses:
                    layouts_by_code_address.setdefault(target, fallback_layout)
            all_layouts = list(layouts_by_code_address.values())
            if fallback_layout and fallback_layout.variables:
                all_layouts.append(fallback_layout)
            combined_layout = self._combine_layouts(all_layouts)

            fallback_sources = metadata.sources if metadata else None
            diff = self.tracer.project_trace_artifact(
                artifact,
                address,
                layout=combined_layout,
                sources=fallback_sources,
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
            return ContractHistoryProjection(
                storage_address=address.lower(),
                metadata=metadata,
                diff=diff,
                code_addresses=code_addresses,
                display_name=display_name,
                layouts_by_code_address=layouts_by_code_address,
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
        *,
        follow_proxy: bool = True,
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
                follow_proxy=follow_proxy,
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
    def _combine_layouts(layouts: list[StorageLayout]) -> StorageLayout | None:
        if not layouts:
            return None
        variables = {}
        types = {}
        for layout in layouts:
            types.update(layout.types)
            for variable in layout.variables:
                variables[
                    (variable.name, variable.slot, variable.offset, variable.type_id)
                ] = variable
        return StorageLayout(
            contract_name=" + ".join(dict.fromkeys(
                layout.contract_name for layout in layouts if layout.contract_name
            )),
            variables=list(variables.values()),
            types=types,
            resolver_version=max(layout.resolver_version for layout in layouts),
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
