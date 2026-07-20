"""RPC client for the native SlotScan transaction trace."""

from dataclasses import dataclass
import logging
import re
from typing import Any

from web3 import Web3

from app.config import Settings
from app.models.errors import RPCError, TraceNotAvailableError, TransactionNotFoundError
from app.services.web3_provider import Web3Provider


logger = logging.getLogger(__name__)

TRACE_METHOD = "slotscan_traceTransaction"
TRACE_CAPABILITY_PROBE_HASH = "0x" + "00" * 32
_TRACE_FIELDS = {
    "transactionHash",
    "blockHash",
    "transactionIndex",
    "rootSucceeded",
    "prestateDiff",
    "writes",
    "sha3Operations",
    "observedStorage",
    "observedStorageComplete",
    "stepCount",
    "degradedReason",
}
_WRITE_FIELDS = {
    "address",
    "codeAddress",
    "codeAttribution",
    "codeSource",
    "codeDesignator",
    "pc",
    "slot",
    "oldValue",
    "value",
    "opcode",
    "namespace",
    "depth",
    "index",
    "frameId",
    "frameParentId",
    "frameFailed",
    "frameReverted",
    "rollbackFrameId",
    "rollbackParentId",
}
_SHA3_FIELDS = {"address", "preimage", "size", "depth"}
_ACCOUNT_FIELDS = {"balance", "code", "nonce", "storage"}


@dataclass(frozen=True)
class SlotScanTraceEvidence:
    transaction_hash: str
    block_hash: str
    transaction_index: int
    root_succeeded: bool
    prestate_diff: dict
    writes: list[dict]
    sha3_operations: list[dict]
    observed_storage: dict[str, dict[str, str | None]]
    observed_storage_complete: bool
    evm_step_count: int
    degraded_reason: str | None = None


