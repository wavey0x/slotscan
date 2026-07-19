"""Transaction-level RPC evidence extraction, independent of decoding/layouts."""

from dataclasses import dataclass
import logging

from app.models.errors import RPCError
from app.services.tracer.rpc_client import TRACE_METHOD, TraceRPCClient


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
        # The receipt is independent network I/O, so overlap it with the one
        # native replay while keeping all trace evidence in that single replay.
        import asyncio

        native, receipt = await asyncio.gather(
            self.rpc_client.execute_slotscan_trace(chain_id, tx_hash),
            self.rpc_client.get_receipt(chain_id, tx_hash),
        )
        self._validate_receipt_identity(native, receipt)
        prestate_diff = native.prestate_diff
        self._normalize_diff(prestate_diff)
        self._merge_observed_prestate(
            prestate_diff,
            native.observed_storage,
        )
        if not native.observed_storage_complete and native.writes:
            logger.warning(
                "Native trace returned incomplete transaction-start storage "
                "observations"
            )
        return TransactionTraceEvidence(
            receipt=receipt,
            prestate_diff=prestate_diff,
            writes=native.writes,
            sha3_operations=native.sha3_operations,
            evm_step_count=native.evm_step_count,
            degraded_reason=native.degraded_reason,
        )

    @classmethod
    def _validate_receipt_identity(cls, native, receipt: dict) -> None:
        try:
            receipt_block_hash = cls._hash(receipt["blockHash"])
            receipt_index = cls._quantity(receipt["transactionIndex"])
            receipt_status = cls._quantity(receipt["status"]) == 1
        except (KeyError, TypeError, ValueError):
            raise RPCError(TRACE_METHOD, "receipt identity is malformed") from None
        if (
            receipt_block_hash != native.block_hash
            or receipt_index != native.transaction_index
            or receipt_status != native.root_succeeded
        ):
            raise RPCError(TRACE_METHOD, "receipt identity does not match trace")

    @staticmethod
    def _hash(value) -> str:
        if isinstance(value, bytes):
            value = "0x" + value.hex()
        elif not isinstance(value, str) and hasattr(value, "hex"):
            value = value.hex()
        if (
            not isinstance(value, str)
            or len(value) != 66
            or not value.startswith("0x")
        ):
            raise ValueError("invalid hash")
        bytes.fromhex(value[2:])
        return value.lower()

    @staticmethod
    def _quantity(value) -> int:
        if isinstance(value, bool):
            raise ValueError("invalid quantity")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value, 16)
        raise TypeError("invalid quantity")

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
