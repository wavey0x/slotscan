"""Web3 provider management."""

import asyncio
from dataclasses import dataclass
import logging
import re
from typing import Any

from web3 import AsyncWeb3, AsyncHTTPProvider, Web3
from web3.middleware import ExtraDataToPOAMiddleware

from app.config import Settings
from app.models.errors import RPCError

logger = logging.getLogger(__name__)

RETH_STORAGE_VALUES_LIMIT = 1024
STORAGE_BLOCK_TAGS = frozenset(
    {"earliest", "finalized", "latest", "pending", "safe"}
)


def _storage_block_parameter(block: int | str | dict[str, Any]) -> str | dict[str, Any]:
    """Encode one state selector for a raw JSON-RPC request."""
    if isinstance(block, bool):
        raise ValueError("Block selector must be an integer, tag, or EIP-1898 object")
    if isinstance(block, int):
        if block < 0:
            raise ValueError("Block selector cannot be negative")
        return hex(block)
    if isinstance(block, str):
        if block in STORAGE_BLOCK_TAGS:
            return block
        raise ValueError(f"Invalid block tag: {block}")
    if not isinstance(block, dict):
        raise ValueError("Invalid EIP-1898 block selector")
    if set(block) in ({"blockHash"}, {"blockHash", "requireCanonical"}):
        block_hash = block["blockHash"]
        if (
            not isinstance(block_hash, str)
            or not block_hash.startswith("0x")
            or len(block_hash) != 66
        ):
            raise ValueError("Invalid EIP-1898 block hash")
        try:
            bytes.fromhex(block_hash[2:])
        except ValueError as exc:
            raise ValueError("Invalid EIP-1898 block hash") from exc
        if "requireCanonical" in block and not isinstance(
            block["requireCanonical"],
            bool,
        ):
            raise ValueError("Invalid EIP-1898 canonical requirement")
        return block
    if set(block) == {"blockNumber"}:
        block_number = block["blockNumber"]
        if not isinstance(block_number, str) or not re.fullmatch(
            r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)",
            block_number,
        ):
            raise ValueError("Invalid EIP-1898 block number")
        return block
    raise ValueError("Invalid EIP-1898 block selector")


def _storage_slots(slots: list[int]) -> list[int]:
    """Validate and first-seen deduplicate native storage slots."""
    unique: list[int] = []
    seen: set[int] = set()
    for slot in slots:
        if isinstance(slot, bool) or not isinstance(slot, int):
            raise ValueError("Storage slots must be integers")
        if slot < 0 or slot >= 2**256:
            raise ValueError("Storage slot is outside the uint256 range")
        if slot not in seen:
            unique.append(slot)
            seen.add(slot)
    return unique


def _decode_storage_values_response(
    response: object,
    address: str,
    expected_count: int,
) -> list[str]:
    """Decode Reth's single-address eth_getStorageValues response strictly."""
    if not isinstance(response, dict):
        raise RPCError("eth_getStorageValues", "Invalid JSON-RPC response envelope")
    if "error" in response:
        error = response["error"]
        code = error.get("code") if isinstance(error, dict) else None
        detail = f"RPC returned error code {code}" if code is not None else "RPC error"
        raise RPCError("eth_getStorageValues", detail)
    result = response.get("result")
    if not isinstance(result, dict):
        raise RPCError("eth_getStorageValues", "Result must be an object")
    matching = [
        value
        for key, value in result.items()
        if isinstance(key, str) and key.lower() == address.lower()
    ]
    if len(result) != 1 or len(matching) != 1:
        raise RPCError(
            "eth_getStorageValues",
            "Result did not contain exactly the requested address",
        )
    values = matching[0]
    if not isinstance(values, list) or len(values) != expected_count:
        raise RPCError(
            "eth_getStorageValues",
            "Storage vector cardinality did not match the request",
        )
    decoded: list[str] = []
    for value in values:
        if (
            not isinstance(value, str)
            or not value.startswith("0x")
            or len(value) != 66
        ):
            raise RPCError(
                "eth_getStorageValues",
                "Storage vector contained an invalid word",
            )
        try:
            raw = bytes.fromhex(value[2:])
        except ValueError as exc:
            raise RPCError(
                "eth_getStorageValues",
                "Storage vector contained an invalid hexadecimal word",
            ) from exc
        if len(raw) != 32:
            raise RPCError(
                "eth_getStorageValues",
                "Storage vector contained a non-32-byte word",
            )
        decoded.append("0x" + raw.hex())
    return decoded


