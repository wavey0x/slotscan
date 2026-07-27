"""Coherent exact-block storage view service."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from web3 import Web3

from app.config import Settings
from app.models.domain import ContractMetadata, StorageLayout
from app.services.compiled_layout import (
    CompiledLayout,
    CompiledType,
    UnsupportedCompiledLayout,
    compile_layout,
)
from app.services.decoder import TypeDecoder
from app.services.layout import LayoutParser
from app.services.resolver import ContractResolver
from app.services.storage import (
    StorageReader,
    is_solidity_dynamic_bytes,
    plan_compiled_scalar_reads,
)
from app.services.storage_query import (
    StorageQueryEngine,
    StorageQueryError,
)
from app.services.web3_provider import StorageAttempt, Web3Provider


@dataclass(frozen=True)
class StorageContext:
    attempt: StorageAttempt
    metadata: ContractMetadata
    layout: CompiledLayout | None
    layout_status: str


def _wire_decoded(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return [_wire_decoded(item) for item in value]
    if isinstance(value, dict):
        return {key: _wire_decoded(item) for key, item in value.items()}
    return value


def _hashed_array_root(slot: int) -> int:
    return int.from_bytes(Web3.keccak(slot.to_bytes(32, "big")), "big")


def _base_storage_provenance(
    layout: CompiledLayout,
    type_info: CompiledType,
    slot: int,
) -> dict[str, list[dict[str, str | None]]] | None:
    if type_info.encoding == "mapping":
        return {
            "regions": [
                {
                    "role": "anchor",
                    "slot": hex(slot),
                    "slot_count": "1",
                }
            ]
        }
    if type_info.encoding == "dynamic_array":
        scheme = layout.storage_rules.array_storage_scheme
        if scheme == "solidity":
            data_start = _hashed_array_root(slot)
        elif scheme == "vyper_sequential":
            data_start = (slot + 1) % (2**256)
        else:
            data_start = None
        return {
            "regions": [
                {
                    "role": "length",
                    "slot": hex(slot),
                    "slot_count": "1",
                },
                *(
                    [
                        {
                            "role": "data",
                            "slot": hex(data_start),
                            "slot_count": None,
                        }
                    ]
                    if data_start is not None
                    else []
                ),
            ]
        }
    if is_solidity_dynamic_bytes(layout, type_info):
        return {
            "regions": [
                {
                    "role": "header",
                    "slot": hex(slot),
                    "slot_count": "1",
                }
            ]
        }
    return None


class StorageViewService:
    """Resolve metadata, layout, and values inside one exact RPC attempt."""

    def __init__(
        self,
        web3_provider: Web3Provider,
        resolver: ContractResolver,
        layout_parser: LayoutParser,
        settings: Settings,
        decoder: TypeDecoder,
    ):
        self.web3_provider = web3_provider
        self.resolver = resolver
        self.layout_parser = layout_parser
        self.settings = settings
        self.decoder = decoder

    def _attempt_resolver(self, attempt: StorageAttempt) -> ContractResolver:
        return ContractResolver(
            web3_provider=attempt,
            settings=self.resolver.settings,
            verification_service=self.resolver.verification_service,
            source_cache_repo=self.resolver.source_cache_repo,
            contract_repo=self.resolver.contract_repo,
            layout_parser=self.resolver.layout_parser,
            compiler_artifact_repo=self.resolver.compiler_artifact_repo,
            use_binding_cache=False,
        )

    async def _resolve_source_layout(
        self,
        metadata: ContractMetadata,
    ) -> StorageLayout | None:
        layout = metadata.storage_layout
        if isinstance(layout, dict):
            try:
                return StorageLayout.from_dict(layout)
            except Exception:
                return None
        if isinstance(layout, StorageLayout):
            return layout
        if not (
            metadata.is_verified
            and metadata.sources
            and metadata.name
            and metadata.compiler_version
        ):
            return None

        target = metadata.compilation_target or {}
        entry_source = next(iter(target)) if len(target) == 1 else None
        if any(filename.endswith(".vy") for filename in metadata.sources):
            return await self.layout_parser.parse_vyper(
                contract_name=metadata.name,
                sources=metadata.sources,
                compiler_version=metadata.compiler_version,
                entry_source=entry_source,
                compiler_artifact_repo=self.resolver.compiler_artifact_repo,
            )

        contract_fqname = None
        if entry_source:
            contract_fqname = f"{entry_source}:{target[entry_source]}"
        return await self.layout_parser.parse(
            contract_name=metadata.name,
            sources=metadata.sources,
            compiler_version=metadata.compiler_version,
            compiler_settings=metadata.compiler_settings,
            metadata_settings=metadata.compiler_settings,
            contract_fqname=contract_fqname,
            compiler_artifact_repo=self.resolver.compiler_artifact_repo,
        )

    async def prepare(
        self,
        chain_id: int,
        address: str,
        selector: int | str,
    ) -> StorageContext:
        attempt = await self.web3_provider.create_storage_attempt(chain_id, selector)
        return await self.prepare_on_attempt(attempt, address)

    async def prepare_exact(
        self,
        chain_id: int,
        address: str,
        number: int,
        block_hash: str,
    ) -> StorageContext:
        try:
            attempt = await self.web3_provider.create_exact_storage_attempt(
                chain_id,
                number,
                block_hash,
            )
        except ValueError as exc:
            raise StorageQueryError("INVALID_BLOCK_REF", str(exc)) from exc
        return await self.prepare_on_attempt(attempt, address)

    async def prepare_on_attempt(
        self,
        attempt: StorageAttempt,
        address: str,
    ) -> StorageContext:
        resolver = self._attempt_resolver(attempt)
        metadata = await resolver.resolve(
            attempt.block_ref.chain_id,
            address,
            block_number=attempt.block_ref.number,
        )
        source_layout = await self._resolve_source_layout(metadata)
        if source_layout is None:
            return StorageContext(
                attempt=attempt,
                metadata=metadata,
                layout=None,
                layout_status=(
                    "unverified" if not metadata.is_verified else "unsupported"
                ),
            )
        try:
            compiled = compile_layout(source_layout)
        except UnsupportedCompiledLayout:
            return StorageContext(
                attempt=attempt,
                metadata=metadata,
                layout=None,
                layout_status="unsupported",
            )
        return StorageContext(
            attempt=attempt,
            metadata=metadata,
            layout=compiled,
            layout_status="ok",
        )

    async def get_view(
        self,
        chain_id: int,
        address: str,
        selector: int | str,
    ) -> dict[str, Any]:
        context = await self.prepare(chain_id, address, selector)
        metadata = context.metadata
        attempt = context.attempt
        effective_code_address = (
            metadata.delegate_address
            if metadata.is_delegated
            else metadata.implementation_address
            if metadata.is_proxy
            else metadata.address
        )
        contract_wire = {
            "address": Web3.to_checksum_address(metadata.address),
            "storage_address": Web3.to_checksum_address(metadata.address),
            "effective_code_address": (
                Web3.to_checksum_address(effective_code_address)
                if effective_code_address
                else Web3.to_checksum_address(metadata.address)
            ),
            "name": metadata.name,
            "is_verified": metadata.is_verified,
            "is_proxy": metadata.is_proxy,
            "proxy_type": metadata.proxy_type,
            "layout_provenance": metadata.layout_provenance,
            "layout_source_address": (
                Web3.to_checksum_address(metadata.layout_source_address)
                if metadata.layout_source_address
                else None
            ),
        }
        block_wire = {
            "number": hex(attempt.block_ref.number),
            "hash": attempt.block_ref.hash,
        }

        if context.layout is None:
            return {
                "block_ref": block_wire,
                "contract": contract_wire,
                "layout_id": None,
                "layout": {
                    "status": context.layout_status,
                    "variables": [],
                    "types": {},
                    "storage_rules": None,
                },
                "values": {
                    "status": "unavailable",
                    "items": [],
                    "error_code": None,
                },
            }

        layout = context.layout
        max_words = min(256, self.settings.max_slots_per_contract)
        plan = plan_compiled_scalar_reads(
            layout,
            max_words=max_words,
        )
        reader = StorageReader(attempt)
        storage_provenance = {
            index: _base_storage_provenance(
                layout,
                projection.type_info,
                projection.slot,
            )
            for index, projection in enumerate(plan.projections)
        }
        try:
            word_values = await reader.read_slots(
                chain_id,
                metadata.address,
                list(plan.words),
                attempt.block_ref.number,
            )

            dynamic_data_slots: dict[int, tuple[int, ...]] = {}
            deferred_dynamic: set[int] = set()
            admitted_words = set(plan.words)
            remaining_words = max_words - len(admitted_words)
            pending_data_words: list[int] = []

            for index, projection in enumerate(plan.projections):
                if projection.status != "pending_dynamic":
                    continue

                raw_word = bytes.fromhex(word_values[projection.slot][2:])
                try:
                    length, is_inline = self.decoder.inspect_dynamic_bytes_slot(
                        raw_word
                    )
                except ValueError:
                    dynamic_data_slots[index] = ()
                    continue
                if is_inline:
                    storage_provenance[index] = {
                        "regions": [
                            {
                                "role": "inline",
                                "slot": hex(projection.slot),
                                "slot_count": "1",
                            }
                        ]
                    }
                    dynamic_data_slots[index] = ()
                    continue

                required_words = (length + 31) // 32
                data_start = _hashed_array_root(projection.slot)
                storage_provenance[index] = {
                    "regions": [
                        {
                            "role": "length",
                            "slot": hex(projection.slot),
                            "slot_count": "1",
                        },
                        {
                            "role": "data",
                            "slot": hex(data_start),
                            "slot_count": str(required_words),
                        },
                    ]
                }
                if required_words > max_words:
                    deferred_dynamic.add(index)
                    continue

                slots = tuple(
                    (data_start + offset) % (2**256)
                    for offset in range(required_words)
                )
                new_slots = [
                    slot
                    for slot in slots
                    if slot not in admitted_words
                ]
                if len(new_slots) > remaining_words:
                    deferred_dynamic.add(index)
                    continue

                dynamic_data_slots[index] = slots
                admitted_words.update(new_slots)
                pending_data_words.extend(new_slots)
                remaining_words -= len(new_slots)

            if pending_data_words:
                word_values.update(
                    await reader.read_slots(
                        chain_id,
                        metadata.address,
                        pending_data_words,
                        attempt.block_ref.number,
                    )
                )
        except Exception:
            values_wire = {
                "status": "error",
                "items": [],
                "error_code": "STORAGE_READ_FAILED",
            }
        else:
            items = []
            for index, projection in enumerate(plan.projections):
                projection_status = (
                    "deferred_budget"
                    if index in deferred_dynamic
                    else projection.status
                )
                base = {
                    "declaration_id": projection.declaration.declaration_id,
                    "path": projection.path,
                    "status": (
                        "ok"
                        if projection_status in {"pending", "pending_dynamic"}
                        else projection_status
                    ),
                    "slot": hex(projection.slot),
                    "byte_offset": projection.byte_offset,
                    "value_encoded": None,
                    "value_decoded": None,
                    "storage": storage_provenance[index],
                }
                if projection_status == "pending":
                    raw_word = word_values[projection.slot]
                    base["value_encoded"] = raw_word
                    try:
                        decoded = self.decoder.decode(
                            bytes.fromhex(raw_word[2:]),
                            projection.type_info,
                            projection.byte_offset,
                        )
                    except Exception:
                        pass
                    else:
                        base["value_decoded"] = _wire_decoded(decoded.decoded)
                elif projection_status == "pending_dynamic":
                    raw_word = word_values[projection.slot]
                    base["value_encoded"] = raw_word
                    try:
                        decoded = self.decoder.decode_dynamic_bytes_value(
                            bytes.fromhex(raw_word[2:]),
                            [
                                bytes.fromhex(word_values[slot][2:])
                                for slot in dynamic_data_slots.get(index, ())
                            ],
                            projection.type_info.label,
                        )
                    except Exception:
                        pass
                    else:
                        base["value_decoded"] = _wire_decoded(decoded.decoded)
                items.append(base)
            values_wire = {
                "status": "ok",
                "items": items,
                "error_code": None,
            }

        layout_wire = layout.canonical_wire()
        return {
            "block_ref": block_wire,
            "contract": contract_wire,
            "layout_id": layout.layout_id,
            "layout": {
                "status": "ok",
                **layout_wire,
            },
            "values": values_wire,
        }

    async def query(
        self,
        *,
        chain_id: int,
        address: str,
        block_number: int,
        block_hash: str,
        layout_id: str,
        declaration_id: str,
        steps: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Resolve one backend-authoritative typed storage access."""
        if chain_id <= 0:
            raise StorageQueryError("INVALID_CHAIN", "chain_id must be positive")
        try:
            checksum_address = Web3.to_checksum_address(address)
        except Exception as exc:
            raise StorageQueryError("INVALID_ADDRESS", "Invalid contract address") from exc
        if block_number < 0 or block_number >= 2**256:
            raise StorageQueryError(
                "INVALID_BLOCK_REF",
                "Block number is outside the uint256 range",
            )
        if not re.fullmatch(r"0x[0-9a-fA-F]{64}", block_hash):
            raise StorageQueryError(
                "INVALID_BLOCK_REF",
                "Block hash must be an exact 32-byte hexadecimal value",
            )
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", layout_id):
            raise StorageQueryError("INVALID_LAYOUT_ID", "Invalid layout_id")
        if not re.fullmatch(r"decl:\d+", declaration_id):
            raise StorageQueryError(
                "INVALID_DECLARATION",
                "Invalid declaration_id",
            )
        if not steps:
            raise StorageQueryError(
                "UNSUPPORTED_ACCESS",
                "A mapping key or array index is required",
            )

        context = await self.prepare_exact(
            chain_id,
            checksum_address,
            block_number,
            block_hash,
        )
        layout = context.layout
        if layout is None:
            raise StorageQueryError(
                "UNSUPPORTED_LAYOUT",
                "The contract does not have a supported compiled layout",
            )
        if layout.layout_id != layout_id:
            raise StorageQueryError(
                "LAYOUT_MISMATCH",
                "layout_id does not match the exact requested block",
            )
        declaration = layout.get_declaration(declaration_id)
        if declaration is None:
            raise StorageQueryError(
                "INVALID_DECLARATION",
                "declaration_id is not part of this layout",
            )
        engine = StorageQueryEngine(
            layout=layout,
            reader=StorageReader(context.attempt),
            decoder=self.decoder,
            max_words=min(256, self.settings.max_slots_per_contract),
            chain_id=chain_id,
            address=checksum_address,
            block_ref=context.attempt.block_ref,
        )
        return await engine.query(declaration, steps)
