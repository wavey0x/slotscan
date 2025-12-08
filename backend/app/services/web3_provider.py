"""Web3 provider management."""

from typing import Optional

from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware

from app.config import Settings


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
            # Add POA middleware for chains that need it
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
