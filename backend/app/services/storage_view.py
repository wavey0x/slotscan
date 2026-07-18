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
    is_one_word_query_result,
    is_one_word_scalar,
    plan_compiled_scalar_reads,
)
from app.services.storage_rules import (
    compute_solidity_mapping_slot,
    compute_vyper_mapping_slot,
    encode_mapping_key,
)
from app.services.web3_provider import BlockRef, StorageAttempt, Web3Provider


@dataclass(frozen=True)
class StorageContext:
    attempt: StorageAttempt
    metadata: ContractMetadata
    layout: CompiledLayout | None
    layout_status: str


class StorageQueryError(ValueError):
    """A stable client error for an invalid or unsupported typed access."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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


def _parse_uint(value: str, label: str) -> int:
    if not isinstance(value, str) or not value.strip():
        raise StorageQueryError("INVALID_INPUT", f"{label} must be a string")
    try:
        parsed = int(value, 0)
    except ValueError as exc:
        raise StorageQueryError(
            "INVALID_INPUT",
            f"{label} must be a decimal or hexadecimal integer",
        ) from exc
    if parsed < 0 or parsed >= 2**256:
        raise StorageQueryError(
            "INVALID_INPUT",
            f"{label} is outside the uint256 range",
        )
    return parsed


def _mapping_location(
    layout: CompiledLayout,
    base_slot: int,
    declared_key_type: str,
    value: str,
) -> int:
    try:
        encoded_key = encode_mapping_key(declared_key_type, value)
    except (TypeError, ValueError) as exc:
        raise StorageQueryError("INVALID_MAPPING_KEY", str(exc)) from exc
    if layout.storage_rules.mapping_preimage_order == "key_then_slot":
        return compute_solidity_mapping_slot(base_slot, encoded_key)
    return compute_vyper_mapping_slot(base_slot, encoded_key)


def _hashed_array_root(slot: int) -> int:
    return int.from_bytes(Web3.keccak(slot.to_bytes(32, "big")), "big")


def _array_element_location(
    layout: CompiledLayout,
    type_info: CompiledType,
    declaration_slot: int,
    index: int,
) -> tuple[int, int, CompiledType, int | None]:
    element_type = (
        layout.get_type(type_info.element_type) if type_info.element_type else None
    )
    if not is_one_word_scalar(element_type):
        raise StorageQueryError(
            "UNSUPPORTED_ACCESS",
            "Only arrays ending in one-word scalar elements are supported",
        )

    scheme = layout.storage_rules.array_storage_scheme
    is_dynamic = type_info.encoding == "dynamic_array"
    if is_dynamic:
        if scheme == "solidity":
            data_start = _hashed_array_root(declaration_slot)
        elif scheme == "vyper_sequential":
            data_start = declaration_slot + 1
        else:
            raise StorageQueryError(
                "UNSUPPORTED_ACCESS",
                "Dynamic arrays using legacy Vyper hashed storage are unsupported",
            )
        static_bound = type_info.array_length if scheme != "solidity" else None
    else:
        if type_info.encoding != "inplace" or type_info.array_length is None:
            raise StorageQueryError(
                "UNSUPPORTED_ACCESS",
                "The declaration is not a supported fixed array",
            )
        data_start = (
            _hashed_array_root(declaration_slot)
            if scheme == "vyper_legacy_hashed"
            else declaration_slot
        )
        static_bound = type_info.array_length

    element_size = element_type.num_bytes or 32
    if scheme == "solidity" and element_size < 32:
        elements_per_word = 32 // element_size
        slot = data_start + index // elements_per_word
        byte_offset = (index % elements_per_word) * element_size
    else:
        slot = data_start + index
        byte_offset = 0
    return slot % (2**256), byte_offset, element_type, static_bound


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
        plan = plan_compiled_scalar_reads(
            layout,
            max_words=min(256, self.settings.max_slots_per_contract),
        )
        reader = StorageReader(attempt)
        try:
            word_values = await reader.read_slots_batch(
                chain_id,
                metadata.address,
                list(plan.words),
                attempt.block_ref.number,
            )
        except Exception:
            values_wire = {
                "status": "error",
                "items": [],
                "error_code": "STORAGE_READ_FAILED",
            }
        else:
            items = []
            for projection in plan.projections:
                base = {
                    "declaration_id": projection.declaration.declaration_id,
                    "path": projection.path,
                    "status": (
                        "ok" if projection.status == "pending" else projection.status
                    ),
                    "slot": hex(projection.slot),
                    "byte_offset": projection.byte_offset,
                    "value_encoded": None,
                    "value_decoded": None,
                }
                if projection.status == "pending":
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
        """Resolve one backend-authoritative mapping or array access."""
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
        type_info = layout.get_type(declaration.type_id)
        if type_info is None:
            raise StorageQueryError(
                "UNSUPPORTED_ACCESS",
                "The declaration type is unavailable",
            )

        length_word: str | None = None
        if type_info.encoding == "mapping":
            slot = declaration.slot
            path = declaration.name
            current_type = type_info
            for step in steps:
                if (
                    step.get("kind") != "mapping_key"
                    or current_type.encoding != "mapping"
                    or not current_type.key_type
                    or not current_type.value_type
                ):
                    raise StorageQueryError(
                        "UNSUPPORTED_ACCESS",
                        "The step sequence is not a scalar mapping path",
                    )
                slot = _mapping_location(
                    layout,
                    slot,
                    current_type.key_type,
                    step.get("value", ""),
                )
                path = f"{path}[{step.get('value', '')}]"
                next_type = layout.get_type(current_type.value_type)
                if next_type is None:
                    raise StorageQueryError(
                        "UNSUPPORTED_ACCESS",
                        "The mapping value type is unavailable",
                    )
                current_type = next_type
            if not is_one_word_query_result(layout, current_type):
                raise StorageQueryError(
                    "UNSUPPORTED_ACCESS",
                    "Mappings must end in a one-word scalar or packed struct value",
                )
            byte_offset = 0
            result_type = current_type
        elif type_info.kind == "array":
            if len(steps) != 1 or steps[0].get("kind") != "array_index":
                raise StorageQueryError(
                    "UNSUPPORTED_ACCESS",
                    "Top-level arrays require exactly one array_index step",
                )
            index = _parse_uint(steps[0].get("value", ""), "array index")
            slot, byte_offset, result_type, static_bound = _array_element_location(
                layout,
                type_info,
                declaration.slot,
                index,
            )
            if static_bound is not None and index >= static_bound:
                raise StorageQueryError(
                    "ARRAY_BOUNDS",
                    "Array index is outside the declared bound",
                )
            path = f"{declaration.name}[{index}]"
            if type_info.encoding == "dynamic_array":
                reader = StorageReader(context.attempt)
                length_values = await reader.read_slots_batch(
                    chain_id,
                    checksum_address,
                    [declaration.slot],
                    context.attempt.block_ref.number,
                )
                length_word = length_values[declaration.slot]
                length = int(length_word, 16)
                if index >= length:
                    raise StorageQueryError(
                        "ARRAY_BOUNDS",
                        "Array index is outside the current dynamic length",
                    )
        else:
            raise StorageQueryError(
                "UNSUPPORTED_ACCESS",
                "Only mappings and top-level arrays are queryable",
            )

        reader = StorageReader(context.attempt)
        word_values = await reader.read_slots_batch(
            chain_id,
            checksum_address,
            [slot],
            context.attempt.block_ref.number,
        )
        raw_word = word_values[slot]
        try:
            raw_bytes = bytes.fromhex(raw_word[2:])
            if result_type.kind == "struct":
                decoded_wire = {
                    member.name: _wire_decoded(
                        self.decoder.decode(
                            raw_bytes,
                            layout.types[member.type_id],
                            member.byte_offset,
                        ).decoded
                    )
                    for member in result_type.members
                }
            else:
                decoded = self.decoder.decode(
                    raw_bytes,
                    result_type,
                    byte_offset,
                )
                decoded_wire = _wire_decoded(decoded.decoded)
        except Exception:
            decoded_wire = None

        response = {
            "block_ref": block_ref_wire(context.attempt.block_ref),
            "layout_id": layout.layout_id,
            "declaration_id": declaration.declaration_id,
            "path": path,
            "location": {
                "slot": hex(slot),
                "byte_offset": byte_offset,
                "byte_size": result_type.num_bytes,
            },
            "value_encoded": raw_word,
            "value_decoded": decoded_wire,
        }
        if length_word is not None:
            response["array_length"] = str(int(length_word, 16))
        return response


def block_ref_wire(block_ref: BlockRef) -> dict[str, str]:
    """Return the public exact-block representation."""
    return {
        "number": hex(block_ref.number),
        "hash": block_ref.hash,
    }