async def _request_storage_values(
    web3: AsyncWeb3,
    address: str,
    unique_slots: list[int],
    block: int | str | dict[str, Any],
) -> dict[int, str]:
    """Request validated, first-seen unique slots from Reth."""
    checksum_address = Web3.to_checksum_address(address)
    block_parameter = _storage_block_parameter(block)
    results: dict[int, str] = {}
    for start in range(0, len(unique_slots), RETH_STORAGE_VALUES_LIMIT):
        chunk = unique_slots[start : start + RETH_STORAGE_VALUES_LIMIT]
        response = await web3.provider.make_request(
            "eth_getStorageValues",
            [
                {
                    checksum_address: [
                        "0x" + slot.to_bytes(32, byteorder="big").hex()
                        for slot in chunk
                    ]
                },
                block_parameter,
            ],
        )
        values = _decode_storage_values_response(
            response,
            checksum_address,
            len(chunk),
        )
        results.update(zip(chunk, values, strict=True))
    if set(results) != set(unique_slots) or len(results) != len(unique_slots):
        raise RPCError(
            "eth_getStorageValues",
            "Result omitted one or more requested storage slots",
        )
    return results


@dataclass(frozen=True)
class BlockRef:
    """Exact canonical block identity used by one request."""

    chain_id: int
    number: int
    hash: str