class TraceRPCClient:
    """Fetch and validate one native single-replay trace."""

    def __init__(
        self,
        web3_provider: Web3Provider,
        settings: Settings | None = None,
    ):
        self.web3_provider = web3_provider
        self.max_writes = settings.max_sstore_ops if settings else 10_000
        self.max_steps = settings.max_trace_steps if settings else 5_000_000
        self.max_sha3_ops = settings.max_trace_sha3_ops if settings else 20_000
        self.max_preimage_bytes = (
            settings.max_trace_preimage_bytes if settings else 5 * 1024 * 1024
        )
        self.max_prestate_accounts = (
            settings.max_prestate_accounts if settings else 10_000
        )
        self.max_prestate_storage_entries = (
            settings.max_prestate_storage_entries if settings else 100_000
        )
        self.max_observed_storage = self.max_prestate_storage_entries

    async def get_receipt(self, chain_id: int, tx_hash: str) -> dict:
        """Fetch a receipt without exposing provider details in public errors."""
        try:
            receipt = await self.web3_provider.get_transaction_receipt(chain_id, tx_hash)
        except Exception as exc:
            lowered = str(exc).lower()
            if "not found" in lowered or "transaction receipt" in lowered:
                raise TransactionNotFoundError(tx_hash) from None
            logger.info(
                "Receipt RPC failed for %s (%s)",
                tx_hash,
                type(exc).__name__,
            )
            raise RPCError("eth_getTransactionReceipt", "upstream request failed") from None

        if receipt is None:
            raise TransactionNotFoundError(tx_hash)
        return receipt

    async def check_support(self, chain_id: int) -> None:
        """Require the native method without replaying a real transaction."""
        try:
            await self.execute_slotscan_trace(
                chain_id,
                TRACE_CAPABILITY_PROBE_HASH,
            )
        except TransactionNotFoundError:
            return

    async def execute_slotscan_trace(
        self,
        chain_id: int,
        tx_hash: str,
    ) -> SlotScanTraceEvidence:
        """Execute the native one-replay trace and validate its full envelope."""
        requested_hash = self._strict_hash(tx_hash, "transaction hash")
        limits = {
            "maxSteps": self.max_steps,
            "maxWrites": self.max_writes,
            "maxSha3Operations": self.max_sha3_ops,
            "maxPreimageBytes": self.max_preimage_bytes,
            "maxObservedStorage": self.max_observed_storage,
        }
        try:
            response = await self.web3_provider.make_request(
                chain_id,
                TRACE_METHOD,
                [requested_hash, limits],
            )
        except Exception as exc:
            lowered = str(exc).lower()
            if "method not found" in lowered or "not supported" in lowered:
                raise TraceNotAvailableError(
                    "Node does not support slotscan_traceTransaction"
                ) from None
            logger.info(
                "Native trace RPC failed for %s (%s)",
                tx_hash,
                type(exc).__name__,
            )
            raise RPCError(TRACE_METHOD, "upstream request failed") from None

        if not isinstance(response, dict):
            raise RPCError(TRACE_METHOD, "invalid JSON-RPC response envelope")
        if "error" in response:
            self._raise_trace_rpc_error(response["error"], requested_hash)
        if (
            "result" not in response
            or not set(response).issubset({"jsonrpc", "id", "result"})
            or ("jsonrpc" in response and response["jsonrpc"] != "2.0")
        ):
            raise RPCError(TRACE_METHOD, "invalid JSON-RPC response envelope")
        try:
            return self._decode_slotscan_trace_result(
                response["result"],
                requested_hash,
            )
        except TraceNotAvailableError:
            raise
        except (TypeError, ValueError) as exc:
            logger.info("Native trace returned malformed evidence: %s", exc)
            raise RPCError(TRACE_METHOD, "invalid trace response") from None

    def _raise_trace_rpc_error(self, error: Any, tx_hash: str) -> None:
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message", "") if isinstance(error, dict) else str(error)
        lowered = message.lower() if isinstance(message, str) else ""
        if code == -32601 or "method not found" in lowered or "not supported" in lowered:
            raise TraceNotAvailableError(
                "Node does not support slotscan_traceTransaction"
            )
        if code == -32000 and lowered == "transaction not found":
            raise TransactionNotFoundError(tx_hash)
        logger.info("Native trace RPC returned error code %r", code)
        raise RPCError(TRACE_METHOD, "upstream request failed")

    def _decode_slotscan_trace_result(
        self,
        result: Any,
        requested_hash: str,
    ) -> SlotScanTraceEvidence:
        if not isinstance(result, dict) or set(result) != _TRACE_FIELDS:
            raise ValueError("invalid native trace envelope")

        transaction_hash = self._strict_hash(
            result["transactionHash"],
            "transactionHash",
        )
        if transaction_hash != requested_hash:
            raise ValueError("trace transaction hash does not match the request")
        block_hash = self._strict_hash(result["blockHash"], "blockHash")
        transaction_index = self._strict_int(
            result["transactionIndex"],
            "transactionIndex",
        )
        root_succeeded = result["rootSucceeded"]
        if not isinstance(root_succeeded, bool):
            raise ValueError("rootSucceeded must be a boolean")

        prestate_diff = self._validate_prestate_diff(result["prestateDiff"])
        step_count = self._strict_int(result["stepCount"], "stepCount")
        degraded_reason = result["degradedReason"]
        if degraded_reason not in {None, "trace_limit"}:
            raise ValueError("invalid degradation reason")

        writes_value = result["writes"]
        sha3_value = result["sha3Operations"]
        if not isinstance(writes_value, list) or not isinstance(sha3_value, list):
            raise ValueError("trace evidence collections must be arrays")
        writes = self._validate_writes(writes_value, step_count)
        sha3_operations = self._validate_sha3_operations(sha3_value)
        observed_storage = self._validate_observed_storage(result["observedStorage"])
        observed_storage_complete = result["observedStorageComplete"]
        if not isinstance(observed_storage_complete, bool):
            raise ValueError("observedStorageComplete must be a boolean")

        if degraded_reason == "trace_limit":
            if writes or sha3_operations or observed_storage or observed_storage_complete:
                raise ValueError("degraded trace contains partial evidence")
        elif step_count > self.max_steps:
            raise TraceNotAvailableError("Trace exceeds the configured step limit")

        persistent_keys = {
            (write["address"], write["slot"])
            for write in writes
            if write["namespace"] == "persistent"
        }
        observed_keys = {
            (address, slot)
            for address, storage in observed_storage.items()
            for slot in storage
        }
        if observed_storage_complete:
            if any(
                value is None
                for storage in observed_storage.values()
                for value in storage.values()
            ):
                raise ValueError("complete observed storage contains null values")
            if not persistent_keys.issubset(observed_keys):
                raise ValueError(
                    "complete observed storage omitted a persistent write key"
                )

        return SlotScanTraceEvidence(
            transaction_hash=transaction_hash,
            block_hash=block_hash,
            transaction_index=transaction_index,
            root_succeeded=root_succeeded,
            prestate_diff=prestate_diff,
            writes=writes,
            sha3_operations=sha3_operations,
            observed_storage=observed_storage,
            observed_storage_complete=observed_storage_complete,
            evm_step_count=0 if degraded_reason else step_count,
            degraded_reason=degraded_reason,
        )

    def _validate_prestate_diff(self, value: Any) -> dict:
        if not isinstance(value, dict) or set(value) != {"pre", "post"}:
            raise ValueError("prestateDiff must contain pre and post objects")

        normalized = {"pre": {}, "post": {}}
        account_count = 0
        storage_count = 0
        for side in ("pre", "post"):
            accounts = value[side]
            if not isinstance(accounts, dict):
                raise ValueError(f"prestateDiff.{side} must be an object")
            for raw_address, raw_state in accounts.items():
                account_count += 1
                if account_count > self.max_prestate_accounts:
                    raise TraceNotAvailableError(
                        "Prestate trace exceeds the configured account limit"
                    )
                address = self._strict_address(
                    raw_address,
                    f"prestateDiff.{side}.address",
                )
                if address in normalized[side]:
                    raise ValueError("duplicate prestate account")
                if not isinstance(raw_state, dict) or not set(raw_state).issubset(
                    _ACCOUNT_FIELDS
                ):
                    raise ValueError("invalid prestate account")

                state = dict(raw_state)
                storage = state.get("storage", {})
                if not isinstance(storage, dict):
                    raise ValueError("prestate storage must be an object")
                normalized_storage = {}
                for raw_slot, raw_word in storage.items():
                    storage_count += 1
                    if storage_count > self.max_prestate_storage_entries:
                        raise TraceNotAvailableError(
                            "Prestate trace exceeds the configured storage limit"
                        )
                    slot = self._strict_word(
                        raw_slot,
                        "prestateDiff.storage.slot",
                    )
                    if slot in normalized_storage:
                        raise ValueError("duplicate prestate storage slot")
                    normalized_storage[slot] = self._strict_word(
                        raw_word,
                        "prestateDiff.storage.value",
                    )
                if "storage" in state:
                    state["storage"] = normalized_storage
                self._validate_account_scalars(state)
                normalized[side][address] = state
        return normalized

    def _validate_account_scalars(self, state: dict) -> None:
        balance = state.get("balance")
        if balance is not None:
            state["balance"] = self._strict_quantity(balance, "prestate balance")
        nonce = state.get("nonce")
        if nonce is not None:
            if isinstance(nonce, int):
                state["nonce"] = self._strict_int(nonce, "prestate nonce")
            else:
                state["nonce"] = self._strict_quantity(nonce, "prestate nonce")
        code = state.get("code")
        if code is not None:
            if not isinstance(code, str) or not re.fullmatch(
                r"0x(?:[0-9a-fA-F]{2})*",
                code,
            ):
                raise ValueError("prestate code must be hex bytes")
            state["code"] = code.lower()

    def _validate_writes(self, values: list[Any], step_count: int) -> list[dict]:
        if len(values) > self.max_writes:
            raise TraceNotAvailableError("Trace exceeds the configured write limit")

        writes = []
        previous_index = -1
        for raw in values:
            if not isinstance(raw, dict) or set(raw) != _WRITE_FIELDS:
                raise ValueError("invalid write evidence")
            index = self._strict_int(raw["index"], "write.index")
            if index <= previous_index or index >= step_count:
                raise ValueError("write index is outside execution order")
            previous_index = index
            opcode = raw["opcode"]
            namespace = raw["namespace"]
            if (opcode, namespace) not in {
                ("SSTORE", "persistent"),
                ("TSTORE", "transient"),
            }:
                raise ValueError("invalid storage-write opcode/namespace")

            attribution = raw["codeAttribution"]
            source = raw["codeSource"]
            code_address = raw["codeAddress"]
            designator = raw["codeDesignator"]
            if attribution == "exact":
                code_address = self._strict_address(
                    code_address,
                    "write.codeAddress",
                )
                if source == "direct":
                    if designator is not None:
                        raise ValueError("direct code attribution has a designator")
                elif source == "eip7702":
                    if (
                        not isinstance(designator, str)
                        or not re.fullmatch(
                            r"0x[eE][fF]0100[0-9a-fA-F]{40}",
                            designator,
                        )
                    ):
                        raise ValueError("invalid EIP-7702 designator")
                    designator = designator.lower()
                    if code_address != "0x" + designator[8:]:
                        raise ValueError("EIP-7702 designator target mismatch")
                else:
                    raise ValueError("invalid exact code source")
            elif attribution == "unknown":
                if code_address is not None or source != "unknown" or designator is not None:
                    raise ValueError("invalid unknown code attribution")
            else:
                raise ValueError("invalid code attribution")

            frame_parent_id = self._optional_int(
                raw["frameParentId"],
                "write.frameParentId",
            )
            rollback_frame_id = self._optional_int(
                raw["rollbackFrameId"],
                "write.rollbackFrameId",
            )
            rollback_parent_id = self._optional_int(
                raw["rollbackParentId"],
                "write.rollbackParentId",
            )
            frame_failed = raw["frameFailed"]
            frame_reverted = raw["frameReverted"]
            if not isinstance(frame_failed, bool) or not isinstance(frame_reverted, bool):
                raise ValueError("write rollback markers must be booleans")
            if frame_failed and not frame_reverted:
                raise ValueError("failed frame write is not marked reverted")
            if frame_reverted != (rollback_frame_id is not None):
                raise ValueError("write rollback frame marker is inconsistent")
            if rollback_parent_id is not None and rollback_frame_id is None:
                raise ValueError("write rollback parent has no rollback frame")

            old_value = raw["oldValue"]
            if old_value is not None:
                old_value = self._strict_word(old_value, "write.oldValue")
            writes.append(
                {
                    "address": self._strict_address(raw["address"], "write.address"),
                    "code_address": code_address,
                    "code_attribution": attribution,
                    "code_source": source,
                    "code_designator": designator,
                    "pc": self._strict_int(raw["pc"], "write.pc"),
                    "slot": self._strict_word(raw["slot"], "write.slot"),
                    "old_value": old_value,
                    "value": self._strict_word(raw["value"], "write.value"),
                    "opcode": opcode,
                    "namespace": namespace,
                    "depth": self._strict_int(raw["depth"], "write.depth"),
                    "index": index,
                    "frame_id": self._strict_int(raw["frameId"], "write.frameId"),
                    "frame_parent_id": frame_parent_id,
                    "frame_failed": frame_failed,
                    "frame_reverted": frame_reverted,
                    "rollback_frame_id": rollback_frame_id,
                    "rollback_parent_id": rollback_parent_id,
                }
            )
        return writes

    def _validate_sha3_operations(self, values: list[Any]) -> list[dict]:
        if len(values) > self.max_sha3_ops:
            raise TraceNotAvailableError("Trace exceeds the configured SHA3 limit")
        operations = []
        preimage_bytes = 0
        for raw in values:
            if not isinstance(raw, dict) or set(raw) != _SHA3_FIELDS:
                raise ValueError("invalid SHA3 evidence")
            size = self._strict_int(raw["size"], "sha3.size")
            if not 32 <= size <= 256:
                raise ValueError("SHA3 evidence size is outside capture range")
            preimage = raw["preimage"]
            if (
                not isinstance(preimage, str)
                or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})+", preimage)
                or (len(preimage) - 2) // 2 != size
            ):
                raise ValueError("invalid SHA3 preimage")
            preimage = preimage.lower()
            preimage_bytes += size
            if preimage_bytes > self.max_preimage_bytes:
                raise TraceNotAvailableError(
                    "Trace exceeds the configured preimage limit"
                )
            operations.append(
                {
                    "address": self._strict_address(raw["address"], "sha3.address"),
                    "preimage": preimage,
                    "hash": Web3.keccak(bytes.fromhex(preimage[2:])).hex(),
                    "size": size,
                    "depth": self._strict_int(raw["depth"], "sha3.depth"),
                }
            )
        return operations

    def _validate_observed_storage(
        self,
        value: Any,
    ) -> dict[str, dict[str, str | None]]:
        if not isinstance(value, dict):
            raise ValueError("observedStorage must be an object")
        observed = {}
        count = 0
        for raw_address, raw_storage in value.items():
            if len(observed) >= self.max_prestate_accounts:
                raise TraceNotAvailableError(
                    "Trace exceeds the configured observed-account limit"
                )
            address = self._strict_address(
                raw_address,
                "observedStorage.address",
            )
            if address in observed:
                raise ValueError("duplicate observed-storage address")
            if not isinstance(raw_storage, dict) or not raw_storage:
                raise ValueError("observed account storage must be a nonempty object")
            storage = {}
            for raw_slot, raw_value in raw_storage.items():
                count += 1
                if count > self.max_observed_storage:
                    raise TraceNotAvailableError(
                        "Trace exceeds the configured observation limit"
                    )
                slot = self._strict_word(raw_slot, "observedStorage.slot")
                if slot in storage:
                    raise ValueError("duplicate observed-storage slot")
                storage[slot] = (
                    None
                    if raw_value is None
                    else self._strict_word(raw_value, "observedStorage.value")
                )
            observed[address] = storage
        return observed

    @staticmethod
    def _strict_int(value: Any, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} must be a nonnegative integer")
        return value

    @classmethod
    def _optional_int(cls, value: Any, field: str) -> int | None:
        return None if value is None else cls._strict_int(value, field)

    @staticmethod
    def _strict_address(value: Any, field: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"0x[0-9a-fA-F]{40}",
            value,
        ):
            raise ValueError(f"{field} must be exactly 20 bytes")
        return value.lower()

    @staticmethod
    def _strict_hash(value: Any, field: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"0x[0-9a-fA-F]{64}",
            value,
        ):
            raise ValueError(f"{field} must be exactly 32 bytes")
        return value.lower()

    @staticmethod
    def _strict_word(value: Any, field: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"0x[0-9a-fA-F]{64}",
            value,
        ):
            raise ValueError(f"{field} must be exactly 32 bytes")
        return value.lower()

    @staticmethod
    def _strict_quantity(value: Any, field: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)",
            value,
        ):
            raise ValueError(f"{field} must be a canonical quantity")
        return value.lower()
