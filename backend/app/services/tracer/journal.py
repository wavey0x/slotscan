"""Rollback-aware transaction storage-write journal."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging

from app.services.layout_index import StorageNamespace
from app.utils.addresses import normalize_evm_address


ZERO_WORD = "0x" + "0" * 64
logger = logging.getLogger(__name__)


class WriteEffect(str, Enum):
    APPLIED = "applied"
    NOOP = "noop"
    REVERTED = "reverted"


@dataclass(frozen=True)
class StorageWriteEvent:
    address: str
    code_address: str | None
    slot: str
    value: str
    step: int
    pc: int | None
    depth: int
    frame_id: int
    opcode: str
    namespace: StorageNamespace
    value_before: str | None = None
    changed_value: bool | None = None
    frame_outcome: str = "applied"
    effect: WriteEffect = WriteEffect.APPLIED

    @property
    def value_after(self) -> str:
        return self.value


@dataclass(frozen=True)
class SlotHistory:
    address: str
    slot: str
    namespace: StorageNamespace
    initial_value: str | None
    final_value: str | None
    writes: tuple[StorageWriteEvent, ...]
    net_changed: bool

    @property
    def state_values_known(self) -> bool:
        return self.initial_value is not None and self.final_value is not None


@dataclass(frozen=True)
class TraceCapabilities:
    execution_order: bool
    frame_outcomes: bool
    write_old_values: bool
    final_state_values: bool
    state_reconciliation: bool
    transient_storage: bool


@dataclass(frozen=True)
class StorageJournal:
    events: tuple[StorageWriteEvent, ...]
    histories: tuple[SlotHistory, ...]
    capabilities: TraceCapabilities
    root_succeeded: bool
    evm_step_count: int | None = None

    def for_contract(
        self,
        address: str,
        namespace: StorageNamespace = StorageNamespace.PERSISTENT,
    ) -> tuple[SlotHistory, ...]:
        normalized = address.lower()
        return tuple(
            history
            for history in self.histories
            if history.address == normalized and history.namespace == namespace
        )


class StorageJournalBuilder:
    """Reconcile raw write evidence with authoritative pre/post state."""

    def build(
        self,
        writes: list[dict],
        prestate_diff: dict,
        *,
        root_succeeded: bool,
        evm_step_count: int | None = None,
    ) -> StorageJournal:
        initial_state, final_state, net_changed_keys = self._extract_state(prestate_diff)
        current_state = dict(initial_state)
        rollback_overlays: dict[
            int, dict[tuple[str, StorageNamespace, str], str]
        ] = {}
        rollback_parents: dict[int, int | None] = {}
        events: list[StorageWriteEvent] = []

        for raw in sorted(writes, key=lambda item: item.get("index", 0)):
            address = normalize_evm_address(raw.get("address")) or ""
            if not address:
                # Address-less writes cannot be safely assigned to a contract.
                continue
            namespace = StorageNamespace(raw.get("namespace", "persistent"))
            opcode = raw.get("opcode") or (
                "TSTORE" if namespace == StorageNamespace.TRANSIENT else "SSTORE"
            )
            slot = self._normalize_word(raw.get("slot", "0x0"))
            value = self._normalize_word(raw.get("value", ZERO_WORD))
            key = (address, namespace, slot)
            reverted = not root_succeeded or bool(raw.get("frame_reverted"))
            rollback_frame_id = raw.get("rollback_frame_id")
            if reverted and rollback_frame_id is None:
                rollback_frame_id = 0
            if rollback_frame_id is not None:
                rollback_frame_id = int(rollback_frame_id)
                rollback_parents.setdefault(
                    rollback_frame_id,
                    raw.get("rollback_parent_id"),
                )

            if namespace == StorageNamespace.TRANSIENT:
                current_state.setdefault(key, ZERO_WORD)

            value_before = raw.get("old_value")
            if value_before is not None:
                value_before = self._normalize_word(value_before)
                current_state.setdefault(key, value_before)
                initial_state.setdefault(key, value_before)
            else:
                value_before = self._effective_value(
                    key,
                    current_state,
                    rollback_overlays,
                    rollback_parents,
                    rollback_frame_id if reverted else None,
                )

            changed_value = (
                value_before != value if value_before is not None else None
            )
            if reverted:
                effect = WriteEffect.REVERTED
            elif changed_value is False:
                effect = WriteEffect.NOOP
            else:
                effect = WriteEffect.APPLIED

            event = StorageWriteEvent(
                address=address,
                code_address=normalize_evm_address(raw.get("code_address")),
                slot=slot,
                value=value,
                value_before=value_before,
                step=int(raw.get("index", 0)),
                pc=raw.get("pc"),
                depth=int(raw.get("depth", 1)),
                frame_id=int(raw.get("frame_id", 0)),
                opcode=opcode,
                namespace=namespace,
                changed_value=changed_value,
                frame_outcome="reverted" if reverted else "applied",
                effect=effect,
            )
            events.append(event)

            if effect == WriteEffect.REVERTED and rollback_frame_id is not None:
                rollback_overlays.setdefault(rollback_frame_id, {})[key] = value
            else:
                current_state[key] = value

        grouped: dict[
            tuple[str, StorageNamespace, str], list[StorageWriteEvent]
        ] = {}
        for event in events:
            grouped.setdefault((event.address, event.namespace, event.slot), []).append(event)

        histories: list[SlotHistory] = []
        for key, slot_events in grouped.items():
            address, namespace, slot = key
            initial_value = initial_state.get(key)
            final_value: str | None

            if namespace == StorageNamespace.TRANSIENT:
                initial_value = ZERO_WORD
                final_value = ZERO_WORD
                net_changed = False
            elif key in final_state:
                final_value = final_state[key]
                net_changed = key in net_changed_keys
            elif not root_succeeded:
                final_value = initial_value
                net_changed = False
            elif key not in net_changed_keys:
                # prestateTracer diff mode omits restored/no-op slots. Once the
                # trace gives us their initial word, their final word is equal.
                final_value = initial_value
                net_changed = False
            else:
                final_value = None
                net_changed = True

            histories.append(
                SlotHistory(
                    address=address,
                    slot=slot,
                    namespace=namespace,
                    initial_value=initial_value,
                    final_value=final_value,
                    writes=tuple(slot_events),
                    net_changed=net_changed,
                )
            )

        histories.sort(key=lambda item: item.writes[0].step if item.writes else 0)
        all_old_values_known = all(event.value_before is not None for event in events)
        all_final_values_known = all(history.final_value is not None for history in histories)
        mismatches = [
            history
            for history in histories
            if history.namespace == StorageNamespace.PERSISTENT
            and current_state.get(
                (history.address, history.namespace, history.slot),
                history.initial_value,
            )
            != history.final_value
        ]
        state_reconciliation = all_final_values_known and not mismatches
        if mismatches:
            logger.warning(
                "Storage journal final-state reconciliation failed for %s slots",
                len(mismatches),
            )

        return StorageJournal(
            events=tuple(events),
            histories=tuple(histories),
            capabilities=TraceCapabilities(
                execution_order=bool(evm_step_count),
                frame_outcomes=(
                    all("frame_reverted" in write for write in writes)
                    and state_reconciliation
                ),
                write_old_values=all_old_values_known and state_reconciliation,
                final_state_values=(
                    all_final_values_known and state_reconciliation
                ),
                state_reconciliation=state_reconciliation,
                transient_storage=any(
                    event.namespace == StorageNamespace.TRANSIENT for event in events
                ),
            ),
            root_succeeded=root_succeeded,
            evm_step_count=evm_step_count,
        )

    @staticmethod
    def _effective_value(
        key: tuple[str, StorageNamespace, str],
        current_state: dict[tuple[str, StorageNamespace, str], str],
        rollback_overlays: dict[
            int, dict[tuple[str, StorageNamespace, str], str]
        ],
        rollback_parents: dict[int, int | None],
        rollback_frame_id: int | None,
    ) -> str | None:
        current = rollback_frame_id
        seen: set[int] = set()
        while current is not None and current not in seen:
            seen.add(current)
            overlay = rollback_overlays.get(current, {})
            if key in overlay:
                return overlay[key]
            parent = rollback_parents.get(current)
            current = int(parent) if parent is not None else None
        return current_state.get(key)

    def _extract_state(
        self, prestate_diff: dict
    ) -> tuple[
        dict[tuple[str, StorageNamespace, str], str],
        dict[tuple[str, StorageNamespace, str], str],
        set[tuple[str, StorageNamespace, str]],
    ]:
        pre_by_address = prestate_diff.get("pre", {})
        post_by_address = prestate_diff.get("post", {})
        initial: dict[tuple[str, StorageNamespace, str], str] = {}
        final: dict[tuple[str, StorageNamespace, str], str] = {}
        changed: set[tuple[str, StorageNamespace, str]] = set()

        addresses = set(pre_by_address) | set(post_by_address)
        for raw_address in addresses:
            address = normalize_evm_address(raw_address) or raw_address.lower()
            pre_storage = pre_by_address.get(raw_address, {}).get("storage", {})
            post_storage = post_by_address.get(raw_address, {}).get("storage", {})
            raw_slots = set(pre_storage) | set(post_storage)
            for raw_slot in raw_slots:
                slot = self._normalize_word(raw_slot)
                key = (address, StorageNamespace.PERSISTENT, slot)
                before = self._normalize_word(pre_storage.get(raw_slot, ZERO_WORD))
                after = self._normalize_word(post_storage.get(raw_slot, ZERO_WORD))
                initial[key] = before
                final[key] = after
                if before != after:
                    changed.add(key)

        return initial, final, changed

    @staticmethod
    def _normalize_word(value: str | int) -> str:
        if isinstance(value, int):
            return f"0x{value:064x}"
        clean = value[2:] if value.startswith("0x") else value
        return "0x" + clean.lower().zfill(64)
