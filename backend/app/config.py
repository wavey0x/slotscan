"""Application configuration loaded from environment variables."""

import os
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://wavey@localhost:5432/storagescan_dev",
        alias="DATABASE_URL"
    )
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")

    # Server
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    debug: bool = Field(default=False, alias="DEBUG")

    # CORS
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        alias="CORS_ORIGINS",
    )

    # RPC - Mainnet only for MVP
    rpc_url_1: str = Field(default="", alias="RPC_URL_1")
    rpc_url_1_backup: str = Field(default="", alias="RPC_URL_1_BACKUP")

    # Etherscan API
    etherscan_api_key_1: str = Field(default="", alias="ETHERSCAN_API_KEY_1")

    # Cache settings
    cache_snapshot_ttl_minutes: int = Field(default=30, alias="CACHE_SNAPSHOT_TTL_MINUTES")
    cache_tx_diff_ttl_minutes: int = Field(default=0, alias="CACHE_TX_DIFF_TTL_MINUTES")

    # Limits
    max_slots_per_contract: int = Field(default=10000, alias="MAX_SLOTS_PER_CONTRACT")
    max_sstore_ops: int = Field(default=10000, alias="MAX_SSTORE_OPS")
    request_timeout_seconds: int = Field(default=45, alias="REQUEST_TIMEOUT_SECONDS")

    model_config = {
        "env_file": "../.env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def rpc_urls(self) -> dict[int, str]:
        """Get RPC URLs by chain ID."""
        urls = {}
        if self.rpc_url_1:
            urls[1] = self.rpc_url_1
        return urls

    @property
    def rpc_backup_urls(self) -> dict[int, str]:
        """Get backup RPC URLs by chain ID."""
        urls = {}
        if self.rpc_url_1_backup:
            urls[1] = self.rpc_url_1_backup
        return urls

    @property
    def etherscan_keys(self) -> dict[int, str]:
        """Get Etherscan API keys by chain ID."""
        keys = {}
        if self.etherscan_api_key_1:
            keys[1] = self.etherscan_api_key_1
        return keys

    @property
    def etherscan_urls(self) -> dict[int, str]:
        """Get Etherscan API URLs by chain ID."""
        return {
            1: "https://api.etherscan.io/api",
        }


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
