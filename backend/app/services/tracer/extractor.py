"""Transaction-level RPC evidence extraction, independent of decoding/layouts."""

from dataclasses import dataclass
import logging

from app.services.tracer.rpc_client import TraceRPCClient


logger = logging.getLogger(__name__)
ZERO_WORD = "0x" + "0" * 64


@dataclass(frozen=True)
class TransactionTraceEvidence:
    receipt: dict
    prestate_diff: dict
    writes: list[dict]
    sha3_operations: list[dict]
    evm_step_count: int


class TransactionTraceExtractor:
    """Fetch canonical raw evidence once for all touched contracts."""

    def __init__(self, rpc_client: TraceRPCClient):
        self.rpc_client = rpc_client

    async def extract(self, chain_id: int, tx_hash: str) -> TransactionTraceEvidence:
        # Receipt and prestate calls are deliberately kept together here so
        # contract projections never issue their own transaction trace.
        import asyncio

        prestate_diff, receipt = await asyncio.gather(
            self.rpc_client.execute_prestate_trace(chain_id, tx_hash),
            self.rpc_client.get_receipt(chain_id, tx_hash),
        )
        writes, sha3_operations, evm_step_count = (
            await self.rpc_client.execute_structlogs_trace(
                chain_id,
                tx_hash,
            )
        )
        self._normalize_diff(prestate_diff)
        missing = self._missing_initial_values(writes, prestate_diff)
        has_persistent_writes = any(
            write.get("namespace", "persistent") == "persistent"
            and write.get("address")
            for write in writes
        )
        if has_persistent_writes:
            try:
                full_prestate = await self.rpc_client.execute_prestate_trace(
                    chain_id,
                    tx_hash,
                    diff_mode=False,
                )
                self._merge_observed_prestate(
                    prestate_diff,
                    full_prestate,
                    missing,
                )
            except Exception as exc:
                # Preserve raw events with nullable before-values. A failed
                # enrichment trace must not erase the write inventory.
                logger.warning(
                    "Could not recover %s observed prestate values: %s",
                    len(missing),
                    exc,
                )
        return TransactionTraceEvidence(
            receipt=receipt,
            prestate_diff=prestate_diff,
            writes=writes,
            sha3_operations=sha3_operations,
            evm_step_count=evm_step_count,
        )

    @staticmethod
    def _word(value: str | int) -> str:
        if isinstance(value, int):
            return f"0x{value:064x}"
        return "0x" + value.removeprefix("0x").lower().zfill(64)

    @classmethod
    def _normalize_diff(cls, diff: dict) -> None:
        for side in ("pre", "post"):
            normalized_accounts = {}
            for address, state in diff.get(side, {}).items():
                normalized = dict(state)
                normalized["storage"] = {
                    cls._word(slot): cls._word(value)
                    for slot, value in state.get("storage", {}).items()
                }
                normalized_accounts[address.lower()] = normalized
            diff[side] = normalized_accounts

    @classmethod
    def _missing_initial_values(
        cls,
        writes: list[dict],
        diff: dict,
    ) -> set[tuple[str, str]]:
        pre = diff.get("pre", {})
        missing = set()
        first_event_old_values: dict[tuple[str, str], str | None] = {}
        for write in writes:
            if write.get("namespace", "persistent") != "persistent":
                continue
            address = (write.get("address") or "").lower()
            if not address:
                continue
            slot = cls._word(write.get("slot", "0x0"))
            key = (address, slot)
            first_event_old_values.setdefault(key, write.get("old_value"))
            if (
                slot not in pre.get(address, {}).get("storage", {})
                and first_event_old_values[key] is None
            ):
                missing.add((address, slot))
        return missing

    @classmethod
    def _merge_observed_prestate(
        cls,
        diff: dict,
        full_prestate: dict,
        missing: set[tuple[str, str]],
    ) -> None:
        accounts = {address.lower(): state for address, state in full_prestate.items()}
        pre = diff.setdefault("pre", {})
        post = diff.setdefault("post", {})
        normalized_storage_by_address = {
            address: {
                cls._word(raw_slot): cls._word(value)
                for raw_slot, value in state.get("storage", {}).items()
            }
            for address, state in accounts.items()
        }

        # Full prestate mode records every storage word the execution observed,
        # including unchanged reads such as Solidity dynamic-array lengths.
        # Retain that bounded evidence. A word absent from both sides of the
        # original diff is unchanged (or restored), so mirror it into post.
        for address, storage in normalized_storage_by_address.items():
            pre_storage = pre.setdefault(address, {}).setdefault("storage", {})
            post_storage = post.setdefault(address, {}).setdefault("storage", {})
            for slot, initial in storage.items():
                absent_from_diff = slot not in pre_storage and slot not in post_storage
                pre_storage.setdefault(slot, initial)
                if absent_from_diff:
                    post_storage[slot] = initial

        for address, slot in missing:
            initial = normalized_storage_by_address.get(address, {}).get(
                slot,
                ZERO_WORD,
            )
            pre_storage = pre.setdefault(address, {}).setdefault("storage", {})
            post_storage = post.setdefault(address, {}).setdefault("storage", {})
            absent_from_diff = slot not in pre_storage and slot not in post_storage
            pre_storage.setdefault(slot, initial)
            # Only an omitted post value proves no durable change. A post-only
            # diff is the normal zero-to-nonzero net-change representation.
            if absent_from_diff:
                post_storage[slot] = initial