@dataclass(frozen=True)
class StorageAttempt:
    """One captured RPC client bound to one exact block hash."""

    web3: AsyncWeb3
    block_ref: BlockRef
    timeout_seconds: int

    @property
    def block_identifier(self) -> dict[str, Any]:
        return {
            "blockHash": self.block_ref.hash,
            "requireCanonical": True,
        }

    def _validate_chain(self, chain_id: int) -> None:
        if chain_id != self.block_ref.chain_id:
            raise ValueError(
                f"Attempt is bound to chain {self.block_ref.chain_id}, not {chain_id}"
            )

    def _validate_block(self, block: int | str) -> None:
        if isinstance(block, int):
            matches = block == self.block_ref.number
        else:
            normalized = block.strip().lower()
            matches = normalized == self.block_ref.hash or normalized == hex(
                self.block_ref.number
            )
            if not matches and normalized.isdigit():
                matches = int(normalized) == self.block_ref.number
        if not matches:
            raise ValueError("Attempt cannot read a different block")

    async def _wait(self, operation: str, awaitable):
        try:
            return await asyncio.wait_for(
                awaitable,
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            raise RuntimeError(
                f"{operation} failed on the configured RPC endpoint: {exc}"
            ) from exc

    async def get_code(self, chain_id: int, address: str, block: int | str):
        self._validate_chain(chain_id)
        self._validate_block(block)
        return await self._wait(
            "eth_getCode",
            self.web3.eth.get_code(
                address,
                block_identifier=self.block_identifier,
            ),
        )

    async def eth_call(
        self,
        chain_id: int,
        transaction: dict,
        block: int | str,
    ):
        self._validate_chain(chain_id)
        self._validate_block(block)
        return await self._wait(
            "eth_call",
            self.web3.eth.call(
                transaction,
                block_identifier=self.block_identifier,
            ),
        )

    async def get_block_number(self, chain_id: int) -> int:
        self._validate_chain(chain_id)
        return self.block_ref.number

    async def get_storage_values(
        self,
        chain_id: int,
        address: str,
        slots: list[int],
        block: int | str,
    ) -> dict[int, str]:
        """Read strict, complete vectors through this attempt's RPC client."""
        self._validate_chain(chain_id)
        self._validate_block(block)
        unique_slots = _storage_slots(slots)
        if not unique_slots:
            return {}
        return await self._wait(
            "eth_getStorageValues",
            _request_storage_values(
                self.web3,
                address,
                unique_slots,
                self.block_identifier,
            ),
        )


class Web3Provider:
    """Manages Web3 instances per chain."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._instances: dict[int, AsyncWeb3] = {}

    def get_web3(self, chain_id: int) -> AsyncWeb3:
        """Get Web3 instance for chain."""
        if chain_id not in self._instances:
            rpc_url = self.settings.rpc_urls.get(chain_id)
            if not rpc_url:
                raise ValueError(f"No RPC URL configured for chain {chain_id}")

            provider = AsyncHTTPProvider(
                rpc_url,
                request_kwargs={"timeout": self.settings.request_timeout_seconds},
            )
            w3 = AsyncWeb3(provider)
            # Addresses are validated before RPC use. Removing ENS resolution also
            # avoids web3.py 7.14's async name middleware treating an EIP-1898
            # block-identifier object as an address-bearing ABI mapping.
            w3.middleware_onion.remove("ens_name_to_address")
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            self._instances[chain_id] = w3

        return self._instances[chain_id]

    async def create_storage_attempt(
        self,
        chain_id: int,
        selector: int | str,
    ) -> StorageAttempt:
        """Capture one client and resolve a selector to an exact block."""
        web3 = self.get_web3(chain_id)
        block_selector: int | str
        if isinstance(selector, int):
            block_selector = selector
        else:
            normalized = selector.strip().lower()
            if normalized in {"latest", "safe", "finalized"}:
                block_selector = normalized
            else:
                try:
                    block_selector = int(normalized, 0)
                except ValueError as exc:
                    raise ValueError(f"Invalid block selector: {selector}") from exc
        if isinstance(block_selector, int) and block_selector < 0:
            raise ValueError("Block selector cannot be negative")
        try:
            block = await asyncio.wait_for(
                web3.eth.get_block(block_selector),
                timeout=self.settings.request_timeout_seconds,
            )
        except Exception as exc:
            raise RuntimeError(
                f"eth_getBlockByNumber failed on the configured RPC endpoint: {exc}"
            ) from exc
        number = block.get("number")
        block_hash = block.get("hash")
        if number is None or block_hash is None:
            raise RuntimeError("RPC returned an incomplete block identity")
        hash_hex = Web3.to_hex(block_hash).lower()
        if len(bytes.fromhex(hash_hex[2:])) != 32:
            raise RuntimeError("RPC returned an invalid block hash")
        return StorageAttempt(
            web3=web3,
            block_ref=BlockRef(
                chain_id=chain_id,
                number=int(number),
                hash=hash_hex,
            ),
            timeout_seconds=self.settings.request_timeout_seconds,
        )

    async def create_exact_storage_attempt(
        self,
        chain_id: int,
        number: int,
        block_hash: str,
    ) -> StorageAttempt:
        """Validate an exact number/hash pair before any state read."""
        attempt = await self.create_storage_attempt(chain_id, number)
        try:
            normalized_hash = Web3.to_hex(hexstr=block_hash).lower()
        except Exception as exc:
            raise ValueError("Invalid block hash") from exc
        if attempt.block_ref.hash != normalized_hash:
            raise ValueError("Block number and hash do not describe the same block")
        return attempt

    async def _call(self, chain_id: int, operation: str, call):
        web3 = self.get_web3(chain_id)
        try:
            return await asyncio.wait_for(
                call(web3),
                timeout=self.settings.request_timeout_seconds,
            )
        except Exception as exc:
            logger.warning("%s failed on RPC endpoint: %s", operation, exc)
            raise RuntimeError(f"{operation} failed on RPC endpoint: {exc}") from exc

    async def make_request(self, chain_id: int, method: str, params: list) -> dict:
        return await self._call(
            chain_id,
            method,
            lambda web3: web3.provider.make_request(method, params),
        )

    async def get_transaction_receipt(self, chain_id: int, tx_hash: str):
        return await self._call(
            chain_id,
            "eth_getTransactionReceipt",
            lambda web3: web3.eth.get_transaction_receipt(tx_hash),
        )

    async def get_code(self, chain_id: int, address: str, block: int | str):
        return await self._call(
            chain_id,
            "eth_getCode",
            lambda web3: web3.eth.get_code(address, block_identifier=block),
        )

    async def get_block_number(self, chain_id: int) -> int:
        return await self._call(
            chain_id,
            "eth_blockNumber",
            lambda web3: web3.eth.get_block_number(),
        )

    async def eth_call(self, chain_id: int, transaction: dict, block: int | str):
        return await self._call(
            chain_id,
            "eth_call",
            lambda web3: web3.eth.call(transaction, block_identifier=block),
        )

    async def close(self) -> None:
        """Close every RPC session created by this process."""
        for web3 in self._instances.values():
            await web3.provider.disconnect()
        self._instances.clear()

    async def get_storage_values(
        self,
        chain_id: int,
        address: str,
        slots: list[int],
        block: int | str | dict[str, Any],
    ) -> dict[int, str]:
        unique_slots = _storage_slots(slots)
        if not unique_slots:
            return {}
        return await self._call(
            chain_id,
            "eth_getStorageValues",
            lambda web3: _request_storage_values(
                web3,
                address,
                unique_slots,
                block,
            ),
        )
