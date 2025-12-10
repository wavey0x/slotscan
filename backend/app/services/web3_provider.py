"""Web3 provider management."""

import logging
from typing import Optional

from web3 import AsyncWeb3, AsyncHTTPProvider, Web3
from web3.middleware import ExtraDataToPOAMiddleware

from app.config import Settings

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

            provider = AsyncHTTPProvider(rpc_url, request_kwargs={"timeout": 90})
            w3 = AsyncWeb3(provider)
            # Add POA middleware for chains that need it (web3.py v7+)
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            self._instances[chain_id] = w3

        return self._instances[chain_id]

    def get_backup_web3(self, chain_id: int) -> Optional[AsyncWeb3]:
        """Get backup Web3 instance for chain."""
        backup_url = self.settings.rpc_backup_urls.get(chain_id)
        if not backup_url:
            return None

        if chain_id not in self._backup_instances:
            provider = AsyncHTTPProvider(backup_url, request_kwargs={"timeout": 90})
            w3 = AsyncWeb3(provider)
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            self._backup_instances[chain_id] = w3

        return self._backup_instances[chain_id]

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

        web3 = self.get_web3(chain_id)
        address = Web3.to_checksum_address(address)

        results = {}

        # Process in batches (RPC providers often limit batch size to 100-1000)
        for i in range(0, len(slots), batch_size):
            batch_slots = slots[i : i + batch_size]

            # Use web3.py's built-in batch API
            batch = web3.batch_requests()

            for slot in batch_slots:
                batch.add(web3.eth.get_storage_at(address, slot, block_identifier=block))

            # Execute batch (single HTTP request for all calls)
            try:
                responses = await batch.async_execute()
            except Exception as e:
                logger.warning(f"Batch RPC failed for slots {i}-{i + len(batch_slots)}: {e}")
                raise

            # Map responses back to slots (responses are in same order as added)
            for slot, response in zip(batch_slots, responses):
                if isinstance(response, bytes):
                    results[slot] = "0x" + response.hex().zfill(64)
                elif isinstance(response, Exception):
                    logger.warning(f"Slot {slot} read failed: {response}")
                    results[slot] = "0x" + "00" * 32
                else:
                    # Handle other response types
                    results[slot] = "0x" + "00" * 32

        logger.debug(
            f"Batch read {len(slots)} slots in {(len(slots) + batch_size - 1) // batch_size} batches"
        )
        return results
