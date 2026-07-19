"""Transaction-level RPC evidence extraction, independent of decoding/layouts."""

from dataclasses import dataclass
import logging

from app.services.tracer.rpc_client import TraceRPCClient


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransactionTraceEvidence:
    receipt: dict
    prestate_diff: dict
    writes: list[dict]
    sha3_operations: list[dict]
    evm_step_count: int
    degraded_reason: str | None = None


class TransactionTraceExtractor:
    """Fetch canonical raw evidence once for all touched contracts."""

    def __init__(self, rpc_client: TraceRPCClient):
        self.rpc_client = rpc_client

    async def extract(self, chain_id: int, tx_hash: str) -> TransactionTraceEvidence:
        # Receipt and prestate calls are deliberately kept together here so
        # contract projections never issue their own transaction trace.
        import asyncio

        prestate_diff, receipt = await asyncio.gather(
            self.rpc_client.execute_prestate_diff(chain_id, tx_hash),
            self.rpc_client.get_receipt(chain_id, tx_hash),
        )
        compact = await self.rpc_client.execute_compact_trace(
            chain_id,
            tx_hash,
        )
        self._normalize_diff(prestate_diff)
        self._merge_observed_prestate(
            prestate_diff,
            compact.observed_storage,
        )
        if not compact.observed_storage_complete and compact.writes:
            logger.warning(
                "Compact trace returned incomplete transaction-start storage "
                "observations"
            )
        return TransactionTraceEvidence(
            receipt=receipt,
            prestate_diff=prestate_diff,
            writes=compact.writes,
            sha3_operations=compact.sha3_operations,
            evm_step_count=compact.evm_step_count,
            degraded_reason=compact.degraded_reason,
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
    def _merge_observed_prestate(
        cls,
        diff: dict,
        observed_storage: dict[str, dict[str, str | None]],
    ) -> None:
        pre = diff.setdefault("pre", {})
        post = diff.setdefault("post", {})

        for raw_address, storage in observed_storage.items():
            address = raw_address.lower()
            known_storage = {
                raw_slot: raw_initial
                for raw_slot, raw_initial in storage.items()
                if raw_initial is not None
            }
            if not known_storage:
                continue
            pre_storage = pre.setdefault(address, {}).setdefault("storage", {})
            post_storage = post.setdefault(address, {}).setdefault("storage", {})
            for raw_slot, raw_initial in known_storage.items():
                slot = cls._word(raw_slot)
                initial = cls._word(raw_initial)
                absent_from_diff = slot not in pre_storage and slot not in post_storage
                pre_storage.setdefault(slot, initial)
                if absent_from_diff:
                    post_storage[slot] = initial
