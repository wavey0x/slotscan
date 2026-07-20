"""Transaction tracer for extracting storage changes from transactions."""

import asyncio
from bisect import bisect_right
from collections.abc import Callable
from contextlib import asynccontextmanager
import logging
from dataclasses import asdict, dataclass, replace
from typing import AsyncIterator, Optional

from web3 import Web3

from app.config import Settings
from app.models.domain import (
    DecodedValue,
    StorageChange,
    StorageLayout,
    TransactionDiff,
)
from app.repositories.trace_cache import (
    TraceCacheRepository,
    TransactionTraceArtifactData,
)
from app.services.decoder import TypeDecoder
from app.services.web3_provider import Web3Provider
from app.services.tracer.rpc_client import TraceRPCClient
from app.services.tracer.preimage_resolver import PreimageResolver
from app.services.tracer.slot_resolver import SlotPathResolver
from app.services.layout_index import array_packing
from app.services.layout_index import LayoutIndex, StorageLocation, StorageNamespace
from app.services.tracer.journal import (
    StorageJournal,
    StorageJournalBuilder,
    WriteEffect,
)
from app.services.tracer.extractor import (
    TransactionTraceEvidence,
    TransactionTraceExtractor,
)
from app.services.transaction_receipt import ReceiptIdentity
from app.models.errors import TraceNotAvailableError
from app.utils.vyper import LEGACY_HASHED_STORAGE

logger = logging.getLogger(__name__)


@dataclass
class _TraceLockEntry:
    lock: asyncio.Lock
    users: int = 0


class TraceSingleFlight:
    """Application-scoped per-transaction lock registry."""

    def __init__(self):
        self._entries: dict[
            tuple[int, str, ReceiptIdentity],
            _TraceLockEntry,
        ] = {}

    @asynccontextmanager
    async def hold(
        self,
        chain_id: int,
        tx_hash: str,
        receipt: ReceiptIdentity,
    ) -> AsyncIterator[None]:
        key = (chain_id, tx_hash.lower(), receipt)
        entry = self._entries.get(key)
        if entry is None:
            entry = _TraceLockEntry(asyncio.Lock())
            self._entries[key] = entry
        entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            entry.users -= 1
            if entry.users == 0 and self._entries.get(key) is entry:
                self._entries.pop(key, None)


