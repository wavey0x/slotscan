"""Web3 provider management."""

import asyncio
from dataclasses import dataclass
import logging
from typing import Any

from web3 import AsyncWeb3, AsyncHTTPProvider, Web3
from web3.middleware import ExtraDataToPOAMiddleware

from app.config import Settings
from app.models.errors import RPCError

logger = logging.getLogger(__name__)


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

    async def get_storage_at(
        self,
        chain_id: int,
        address: str,
        slot: int | str,
        block: int | str,
    ):
        self._validate_chain(chain_id)
        self._validate_block(block)
        return await self._wait(
            "eth_getStorageAt",
            self.web3.eth.get_storage_at(
                address,
                slot,
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

    async def batch_get_storage_at(
        self,
        chain_id: int,
        address: str,
        slots: list[int],
        block: int | str,
        batch_size: int = 100,
    ) -> dict[int, str]:
        """Read strict, complete batches through this attempt's RPC client."""
        self._validate_chain(chain_id)
        self._validate_block(block)
        if not slots:
            return {}
        address = Web3.to_checksum_address(address)
        results: dict[int, str] = {}

        for start in range(0, len(slots), batch_size):
            batch_slots = slots[start : start + batch_size]
            batch = self.web3.batch_requests()
            for slot in batch_slots:
                batch.add(
                    self.web3.eth.get_storage_at(
                        address,
                        slot,
                        block_identifier=self.block_identifier,
                    )
                )
            responses = await self._wait(
                "eth_getStorageAt batch",
                batch.async_execute(),
            )
            if len(responses) != len(batch_slots):
                raise RuntimeError(
                    "Batch response cardinality did not match the request"
                )
            for slot, response in zip(batch_slots, responses, strict=True):
                if isinstance(response, Exception):
                    raise RuntimeError(f"Slot {slot}: {response}")
                if not isinstance(response, bytes) or len(response) != 32:
                    length = len(response) if isinstance(response, bytes) else "unknown"
                    raise RuntimeError(
                        f"Slot {slot}: expected 32 bytes, received {length}"
                    )
                results[slot] = "0x" + response.hex()

        if len(results) != len(slots):
            raise RuntimeError("Batch response omitted one or more requested slots")
        return results


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

    async def get_storage_at(
        self, chain_id: int, address: str, slot: int | str, block: int | str
    ):
        return await self._call(
            chain_id,
            "eth_getStorageAt",
            lambda web3: web3.eth.get_storage_at(address, slot, block_identifier=block),
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

    async def batch_get_storage_at(
        self,
        chain_id: int,
        address: str,
        slots: list[int],
        block: int | str,
        batch_size: int = 100,
    ) -> dict[int, str]:
        """
        Batch multiple eth_getStorageAt calls into single HTTP requests.

        Uses JSON-RPC batching to reduce HTTP overhead significantly.
        100 slots = 1 HTTP request instead of 100.

        Args:
            chain_id: Chain ID
            address: Contract address
            slots: List of slot numbers to read
            block: Block number or 'latest'
            batch_size: Max calls per batch (RPC endpoints often limit this)

        Returns:
            Dict mapping slot number to hex value string
        """
        if not slots:
            return {}

        address = Web3.to_checksum_address(address)

        results = {}

        # Process in batches (RPC endpoints often limit batch size to 100-1000)
        for i in range(0, len(slots), batch_size):
            batch_slots = slots[i : i + batch_size]

            async def execute_batch(web3):
                batch = web3.batch_requests()
                for slot in batch_slots:
                    batch.add(
                        web3.eth.get_storage_at(address, slot, block_identifier=block)
                    )
                batch_responses = await batch.async_execute()
                if len(batch_responses) != len(batch_slots):
                    raise RuntimeError(
                        "Batch response cardinality did not match the request"
                    )
                for slot, response in zip(batch_slots, batch_responses):
                    if isinstance(response, Exception):
                        raise RuntimeError(f"Slot {slot}: {response}")
                    if not isinstance(response, bytes):
                        raise RuntimeError(
                            f"Slot {slot}: unexpected response type "
                            f"{type(response).__name__}"
                        )
                    if len(response) != 32:
                        raise RuntimeError(
                            f"Slot {slot}: expected 32 bytes, received {len(response)}"
                        )
                return batch_responses

            responses = await self._call(
                chain_id,
                f"eth_getStorageAt batch {i}-{i + len(batch_slots)}",
                execute_batch,
            )

            # Map responses back to slots (responses are in same order as added)
            for slot, response in zip(batch_slots, responses):
                if isinstance(response, bytes):
                    results[slot] = "0x" + response.hex()
                else:  # validated inside execute_batch
                    raise RPCError("eth_getStorageAt", f"Slot {slot}: invalid response")

        logger.debug(
            f"Batch read {len(slots)} slots in {(len(slots) + batch_size - 1) // batch_size} batches"
        )
        return results
