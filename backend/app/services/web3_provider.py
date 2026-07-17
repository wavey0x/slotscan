"""Web3 provider management."""

import asyncio
import logging

from web3 import AsyncWeb3, AsyncHTTPProvider, Web3
from web3.middleware import ExtraDataToPOAMiddleware

from app.config import Settings
from app.models.errors import RPCError

logger = logging.getLogger(__name__)


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
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            self._instances[chain_id] = w3

        return self._instances[chain_id]

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
                for slot, response in zip(batch_slots, batch_responses):
                    if isinstance(response, Exception):
                        raise RuntimeError(f"Slot {slot}: {response}")
                    if not isinstance(response, bytes):
                        raise RuntimeError(
                            f"Slot {slot}: unexpected response type "
                            f"{type(response).__name__}"
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
                    results[slot] = "0x" + response.hex().zfill(64)
                else:  # validated inside execute_batch
                    raise RPCError("eth_getStorageAt", f"Slot {slot}: invalid response")

        logger.debug(
            f"Batch read {len(slots)} slots in {(len(slots) + batch_size - 1) // batch_size} batches"
        )
        return results