class TransactionAnalysisService:
    """Orchestrate transaction evidence, journaling, resolution, and decoding."""

    def __init__(
        self,
        web3_provider: Web3Provider,
        settings: Settings,
        decoder: TypeDecoder,
        trace_cache_repo: Optional[TraceCacheRepository] = None,
        single_flight: TraceSingleFlight | None = None,
    ):
        self.web3_provider = web3_provider
        self.settings = settings
        self.decoder = decoder
        self.trace_cache_repo = trace_cache_repo
        self.single_flight = single_flight or TraceSingleFlight()

        # Composed services
        self.rpc_client = TraceRPCClient(web3_provider, settings)
        self.trace_extractor = TransactionTraceExtractor(self.rpc_client)
        self.preimage_resolver = PreimageResolver(
            settings.max_constant_mapping_candidates
        )
        self.slot_resolver = SlotPathResolver()
        self.journal_builder = StorageJournalBuilder()

    async def load_trace_artifact(
        self,
        chain_id: int,
        tx_hash: str,
        receipt: dict | None = None,
    ) -> TransactionTraceArtifactData:
        """Load or extract the one contract-agnostic artifact for a transaction."""
        if receipt is None:
            receipt = await self.rpc_client.get_receipt(chain_id, tx_hash)
        receipt_identity = ReceiptIdentity.from_receipt(receipt)
        if self.trace_cache_repo:
            cached = await self.trace_cache_repo.get(
                chain_id,
                tx_hash,
                receipt_identity,
            )
            if cached:
                return cached

            async with self.single_flight.hold(
                chain_id,
                tx_hash,
                receipt_identity,
            ):
                cached = await self.trace_cache_repo.get(
                    chain_id,
                    tx_hash,
                    receipt_identity,
                )
                if cached:
                    return cached
                return await self._extract_trace_artifact(
                    chain_id,
                    tx_hash,
                    receipt,
                    receipt_identity,
                )

        return await self._extract_trace_artifact(
            chain_id,
            tx_hash,
            receipt,
            receipt_identity,
        )

    async def _extract_trace_artifact(
        self,
        chain_id: int,
        tx_hash: str,
        receipt: dict,
        receipt_identity: ReceiptIdentity,
    ) -> TransactionTraceArtifactData:
        logger.info("Trace artifact MISS for %s - executing RPC calls", tx_hash[:10])
        evidence = await self.trace_extractor.extract(
            chain_id,
            tx_hash,
            receipt,
        )
        try:
            self._enforce_trace_limits(evidence)
        except TraceNotAvailableError as exc:
            logger.warning(
                "Discarding oversized execution history while preserving net state "
                "for %s: %s",
                tx_hash,
                exc.reason,
            )
            evidence = replace(
                evidence,
                writes=[],
                sha3_operations=[],
                evm_step_count=0,
                degraded_reason="trace_limit",
            )
        journal = self.journal_builder.build(
            evidence.writes,
            evidence.prestate_diff,
            root_succeeded=receipt_identity.root_succeeded,
            evm_step_count=evidence.evm_step_count or None,
        )
        write_history_complete = evidence.evm_step_count > 0
        persistent_writes = [
            write
            for write in evidence.writes
            if write.get("namespace", "persistent") == "persistent"
        ]
        capabilities = {
            **asdict(journal.capabilities),
            "write_history_complete": write_history_complete,
            "address_attribution_complete": all(
                bool(write.get("address")) for write in evidence.writes
            ),
            "code_attribution_complete": (
                write_history_complete
                and all(
                    write.get("code_attribution") == "exact"
                    and bool(write.get("code_address"))
                    for write in persistent_writes
                )
            ),
            "degraded_reason": evidence.degraded_reason,
        }
        artifact = TransactionTraceArtifactData(
            chain_id=chain_id,
            tx_hash=tx_hash.lower(),
            block_hash=receipt_identity.block_hash,
            block_number=receipt_identity.block_number,
            transaction_index=receipt_identity.transaction_index,
            root_succeeded=receipt_identity.root_succeeded,
            transaction_from=self._optional_address(receipt.get("from")),
            transaction_to=self._optional_address(receipt.get("to")),
            created_contract=self._optional_address(receipt.get("contractAddress")),
            write_events=evidence.writes,
            prestate_diff=evidence.prestate_diff,
            preimage_lookup=self.preimage_resolver.build_preimage_lookup(
                evidence.sha3_operations
            ),
            capabilities=capabilities,
            trace_step_count=evidence.evm_step_count or None,
        )

        # A degraded trace returns an incomplete, useful net-state projection,
        # but is not cached so a later request can retry tracing.
        if self.trace_cache_repo and write_history_complete:
            try:
                await self.trace_cache_repo.save(artifact)
            except Exception as exc:
                logger.warning("Failed to save trace artifact: %s", exc)
        return artifact

    def _enforce_trace_limits(self, evidence: TransactionTraceEvidence) -> None:
        if len(evidence.writes) > self.settings.max_sstore_ops:
            raise TraceNotAvailableError("Trace exceeds the configured write limit")
        if evidence.evm_step_count > self.settings.max_trace_steps:
            raise TraceNotAvailableError("Trace exceeds the configured step limit")
        if len(evidence.sha3_operations) > self.settings.max_trace_sha3_ops:
            raise TraceNotAvailableError("Trace exceeds the configured SHA3 limit")

        preimage_bytes = 0
        for operation in evidence.sha3_operations:
            preimage = operation.get("preimage")
            if not isinstance(preimage, str):
                continue
            clean = preimage.removeprefix("0x")
            preimage_bytes += (len(clean) + 1) // 2
            if preimage_bytes > self.settings.max_trace_preimage_bytes:
                raise TraceNotAvailableError(
                    "Trace exceeds the configured preimage limit"
                )

    def build_journal(self, artifact: TransactionTraceArtifactData) -> StorageJournal:
        return self.journal_builder.build(
            artifact.write_events,
            artifact.prestate_diff,
            root_succeeded=artifact.root_succeeded,
            evm_step_count=artifact.trace_step_count,
        )

    def persistent_storage_owners(
        self,
        artifact: TransactionTraceArtifactData,
        journal: StorageJournal | None = None,
    ) -> tuple[str, ...]:
        """Enumerate storage owners from writes, including rolled-back/no-op writes."""
        journal = journal or self.build_journal(artifact)
        first_step: dict[str, int] = {}
        for event in journal.events:
            if event.namespace != StorageNamespace.PERSISTENT:
                continue
            first_step.setdefault(event.address, event.step)

        if not first_step and not artifact.capabilities.get(
            "write_history_complete", False
        ):
            # Degraded fallback: net-diff owners are useful but explicitly do
            # not prove complete execution-time write history.
            for state_side in ("pre", "post"):
                for address, state in artifact.prestate_diff.get(state_side, {}).items():
                    if state.get("storage"):
                        first_step.setdefault(address.lower(), 2**63 - 1)

        return tuple(sorted(first_step, key=lambda address: (first_step[address], address)))

    def project_trace_artifact(
        self,
        artifact: TransactionTraceArtifactData,
        contract_address: str,
        *,
        layout: Optional[StorageLayout] = None,
        sources: Optional[dict[str, str]] = None,
        layouts_by_code_address: Optional[dict[str, StorageLayout]] = None,
        sources_by_code_address: Optional[dict[str, dict[str, str]]] = None,
        journal: StorageJournal | None = None,
    ) -> TransactionDiff:
        """Decode one storage-owner projection without issuing another trace."""
        contract_address = Web3.to_checksum_address(contract_address)
        journal = journal or self.build_journal(artifact)
        code_attribution_complete = artifact.capabilities.get(
            "code_attribution_complete",
            False,
        )
        if not code_attribution_complete:
            # A raw struct-log target does not prove the effective EIP-7702
            # code source. Keep the writes, but do not apply a guessed layout.
            layout = None
            sources = None
            layouts_by_code_address = None
            sources_by_code_address = None
        raw_changes: list[tuple[str, str | None, str, int | None, int]] = []
        code_address_by_step: dict[int, str | None] = {}
        had_unknown_evidence = any(
            not write.get("address") for write in artifact.write_events
        )

        for history in journal.for_contract(
            contract_address,
            StorageNamespace.PERSISTENT,
        ):
            for event in history.writes:
                had_unknown_evidence |= event.value_before is None
                raw_changes.append(
                    (
                        event.slot,
                        event.value_before,
                        event.value_after,
                        event.pc,
                        event.step,
                    )
                )
                code_address_by_step[event.step] = (
                    event.code_address.lower() if event.code_address else None
                )

        write_history_complete = artifact.capabilities.get(
            "write_history_complete", bool(artifact.trace_step_count)
        )
        if not write_history_complete:
            raw_changes = [
                (self._normalize_slot(slot), old, new, None, index)
                for index, (slot, old, new) in enumerate(
                    self._extract_contract_changes(
                        artifact.prestate_diff,
                        contract_address,
                    )
                )
            ]

        raw_changes.sort(key=lambda change: change[4])
        storage_timelines = self._storage_value_timelines(
            artifact,
            journal,
            contract_address,
        )
        is_complete = (
            write_history_complete
            and code_attribution_complete
            and len(raw_changes) <= self.settings.max_sstore_ops
            and not had_unknown_evidence
        )
        if len(raw_changes) > self.settings.max_sstore_ops:
            raw_changes = raw_changes[: self.settings.max_sstore_ops]

        preimage_lookup = dict(artifact.preimage_lookup)
        layouts_by_code_address = {
            address.lower(): code_layout
            for address, code_layout in (layouts_by_code_address or {}).items()
        }
        sources_by_code_address = {
            address.lower(): code_sources
            for address, code_sources in (sources_by_code_address or {}).items()
        }
        if layouts_by_code_address and write_history_complete:
            grouped_changes: dict[str | None, list[tuple[str, str | None, str, int | None, int]]] = {}
            for raw_change in raw_changes:
                code_address = code_address_by_step.get(raw_change[4])
                grouped_changes.setdefault(code_address, []).append(raw_change)
            decoded_changes = []
            for code_address, code_changes in grouped_changes.items():
                code_layout = layouts_by_code_address.get(code_address or "") or layout
                code_sources = sources_by_code_address.get(code_address or "") or sources
                code_preimages = dict(preimage_lookup)
                if code_sources and code_layout:
                    constants = self.preimage_resolver.build_constant_preimage_lookup(
                        code_sources,
                        code_layout,
                    )
                    for slot_hash, preimage in constants.items():
                        code_preimages.setdefault(slot_hash, preimage)
                decoded_changes.extend(
                    self._decode_changes(
                        code_changes,
                        code_layout,
                        code_preimages,
                        storage_timelines,
                    )
                )
            decoded_changes.sort(key=lambda change: change.change_index)
        else:
            if sources and layout:
                constants = self.preimage_resolver.build_constant_preimage_lookup(
                    sources,
                    layout,
                )
                for slot_hash, preimage in constants.items():
                    preimage_lookup.setdefault(slot_hash, preimage)
            decoded_changes = self._decode_changes(
                raw_changes,
                layout,
                preimage_lookup,
                storage_timelines,
            )
        self._apply_journal_metadata(decoded_changes, journal, contract_address)
        return TransactionDiff(
            chain_id=artifact.chain_id,
            contract_address=contract_address,
            tx_hash=artifact.tx_hash,
            block_number=artifact.block_number,
            changes=decoded_changes,
            is_complete=is_complete,
            layout=layout,
            trace_unavailable=False,
            execution_order_available=journal.capabilities.execution_order,
            frame_outcomes_available=journal.capabilities.frame_outcomes,
            write_old_values_available=journal.capabilities.write_old_values,
            final_state_values_available=journal.capabilities.final_state_values,
            trace_step_count=artifact.trace_step_count,
        )

    @staticmethod
    def _quantity(value: int | str) -> int:
        return int(value, 16) if isinstance(value, str) else int(value)

    @staticmethod
    def _optional_address(value) -> str | None:
        return str(value).lower() if value else None

    def _apply_journal_metadata(
        self,
        changes: list[StorageChange],
        journal: StorageJournal,
        contract_address: str,
    ) -> None:
        histories = journal.for_contract(
            contract_address,
            StorageNamespace.PERSISTENT,
        )
        history_by_slot = {history.slot: history for history in histories}
        events_by_key = {
            (event.slot, event.step): event
            for history in histories
            for event in history.writes
        }

        for change in changes:
            history = history_by_slot.get(change.slot)
            event = events_by_key.get((change.slot, change.change_index))
            if history:
                change.state_initial_value = history.initial_value
                change.state_final_value = history.final_value
                change.state_values_known = history.state_values_known
            if event:
                change.effect = event.effect.value
                change.frame_id = event.frame_id
                change.depth = event.depth
                change.code_address = event.code_address
                change.changed_value = event.changed_value
                change.frame_outcome = event.frame_outcome
                change.opcode = event.opcode
                change.namespace = event.namespace.value

    def _extract_contract_changes(
        self, trace_result: dict, contract_address: str
    ) -> list[tuple[str, str, str]]:
        """Extract storage changes for a specific contract from trace."""
        contract_address_lower = contract_address.lower()
        changes = []

        pre_state = trace_result.get("pre", {})
        post_state = trace_result.get("post", {})

        pre_storage = {}
        post_storage = {}

        for addr, state in pre_state.items():
            if addr.lower() == contract_address_lower:
                pre_storage = state.get("storage", {})
                break

        for addr, state in post_state.items():
            if addr.lower() == contract_address_lower:
                post_storage = state.get("storage", {})
                break

        all_slots = set(pre_storage.keys()) | set(post_storage.keys())
        zero_value = "0x" + "0" * 64

        for slot in all_slots:
            normalized_slot = self._normalize_slot(slot)
            old_val = pre_storage.get(slot, zero_value)
            new_val = post_storage.get(slot, zero_value)

            old_val = self._normalize_value(old_val)
            new_val = self._normalize_value(new_val)

            if old_val != new_val:
                changes.append((normalized_slot, old_val, new_val))

        return changes

    def _normalize_slot(self, slot: str) -> str:
        """Normalize a slot to 0x-prefixed, 64-char hex."""
        if isinstance(slot, int):
            return f"0x{slot:064x}"
        if not slot.startswith("0x"):
            slot = "0x" + slot
        hex_part = slot[2:]
        padded = hex_part.zfill(64)
        return "0x" + padded.lower()

    def _normalize_value(self, value: str) -> str:
        """Normalize a storage value to full 32-byte hex."""
        if isinstance(value, int):
            return f"0x{value:064x}"
        if not value.startswith("0x"):
            value = "0x" + value
        hex_part = value[2:]
        padded = hex_part.zfill(64)
        return "0x" + padded.lower()

    def _storage_value_timelines(
        self,
        artifact: TransactionTraceArtifactData,
        journal: StorageJournal,
        contract_address: str,
    ) -> dict[int, tuple[int | None, tuple[tuple[int, int], ...]]]:
        """Return proven initial words plus durable writes for one owner."""
        normalized_address = contract_address.lower()
        initial_by_slot: dict[int, int] = {}
        for raw_address, state in artifact.prestate_diff.get("pre", {}).items():
            if raw_address.lower() != normalized_address:
                continue
            initial_by_slot.update(
                {
                    int(self._normalize_slot(slot), 16): int(
                        self._normalize_value(value),
                        16,
                    )
                    for slot, value in state.get("storage", {}).items()
                }
            )

        writes_by_slot: dict[int, list[tuple[int, int]]] = {}
        for history in journal.for_contract(
            contract_address,
            StorageNamespace.PERSISTENT,
        ):
            slot = int(history.slot, 16)
            if history.initial_value is not None:
                initial_by_slot.setdefault(slot, int(history.initial_value, 16))
            for event in history.writes:
                if event.effect == WriteEffect.REVERTED:
                    continue
                writes_by_slot.setdefault(slot, []).append(
                    (event.step, int(event.value_after, 16))
                )

        return {
            slot: (
                initial_by_slot.get(slot),
                tuple(sorted(writes_by_slot.get(slot, ()))),
            )
            for slot in initial_by_slot.keys() | writes_by_slot.keys()
        }

    @staticmethod
    def _storage_value_at_step(
        timelines: dict[int, tuple[int | None, tuple[tuple[int, int], ...]]],
        slot: int,
        step: int,
    ) -> int | None:
        timeline = timelines.get(slot)
        if timeline is None:
            return None
        value, writes = timeline
        for write_step, write_value in writes:
            if write_step >= step:
                break
            value = write_value
        return value

    @staticmethod
    def _array_match_covers_change(
        match: dict | None,
        old_value: str | None,
        new_value: str,
    ) -> bool:
        if match is None:
            return False
        locations = match.get("element_locations")
        if not locations or old_value is None:
            return True
        old_bytes = bytes.fromhex(old_value.removeprefix("0x")).rjust(32, b"\x00")
        new_bytes = bytes.fromhex(new_value.removeprefix("0x")).rjust(32, b"\x00")
        if old_bytes == new_bytes:
            return True
        return any(
            old_bytes[
                32 - location.byte_offset - location.byte_size:
                32 - location.byte_offset
            ]
            != new_bytes[
                32 - location.byte_offset - location.byte_size:
                32 - location.byte_offset
            ]
            for _, location in locations
        )

    @staticmethod
    def _vyper_layout_evidence_conflicts(
        layout: StorageLayout,
        raw_changes: list[tuple[str, str | None, str, int | None, int]],
        preimage_lookup: dict[str, str],
    ) -> list[int]:
        """Find observed Vyper mapping bases that contradict an inferred layout."""
        if layout.language != "Vyper" or not any(
            variable.provenance == "source_inference"
            for variable in layout.variables
        ):
            return []

        mapping_slots = {
            variable.slot
            for variable in layout.variables
            if (
                (variable_type := layout.types.get(variable.type_id))
                and variable_type.encoding == "mapping"
            )
        }
        layout_end = max(
            (
                variable.slot + max(1, (variable.size + 31) // 32)
                for variable in layout.variables
            ),
            default=0,
        )
        conflicts: set[int] = set()
        for slot, *_ in raw_changes:
            preimage = preimage_lookup.get(slot.lower())
            if not preimage:
                continue
            encoded = preimage[2:] if preimage.startswith("0x") else preimage
            if len(encoded) != 128:
                continue
            try:
                base_slot = int(encoded[:64], 16)
            except ValueError:
                continue
            if base_slot < layout_end and base_slot not in mapping_slots:
                conflicts.add(base_slot)
        return sorted(conflicts)

    def _decode_changes(
        self,
        raw_changes: list[tuple[str, str | None, str, int | None, int]],
        layout: Optional[StorageLayout],
        preimage_lookup: Optional[dict[str, str]] = None,
        storage_timelines: Optional[
            dict[int, tuple[int | None, tuple[tuple[int, int], ...]]]
        ] = None,
    ) -> list[StorageChange]:
        """Convert raw slot changes to decoded StorageChange objects."""
        decoded_changes = []
        preimage_lookup = preimage_lookup or {}
        storage_timelines = storage_timelines or {}
        if layout:
            conflicting_bases = self._vyper_layout_evidence_conflicts(
                layout,
                raw_changes,
                preimage_lookup,
            )
            if conflicting_bases:
                logger.warning(
                    "Rejecting inferred Vyper layout %s: observed mapping base slots %s "
                    "contradict the inferred layout",
                    layout.contract_name,
                    conflicting_bases,
                )
                layout = None
        layout_index = LayoutIndex(layout) if layout else None
        decoder = self.decoder.bound(layout.types) if layout else self.decoder.bound({})
        struct_offsets = (
            self.slot_resolver.get_struct_offsets(layout)
            if layout
            else ()
        )
        is_legacy_vyper = bool(
            layout and layout.storage_scheme == LEGACY_HASHED_STORAGE
        )
        legacy_vyper_index = (
            self.slot_resolver.build_legacy_vyper_slot_index(
                layout,
                preimage_lookup,
                {int(change[0], 16) for change in raw_changes},
            )
            if layout and is_legacy_vyper
            else {}
        )
        dynamic_array_index = (
            self.slot_resolver.build_dynamic_array_index(layout)
            if layout and not is_legacy_vyper
            else {}
        )
        dynamic_bytes_index = (
            self.slot_resolver.build_dynamic_bytes_index(layout)
            if layout and not is_legacy_vyper
            else {}
        )
        static_array_index = (
            self.slot_resolver.build_static_array_index(layout)
            if layout and not is_legacy_vyper
            else {}
        )

        # Build mapping-to-array index
        mapping_to_array_index: dict[int, dict] = {}
        if layout and preimage_lookup and not is_legacy_vyper:
            for slot_hash, preimage in preimage_lookup.items():
                preimage_clean = preimage[2:] if preimage.startswith("0x") else preimage
                if len(preimage_clean) == 64:
                    match = self.slot_resolver.try_match_slot_from_preimage(
                        slot_hash,
                        preimage,
                        layout,
                        preimage_lookup,
                        depth=0,
                        struct_offsets=struct_offsets,
                    )
                    if match and match.get("encoding") == "mapping_to_array":
                        array_type = match.get("array_type")
                        if not array_type:
                            continue
                        data_start = match.get("data_start_slot")
                        if data_start is not None:
                            match["array_length"] = array_type.array_length
                            mapping_to_array_index[data_start] = match
            if mapping_to_array_index:
                logger.info(f"Built mapping-to-array index with {len(mapping_to_array_index)} entries")
        mapping_to_array_roots = tuple(sorted(mapping_to_array_index))
        array_roots = tuple(sorted(
            [(root, False) for root in dynamic_array_index]
            + [(root, True) for root in mapping_to_array_index]
        ))

        array_resolution_by_slot: dict[int, list[bool]] = {}
        for slot_hex, old_value, new_value, _, exec_index in raw_changes:
            slot_int = int(slot_hex, 16)
            def length_at_step(length_slot: int, step: int = exec_index) -> int | None:
                return self._storage_value_at_step(
                    storage_timelines,
                    length_slot,
                    step,
                )

            match = (
                self.slot_resolver.try_match_dynamic_array_slot(
                    slot_int,
                    layout,
                    dynamic_array_index,
                    length_at_step,
                )
                if layout and dynamic_array_index
                else None
            )
            if match is None and layout and mapping_to_array_index:
                match = self.slot_resolver.try_match_mapping_to_array_slot(
                    slot_int,
                    layout,
                    mapping_to_array_index,
                    mapping_to_array_roots,
                    length_at_step,
                )
            resolved = self._array_match_covers_change(
                match,
                old_value,
                new_value,
            )
            array_resolution_by_slot.setdefault(slot_int, []).append(resolved)
        blocked_array_slots = {
            slot
            for slot, resolutions in array_resolution_by_slot.items()
            if any(resolutions) and not all(resolutions)
        }

        matched_slots: dict[int, dict] = {}

        stats = {
            "total": 0,
            "layout_direct": 0,
            "static_array": 0,
            "preimage_lookup": 0,
            "struct_offset": 0,
            "dynamic_array": 0,
            "mapping_to_array": 0,
            "dynamic_bytes": 0,
            "legacy_vyper": 0,
            "heuristic": 0,
        }

        total_changes = len(raw_changes)
        logger.info(f"Decoding {total_changes} storage changes (preimage_lookup has {len(preimage_lookup)} entries)...")

        for change_idx, (slot_hex, old_value, new_value, pc, exec_index) in enumerate(raw_changes):
            stats["total"] += 1
            resolution_path = "unknown"
            reported_old_value = old_value

            if change_idx > 0 and change_idx % 50 == 0:
                logger.info(f"  Decoded {change_idx}/{total_changes} changes...")

            try:
                try:
                    slot_int = int(slot_hex, 16)
                except Exception:
                    slot_int = 0

                def length_at_step(length_slot: int) -> int | None:
                    return self._storage_value_at_step(
                        storage_timelines,
                        length_slot,
                        exec_index,
                    )

                legacy_match = legacy_vyper_index.get(slot_int)
                if legacy_match:
                    stats["legacy_vyper"] += 1
                    decode_type = legacy_match["decode_type"]
                    decode_old_value = old_value or ("0x" + "0" * 64)
                    try:
                        old_decoded = decoder.decode(
                            bytes.fromhex(decode_old_value.removeprefix("0x")),
                            decode_type,
                            0,
                        )
                        new_decoded = decoder.decode(
                            bytes.fromhex(new_value.removeprefix("0x")),
                            decode_type,
                            0,
                        )
                    except Exception:
                        old_decoded = None
                        new_decoded = None
                    if old_value is None:
                        old_decoded = None
                    decoded_changes.append(StorageChange(
                        slot=slot_hex,
                        mapping_base_slot=legacy_match.get("mapping_base_slot"),
                        old_value=old_value,
                        new_value=new_value,
                        variable=legacy_match["variable"],
                        variable_path=legacy_match["path"],
                        old_decoded=old_decoded,
                        new_decoded=new_decoded,
                        mapping_key=legacy_match.get("mapping_key"),
                        is_mapping=legacy_match.get("is_mapping", False),
                        encoding=legacy_match.get("encoding"),
                        key_type=legacy_match.get("key_type"),
                        value_type=legacy_match.get("value_type"),
                        element_type_id=legacy_match.get("element_type_id"),
                        array_index=legacy_match.get("array_index"),
                        change_index=exec_index,
                        pc=pc,
                    ))
                    continue

                packed_array_changes = (
                    self._decode_packed_array_change(
                        slot_int=slot_int,
                        slot_hex=slot_hex,
                        old_value=old_value,
                        new_value=new_value,
                        pc=pc,
                        exec_index=exec_index,
                        layout=layout,
                        layout_index=layout_index,
                        decoder=decoder,
                        dynamic_array_index=dynamic_array_index,
                        mapping_to_array_index=mapping_to_array_index,
                        array_roots=array_roots,
                        array_length=length_at_step,
                    )
                    if slot_int not in blocked_array_slots
                    else None
                )
                if packed_array_changes is not None:
                    decoded_changes.extend(packed_array_changes)
                    stats[
                        "static_array"
                        if packed_array_changes[0].encoding == "inplace"
                        else "dynamic_array"
                    ] += 1
                    continue

                # Decode the known side of an incomplete event normally, then
                # clear the synthetic old decode before presentation.
                old_value = old_value or ("0x" + "0" * 64)

                variable = None
                variable_path = None
                old_decoded = None
                new_decoded = None
                mapping_base_slot: Optional[int] = None
                type_label: Optional[str] = None
                mapping_key: Optional[str] = None
                is_mapping: bool = False
                encoding: Optional[str] = None
                key_type: Optional[str] = None
                value_type: Optional[str] = None
                element_type_id: Optional[str] = None
                array_index: Optional[int] = None

                if layout:
                    try:
                        direct_entry = layout_index.first_at(slot_int) if layout_index else None
                        variable = direct_entry.variable if direct_entry else None

                        if variable:
                            stats["layout_direct"] += 1
                            resolution_path = "layout_direct"
                            var_type = layout.get_type(variable.type_id)
                            if var_type:
                                encoding = var_type.encoding
                                is_mapping = var_type.encoding == "mapping"
                                key_type = var_type.key_type
                                value_type = var_type.value_type
                            mapping_base_slot = variable.slot if var_type and var_type.encoding == "mapping" else None
                            variable_path = variable.name
                            decode_type = var_type
                            decode_slot_offset = (
                                slot_int - variable.slot if variable else 0
                            )

                            if var_type and var_type.encoding == "inplace" and var_type.array_length:
                                locations = layout.get_static_array_locations(
                                    variable,
                                    slot_int,
                                )
                                if locations:
                                    static_arr_index = locations[0][0]
                                    stats["static_array"] += 1
                                    resolution_path = "static_array"
                                    variable_path = f"{variable.name}[{static_arr_index}]"
                                    array_index = static_arr_index
                                    if var_type.element_type:
                                        element_type_id = var_type.element_type
                                        value_type = element_type_id
                                        element_type = layout.get_type(element_type_id)
                                        if element_type:
                                            decode_type = element_type
                                            decode_slot_offset = (
                                                slot_int - locations[0][1].slot
                                            )

                            if var_type and var_type.encoding == "mapping":
                                if var_type.value_type:
                                    decode_type = layout.get_type(var_type.value_type)
                                else:
                                    decode_type = None

                            if var_type:
                                try:
                                    old_bytes = bytes.fromhex(old_value[2:])
                                    new_bytes = bytes.fromhex(new_value[2:])
                                    if var_type.encoding == "bytes":
                                        type_label = var_type.label
                                        old_decoded = decoder.decode_dynamic_bytes_slot(old_bytes, type_label)
                                        new_decoded = decoder.decode_dynamic_bytes_slot(new_bytes, type_label)
                                        old_is_long = (old_bytes[-1] & 1) == 1 if old_bytes else False
                                        new_is_long = (new_bytes[-1] & 1) == 1 if new_bytes else False
                                        if old_is_long or new_is_long or old_is_long != new_is_long:
                                            variable_path = f"{variable.name} (length)"
                                            value_type = "uint256"
                                            def extract_string_length(raw_bytes: bytes, is_long: bool) -> int:
                                                if not raw_bytes or raw_bytes == bytes(32):
                                                    return 0
                                                if is_long:
                                                    full_value = int.from_bytes(raw_bytes, "big")
                                                    return (full_value - 1) // 2
                                                else:
                                                    return raw_bytes[-1] // 2
                                            old_length = extract_string_length(old_bytes, old_is_long)
                                            new_length = extract_string_length(new_bytes, new_is_long)
                                            old_decoded = DecodedValue(raw=old_value, decoded=old_length, type_label="uint256")
                                            new_decoded = DecodedValue(raw=new_value, decoded=new_length, type_label="uint256")
                                    elif var_type.encoding == "dynamic_array" or (var_type.element_type and "[]" in (var_type.label or "")):
                                        encoding = "dynamic_array"
                                        old_length = int.from_bytes(old_bytes, "big")
                                        new_length = int.from_bytes(new_bytes, "big")
                                        old_decoded = DecodedValue(raw=old_value, decoded=old_length, type_label="uint256")
                                        new_decoded = DecodedValue(raw=new_value, decoded=new_length, type_label="uint256")
                                        variable_path = f"{variable.name} (array length)"
                                    elif decode_type:
                                        old_decoded = decoder.decode(
                                            old_bytes,
                                            decode_type,
                                            variable.offset,
                                            decode_slot_offset,
                                        )
                                        new_decoded = decoder.decode(
                                            new_bytes,
                                            decode_type,
                                            variable.offset,
                                            decode_slot_offset,
                                        )
                                except Exception as e:
                                    logger.warning(f"Failed to decode change at slot {slot_hex}: {e}")
                        else:
                            # Try preimage lookup
                            if slot_hex in preimage_lookup:
                                preimage = preimage_lookup[slot_hex]
                                preimage_match = self.slot_resolver.try_match_slot_from_preimage(
                                    slot_hex,
                                    preimage,
                                    layout,
                                    preimage_lookup,
                                    struct_offsets=struct_offsets,
                                )
                                if preimage_match:
                                    stats["preimage_lookup"] += 1
                                    resolution_path = "preimage_lookup"
                                    variable = preimage_match.get("variable")
                                    mapping_base_slot = preimage_match.get("base_slot")
                                    mapping_key = preimage_match.get("key")
                                    variable_path = preimage_match.get("path")
                                    is_mapping = True
                                    encoding = preimage_match.get("encoding")
                                    key_type = preimage_match.get("key_type")
                                    value_type = preimage_match.get("value_type")
                                    decode_type = preimage_match.get("decode_type")

                                    # Handle struct offset with nested mapping (e.g., users[addr].allowance[spender])
                                    # The outer_key is the key for the mapping at the struct offset
                                    struct_offset_from_preimage = preimage_match.get("struct_offset")
                                    outer_key = preimage_match.get("outer_key")
                                    if struct_offset_from_preimage and variable:
                                        field_name, field_type = self.slot_resolver.resolve_struct_field(
                                            variable, struct_offset_from_preimage, layout
                                        )
                                        if field_name:
                                            # Build path: base_path.field_name
                                            base_path = preimage_match.get("path", "")
                                            # Replace +N with .field_name
                                            if f"+{struct_offset_from_preimage}" in base_path:
                                                variable_path = base_path.replace(
                                                    f"+{struct_offset_from_preimage}", f".{field_name}"
                                                )
                                            else:
                                                variable_path = f"{base_path}.{field_name}" if base_path else field_name
                                            # If field is a mapping and we have outer_key, append [key]
                                            if outer_key and field_type and field_type.encoding == "mapping":
                                                variable_path = f"{variable_path}[{outer_key}]"
                                                # Update mapping_key to include outer_key
                                                if mapping_key:
                                                    mapping_key = f"{mapping_key}, {outer_key}"
                                                else:
                                                    mapping_key = outer_key
                                            decode_type = field_type

                                    if encoding == "mapping_to_array":
                                        stats["mapping_to_array"] += 1
                                        resolution_path = "mapping_to_array"
                                        array_match = (
                                            self.slot_resolver.try_match_mapping_to_array_slot(
                                                slot_int,
                                                layout,
                                                mapping_to_array_index,
                                                mapping_to_array_roots,
                                                length_at_step,
                                            )
                                            if slot_int not in blocked_array_slots
                                            else None
                                        )
                                        if array_match:
                                            variable_path = array_match["path"]
                                            mapping_key = array_match.get("mapping_key")
                                            array_index = array_match.get("array_index")
                                            element_type = array_match.get("element_type")
                                            element_type_id = (
                                                element_type.id if element_type else None
                                            )
                                            decode_type = array_match.get("decode_type")
                                        else:
                                            variable = None
                                            variable_path = None
                                            mapping_base_slot = None
                                            mapping_key = None
                                            is_mapping = False
                                            encoding = None
                                            key_type = None
                                            value_type = None
                                            decode_type = None

                                    if decode_type:
                                        try:
                                            old_bytes = bytes.fromhex(old_value[2:])
                                            new_bytes = bytes.fromhex(new_value[2:])
                                            old_decoded = decoder.decode(old_bytes, decode_type, variable.offset if variable else 0)
                                            new_decoded = decoder.decode(new_bytes, decode_type, variable.offset if variable else 0)
                                        except Exception:
                                            pass

                            # Try static array
                            if not variable and static_array_index:
                                static_match = self.slot_resolver.try_match_static_array_slot(slot_int, layout, static_array_index)
                                if static_match:
                                    stats["static_array"] += 1
                                    resolution_path = "static_array"
                                    variable = static_match["variable"]
                                    variable_path = static_match["path"]
                                    encoding = static_match.get("encoding")
                                    array_index = static_match.get("array_index")
                                    element_type = static_match.get("element_type")
                                    if element_type:
                                        value_type = element_type.label if hasattr(element_type, 'label') else str(element_type)
                                        try:
                                            old_bytes = bytes.fromhex(old_value[2:])
                                            new_bytes = bytes.fromhex(new_value[2:])
                                            old_decoded = decoder.decode(old_bytes, element_type, 0)
                                            new_decoded = decoder.decode(new_bytes, element_type, 0)
                                        except Exception:
                                            pass

                            # Try dynamic array
                            if (
                                not variable
                                and dynamic_array_index
                                and slot_int not in blocked_array_slots
                            ):
                                array_match = self.slot_resolver.try_match_dynamic_array_slot(
                                    slot_int,
                                    layout,
                                    dynamic_array_index,
                                    length_at_step,
                                )
                                if array_match:
                                    stats["dynamic_array"] += 1
                                    resolution_path = "dynamic_array"
                                    variable = array_match["variable"]
                                    variable_path = array_match["path"]
                                    encoding = array_match.get("encoding")
                                    array_index = array_match.get("array_index")
                                    element_type = array_match.get("element_type")
                                    element_type_id = element_type.id if element_type else None
                                    decode_type = array_match.get("decode_type")
                                    struct_slot_offset = array_match.get("struct_slot_offset", 0) or 0
                                    slot_members = array_match.get("slot_members")
                                    if slot_members and len(slot_members) > 1:
                                        value_type = "packed"
                                        try:
                                            old_bytes = bytes.fromhex(old_value[2:])
                                            new_bytes = bytes.fromhex(new_value[2:])
                                            old_packed = decoder.decode_packed_slot(old_bytes, slot_members, layout.types if layout else {})
                                            new_packed = decoder.decode_packed_slot(new_bytes, slot_members, layout.types if layout else {})
                                            old_decoded = DecodedValue(raw=old_value, decoded={k: v.decoded for k, v in old_packed.items()}, type_label="packed")
                                            new_decoded = DecodedValue(raw=new_value, decoded={k: v.decoded for k, v in new_packed.items()}, type_label="packed")
                                        except Exception:
                                            pass
                                    elif decode_type:
                                        value_type = decode_type.label
                                        try:
                                            old_bytes = bytes.fromhex(old_value[2:])
                                            new_bytes = bytes.fromhex(new_value[2:])
                                            old_decoded = decoder.decode(old_bytes, decode_type, 0, struct_slot_offset)
                                            new_decoded = decoder.decode(new_bytes, decode_type, 0, struct_slot_offset)
                                        except Exception:
                                            pass

                            # Try mapping-to-array
                            if (
                                not variable
                                and mapping_to_array_index
                                and slot_int not in blocked_array_slots
                            ):
                                m2a_match = self.slot_resolver.try_match_mapping_to_array_slot(
                                    slot_int,
                                    layout,
                                    mapping_to_array_index,
                                    mapping_to_array_roots,
                                    length_at_step,
                                )
                                if m2a_match:
                                    stats["mapping_to_array"] += 1
                                    resolution_path = "mapping_to_array"
                                    variable = m2a_match["variable"]
                                    variable_path = m2a_match["path"]
                                    encoding = m2a_match.get("encoding")
                                    is_mapping = True
                                    mapping_key = m2a_match.get("mapping_key")
                                    array_index = m2a_match.get("array_index")
                                    element_type = m2a_match.get("element_type")
                                    element_type_id = element_type.id if element_type else None
                                    decode_type = m2a_match.get("decode_type")
                                    struct_slot_offset = m2a_match.get("struct_slot_offset", 0) or 0
                                    slot_members = m2a_match.get("slot_members")
                                    if slot_members and len(slot_members) > 1:
                                        value_type = "packed"
                                        try:
                                            old_bytes = bytes.fromhex(old_value[2:])
                                            new_bytes = bytes.fromhex(new_value[2:])
                                            old_packed = decoder.decode_packed_slot(old_bytes, slot_members, layout.types if layout else {})
                                            new_packed = decoder.decode_packed_slot(new_bytes, slot_members, layout.types if layout else {})
                                            old_decoded = DecodedValue(raw=old_value, decoded={k: v.decoded for k, v in old_packed.items()}, type_label="packed")
                                            new_decoded = DecodedValue(raw=new_value, decoded={k: v.decoded for k, v in new_packed.items()}, type_label="packed")
                                        except Exception:
                                            pass
                                    elif decode_type:
                                        value_type = decode_type.label
                                        try:
                                            old_bytes = bytes.fromhex(old_value[2:])
                                            new_bytes = bytes.fromhex(new_value[2:])
                                            old_decoded = decoder.decode(old_bytes, decode_type, 0, struct_slot_offset)
                                            new_decoded = decoder.decode(new_bytes, decode_type, 0, struct_slot_offset)
                                        except Exception:
                                            pass

                            # Try dynamic bytes
                            if not variable and dynamic_bytes_index:
                                bytes_match = self.slot_resolver.try_match_dynamic_bytes_slot(
                                    slot_int,
                                    dynamic_bytes_index,
                                )
                                if bytes_match:
                                    stats["dynamic_bytes"] += 1
                                    resolution_path = "dynamic_bytes"
                                    variable = bytes_match["variable"]
                                    variable_path = bytes_match["path"]
                                    encoding = bytes_match.get("encoding")
                                    data_offset = bytes_match.get("data_offset", 0)
                                    try:
                                        old_bytes = bytes.fromhex(old_value[2:])
                                        new_bytes = bytes.fromhex(new_value[2:])
                                        var_type = layout.get_type(variable.type_id)
                                        type_label = var_type.label if var_type else "bytes"
                                        old_decoded = decoder.decode_dynamic_bytes_data_slot(old_bytes, type_label, data_offset)
                                        new_decoded = decoder.decode_dynamic_bytes_data_slot(new_bytes, type_label, data_offset)
                                    except Exception as e:
                                        logger.warning(f"Failed to decode dynamic bytes data slot: {e}")
                    except Exception as e:
                        logger.error(f"Slot matching/decoding failed for slot {slot_hex}: {e}", exc_info=True)

                # Handle struct offsets
                if layout and not variable and slot_hex not in preimage_lookup:
                    for struct_offset, base_match in self.slot_resolver.find_struct_offset_matches(
                        slot_int,
                        layout,
                        preimage_lookup,
                        struct_offsets=struct_offsets,
                    ):
                        base_var = base_match.get("variable")
                        if base_var:
                            stats["struct_offset"] += 1
                            resolution_path = "struct_offset"
                            variable = base_var
                            mapping_base_slot = base_match.get("base_slot")
                            mapping_key = base_match.get("key")
                            base_path = base_match.get("path", "")
                            is_mapping = True
                            encoding = base_match.get("encoding")
                            key_type = base_match.get("key_type")
                            value_type = base_match.get("value_type")
                            field_name, field_type = self.slot_resolver.resolve_match_struct_field(
                                base_match, struct_offset, layout
                            )
                            variable_path = (
                                f"{base_path}.{field_name}" if base_path else field_name
                            )
                            if field_type:
                                value_type = field_type.id
                                try:
                                    old_bytes = bytes.fromhex(old_value[2:])
                                    new_bytes = bytes.fromhex(new_value[2:])
                                    old_decoded = decoder.decode(old_bytes, field_type, 0)
                                    new_decoded = decoder.decode(new_bytes, field_type, 0)
                                except Exception:
                                    pass
                            break

                # Heuristic decode if no layout or no decoded values
                if (not layout or not variable) and not old_decoded:
                    try:
                        old_bytes = bytes.fromhex(old_value[2:])
                        new_bytes = bytes.fromhex(new_value[2:])
                        old_decoded = decoder.decode_heuristic(old_bytes)
                        new_decoded = decoder.decode_heuristic(new_bytes)
                    except Exception:
                        pass

                if resolution_path == "unknown":
                    stats["heuristic"] += 1

                if variable and is_mapping:
                    matched_slots[slot_int] = {
                        "variable": variable,
                        "mapping_base_slot": mapping_base_slot,
                        "mapping_key": mapping_key,
                        "variable_path": variable_path,
                        "encoding": encoding,
                        "key_type": key_type,
                        "value_type": value_type,
                    }

                if reported_old_value is None:
                    old_decoded = None
                decoded_changes.append(
                    StorageChange(
                        slot=slot_hex,
                        mapping_base_slot=mapping_base_slot,
                        old_value=reported_old_value,
                        new_value=new_value,
                        variable=variable,
                        variable_path=variable_path,
                        old_decoded=old_decoded,
                        new_decoded=new_decoded,
                        mapping_key=mapping_key,
                        is_mapping=is_mapping,
                        encoding=encoding,
                        key_type=key_type,
                        value_type=value_type,
                        element_type_id=element_type_id,
                        array_index=array_index,
                        change_index=exec_index,
                        pc=pc,
                    )
                )

            except Exception as e:
                logger.error(f"Fatal error decoding slot {slot_hex}: {e}", exc_info=True)
                try:
                    fallback_old_value = old_value or ("0x" + "0" * 64)
                    old_bytes = bytes.fromhex(fallback_old_value[2:]) if fallback_old_value.startswith("0x") else bytes.fromhex(fallback_old_value)
                    new_bytes = bytes.fromhex(new_value[2:]) if new_value.startswith("0x") else bytes.fromhex(new_value)
                    old_decoded = decoder.decode_heuristic(old_bytes)
                    new_decoded = decoder.decode_heuristic(new_bytes)
                except Exception:
                    old_decoded = None
                    new_decoded = None

                if reported_old_value is None:
                    old_decoded = None
                decoded_changes.append(
                    StorageChange(
                        slot=slot_hex,
                        mapping_base_slot=None,
                        old_value=reported_old_value,
                        new_value=new_value,
                        variable=None,
                        variable_path=None,
                        old_decoded=old_decoded,
                        new_decoded=new_decoded,
                        mapping_key=None,
                        is_mapping=False,
                        encoding=None,
                        key_type=None,
                        value_type=None,
                        element_type_id=None,
                        array_index=None,
                        change_index=exec_index,
                        pc=pc,
                    )
                )

        # Second pass: struct offset detection
        for i, change in enumerate(decoded_changes):
            if change.variable is None:
                slot_int = int(change.slot, 16)
                if slot_int in blocked_array_slots:
                    continue
                for base_slot_int, base_match in matched_slots.items():
                    offset = slot_int - base_slot_int
                    if offset <= 0:
                        continue
                    base_var = base_match["variable"]
                    field_name, _ = self.slot_resolver.resolve_struct_field(
                        base_var,
                        offset,
                        layout,
                    ) if layout else (None, None)
                    if field_name:
                        base_key = base_match["mapping_key"]
                        decoded_changes[i] = StorageChange(
                            slot=change.slot,
                            mapping_base_slot=base_match["mapping_base_slot"],
                            old_value=change.old_value,
                            new_value=change.new_value,
                            variable=base_var,
                            variable_path=f"{base_var.name}[{base_key}].{field_name}",
                            old_decoded=change.old_decoded,
                            new_decoded=change.new_decoded,
                            mapping_key=base_key,
                            is_mapping=True,
                            encoding=base_match.get("encoding"),
                            key_type=base_match.get("key_type"),
                            value_type=base_match.get("value_type"),
                            change_index=change.change_index,
                            pc=change.pc,
                        )
                        break

        resolved = stats["layout_direct"] + stats["preimage_lookup"] + stats["struct_offset"] + stats["dynamic_array"] + stats["mapping_to_array"] + stats["dynamic_bytes"] + stats["legacy_vyper"]
        logger.info(
            f"Slot resolution: {stats['total']} total, {resolved} resolved "
            f"(layout={stats['layout_direct']}, preimage={stats['preimage_lookup']}, "
            f"struct_offset={stats['struct_offset']}, array={stats['dynamic_array']}, "
            f"map_to_array={stats['mapping_to_array']}, bytes={stats['dynamic_bytes']}, "
            f"legacy_vyper={stats['legacy_vyper']}), "
            f"{stats['heuristic']} heuristic"
        )
        return decoded_changes

    def _decode_packed_array_change(
        self,
        *,
        slot_int: int,
        slot_hex: str,
        old_value: str | None,
        new_value: str,
        pc: int | None,
        exec_index: int,
        layout: StorageLayout | None,
        layout_index: LayoutIndex | None,
        decoder: TypeDecoder,
        dynamic_array_index: dict,
        mapping_to_array_index: dict[int, dict],
        array_roots: tuple[tuple[int, bool], ...],
        array_length: Callable[[int], int | None],
    ) -> list[StorageChange] | None:
        """Expand a changed packed-array word into every changed element.

        An SSTORE is still retained as a raw slot event by the journal layer.
        This projection is specifically for human-readable paths: one word can
        contain several array elements and therefore several logical changes.
        """
        if layout is None:
            return None

        direct_entry = layout_index.first_at(slot_int) if layout_index else None
        variable = direct_entry.variable if direct_entry else None
        element_type = None
        locations: tuple[tuple[int, StorageLocation], ...] = ()
        encoding = "inplace"
        mapping_key = None
        mapping_base_slot = None
        path_prefix = None

        if variable:
            variable_type = layout.get_type(variable.type_id)
            if (
                variable_type
                and variable_type.encoding == "inplace"
                and variable_type.array_length is not None
                and variable_type.element_type
            ):
                element_type = layout.get_type(variable_type.element_type)
                packing = array_packing(element_type)
                if packing.is_packed:
                    locations = packing.locations_in_slot(
                        variable.slot,
                        slot_int,
                        length=variable_type.array_length,
                    )
                    path_prefix = variable.name

        if not locations:
            # Prefer the closest known data start. The existing trace-derived
            # indexes are exact starts; this avoids choosing an unrelated array
            # when several arrays precede the numeric slot value.
            end = bisect_right(array_roots, (slot_int, True))
            for root_index in range(end - 1, -1, -1):
                data_start, is_mapping_array = array_roots[root_index]
                entry = (
                    mapping_to_array_index[data_start]
                    if is_mapping_array
                    else dynamic_array_index[data_start]
                )
                if is_mapping_array:
                    candidate_type = entry.get("element_type")
                    candidate_variable = entry.get("variable")
                else:
                    candidate_type = entry.get("element_type")
                    candidate_variable = entry.get("variable")

                packing = array_packing(candidate_type)
                if not packing.is_packed:
                    continue
                proven_length = entry.get("array_length")
                if proven_length is None:
                    length_slot = entry.get("array_length_slot")
                    if length_slot is not None:
                        proven_length = array_length(
                            int(length_slot, 16)
                            if isinstance(length_slot, str)
                            else length_slot
                        )
                if proven_length is None:
                    continue

                variable = candidate_variable
                element_type = candidate_type
                locations = packing.locations_in_slot(
                    data_start,
                    slot_int,
                    length=proven_length,
                )
                if is_mapping_array:
                    encoding = "mapping_to_array"
                    mapping_key = entry.get("key", "?")
                    mapping_base_slot = entry.get("base_slot")
                    path_prefix = entry.get("path") or (
                        f"{variable.name}[{mapping_key}]" if variable else None
                    )
                else:
                    encoding = "dynamic_array"
                    path_prefix = variable.name if variable else None
                break

        if not locations or variable is None or element_type is None or path_prefix is None:
            return None

        if old_value is None:
            return [
                StorageChange(
                    slot=slot_hex,
                    old_value=None,
                    new_value=new_value,
                    mapping_base_slot=mapping_base_slot,
                    variable=variable,
                    variable_path=f"{path_prefix} (packed word)",
                    mapping_key=mapping_key,
                    is_mapping=encoding == "mapping_to_array",
                    encoding=encoding,
                    value_type="packed",
                    element_type_id=element_type.id,
                    change_index=exec_index,
                    pc=pc,
                    state_values_known=False,
                )
            ]
        old_bytes = bytes.fromhex(old_value.removeprefix("0x")).rjust(32, b"\x00")
        new_bytes = bytes.fromhex(new_value.removeprefix("0x")).rjust(32, b"\x00")
        result: list[StorageChange] = []

        for array_index, location in locations:
            start = 32 - location.byte_offset - location.byte_size
            end = 32 - location.byte_offset
            if old_bytes[start:end] == new_bytes[start:end]:
                continue

            result.append(
                StorageChange(
                    slot=slot_hex,
                    old_value=old_value,
                    new_value=new_value,
                    mapping_base_slot=mapping_base_slot,
                    variable=variable,
                    variable_path=f"{path_prefix}[{array_index}]",
                    old_decoded=decoder.decode(
                        old_bytes,
                        element_type,
                        location.byte_offset,
                    ),
                    new_decoded=decoder.decode(
                        new_bytes,
                        element_type,
                        location.byte_offset,
                    ),
                    mapping_key=mapping_key,
                    is_mapping=encoding == "mapping_to_array",
                    encoding=encoding,
                    value_type=element_type.label,
                    element_type_id=element_type.id,
                    array_index=array_index,
                    change_index=exec_index,
                    pc=pc,
                )
            )

        if not result:
            # A no-op SSTORE proves that the packed word was touched but does
            # not reveal which source-level element motivated the write.
            result.append(
                StorageChange(
                    slot=slot_hex,
                    old_value=old_value,
                    new_value=new_value,
                    mapping_base_slot=mapping_base_slot,
                    variable=variable,
                    variable_path=f"{path_prefix} (packed word)",
                    mapping_key=mapping_key,
                    is_mapping=encoding == "mapping_to_array",
                    encoding=encoding,
                    value_type="packed",
                    element_type_id=element_type.id,
                    change_index=exec_index,
                    pc=pc,
                )
            )
        return result
