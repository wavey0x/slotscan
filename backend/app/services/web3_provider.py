"""Web3 provider management."""

import asyncio
import logging
from typing import Optional

from web3 import AsyncWeb3, AsyncHTTPProvider, Web3

# web3.py v7 renamed geth_poa_middleware to ExtraDataToPOAMiddleware
# For async, v6 uses async_geth_poa_middleware, v7 uses ExtraDataToPOAMiddleware
try:
    from web3.middleware import ExtraDataToPOAMiddleware as POAMiddleware
except ImportError:
    from web3.middleware import async_geth_poa_middleware as POAMiddleware

from app.config import Settings
from app.models.errors import RPCError

logger = logging.getLogger(__name__)


class Web3Provider:
    """Manages Web3 instances per chain."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._instances: dict[int, AsyncWeb3] = {}
        self._backup_instances: dict[int, AsyncWeb3] = {}

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
            # Add POA middleware for chains that need it (web3.py v7+)
            w3.middleware_onion.inject(POAMiddleware, layer=0)
            self._instances[chain_id] = w3

        return self._instances[chain_id]

    def get_backup_web3(self, chain_id: int) -> Optional[AsyncWeb3]:
        """Get backup Web3 instance for chain."""
        backup_url = self.settings.rpc_backup_urls.get(chain_id)
        if not backup_url:
            return None

        if chain_id not in self._backup_instances:
            provider = AsyncHTTPProvider(
                backup_url,
                request_kwargs={"timeout": self.settings.request_timeout_seconds},
            )
            w3 = AsyncWeb3(provider)
            w3.middleware_onion.inject(POAMiddleware, layer=0)
            self._backup_instances[chain_id] = w3

        return self._backup_instances[chain_id]

    def _providers(self, chain_id: int) -> list[AsyncWeb3]:
        providers = [self.get_web3(chain_id)]
        backup = self.get_backup_web3(chain_id)
        if backup is not None:
            providers.append(backup)
        return providers

    async def _with_failover(self, chain_id: int, operation: str, call):
        errors = []
        for web3 in self._providers(chain_id):
            try:
                return await asyncio.wait_for(
                    call(web3),
                    timeout=self.settings.request_timeout_seconds,
                )
            except Exception as exc:
                errors.append(str(exc))
                logger.warning("%s failed on RPC provider: %s", operation, exc)
        raise RuntimeError(f"{operation} failed on all RPC providers: {'; '.join(errors)}")

    async def make_request(self, chain_id: int, method: str, params: list) -> dict:
        last_error_response = None
        transport_errors = []
        for web3 in self._providers(chain_id):
            try:
                result = await asyncio.wait_for(
                    web3.provider.make_request(method, params),
                    timeout=self.settings.request_timeout_seconds,
                )
            except Exception as exc:
                transport_errors.append(str(exc))
                logger.warning("%s failed on RPC provider: %s", method, exc)
                continue
            if "error" not in result:
                return result
            last_error_response = result
            logger.warning("%s returned an RPC error; trying backup provider", method)
        if last_error_response is not None:
            return last_error_response
        raise RuntimeError(
            f"{method} failed on all RPC providers: {'; '.join(transport_errors)}"
        )

    async def get_transaction_receipt(self, chain_id: int, tx_hash: str):
        return await self._with_failover(
            chain_id,
            "eth_getTransactionReceipt",
            lambda web3: web3.eth.get_transaction_receipt(tx_hash),
        )

    async def get_code(self, chain_id: int, address: str, block: int | str):
        return await self._with_failover(
            chain_id,
            "eth_getCode",
            lambda web3: web3.eth.get_code(address, block_identifier=block),
        )

    async def get_storage_at(
        self, chain_id: int, address: str, slot: int | str, block: int | str
    ):
        return await self._with_failover(
            chain_id,
            "eth_getStorageAt",
            lambda web3: web3.eth.get_storage_at(address, slot, block_identifier=block),
        )

    async def get_block_number(self, chain_id: int) -> int:
        return await self._with_failover(
            chain_id,
            "eth_blockNumber",
            lambda web3: web3.eth.get_block_number(),
        )

    async def eth_call(self, chain_id: int, transaction: dict, block: int | str):
        return await self._with_failover(
            chain_id,
            "eth_call",
            lambda web3: web3.eth.call(transaction, block_identifier=block),
        )

    async def close(self) -> None:
        """Close every provider session created by this process."""
        for web3 in [*self._instances.values(), *self._backup_instances.values()]:
            disconnect = getattr(web3.provider, "disconnect", None)
            if disconnect:
                result = disconnect()
                if hasattr(result, "__await__"):
                    await result
        self._instances.clear()
        self._backup_instances.clear()

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
            batch_size: Max calls per batch (RPC providers often limit this)

        Returns:
            Dict mapping slot number to hex value string
        """
        if not slots:
            return {}

        address = Web3.to_checksum_address(address)

        results = {}

        # Process in batches (RPC providers often limit batch size to 100-1000)
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

            responses = await self._with_failover(
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
