"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://wavey@localhost:5432/slotscan_dev",
        alias="DATABASE_URL"
    )
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    transaction_response_cache_bytes: int = Field(
        default=64 * 1024 * 1024,
        alias="TRANSACTION_RESPONSE_CACHE_BYTES",
    )
    terminal_response_cache_ttl_seconds: float = Field(
        default=60,
        alias="TERMINAL_RESPONSE_CACHE_TTL_SECONDS",
    )

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

    # Etherscan API
    etherscan_api_key_1: str = Field(default="", alias="ETHERSCAN_API_KEY_1")

    # Limits
    max_slots_per_contract: int = Field(default=10000, alias="MAX_SLOTS_PER_CONTRACT")
    max_sstore_ops: int = Field(default=10000, alias="MAX_SSTORE_OPS")
    max_trace_steps: int = Field(default=5_000_000, alias="MAX_TRACE_STEPS")
    max_trace_sha3_ops: int = Field(default=20_000, alias="MAX_TRACE_SHA3_OPS")
    max_trace_preimage_bytes: int = Field(
        default=5 * 1024 * 1024,
        alias="MAX_TRACE_PREIMAGE_BYTES",
    )
    max_constant_mapping_candidates: int = Field(
        default=10_000,
        alias="MAX_CONSTANT_MAPPING_CANDIDATES",
    )
    max_prestate_accounts: int = Field(
        default=10_000,
        alias="MAX_PRESTATE_ACCOUNTS",
    )
    max_prestate_storage_entries: int = Field(
        default=100_000,
        alias="MAX_PRESTATE_STORAGE_ENTRIES",
    )
    request_timeout_seconds: int = Field(default=45, alias="REQUEST_TIMEOUT_SECONDS")
    max_parallel_contract_resolutions: int = Field(
        default=8,
        alias="MAX_PARALLEL_CONTRACT_RESOLUTIONS",
    )
    contract_resolution_timeout_seconds: int = Field(
        default=20,
        alias="CONTRACT_RESOLUTION_TIMEOUT_SECONDS",
    )
    transaction_resolution_budget_seconds: int = Field(
        default=90,
        alias="TRANSACTION_RESOLUTION_BUDGET_SECONDS",
    )
    contract_resolution_retry_delay_seconds: float = Field(
        default=0.5,
        alias="CONTRACT_RESOLUTION_RETRY_DELAY_SECONDS",
    )
    contract_resolution_retry_concurrency: int = Field(
        default=2,
        alias="CONTRACT_RESOLUTION_RETRY_CONCURRENCY",
    )
    no_source_cache_ttl_seconds: int = Field(
        default=15 * 60,
        alias="NO_SOURCE_CACHE_TTL_SECONDS",
    )
    max_parallel_verification_requests: int = Field(
        default=4,
        alias="MAX_PARALLEL_VERIFICATION_REQUESTS",
    )
    max_verification_response_bytes: int = Field(
        default=20 * 1024 * 1024,
        alias="MAX_VERIFICATION_RESPONSE_BYTES",
    )
    # Compiler isolation
    allow_compiler_install: bool = Field(default=False, alias="ALLOW_COMPILER_INSTALL")
    max_installed_compilers: int = Field(default=64, alias="MAX_INSTALLED_COMPILERS")
    max_parallel_compilations: int = Field(default=2, alias="MAX_PARALLEL_COMPILATIONS")
    compiler_timeout_seconds: int = Field(default=120, alias="COMPILER_TIMEOUT_SECONDS")
    compiler_memory_limit_mb: int = Field(default=1536, alias="COMPILER_MEMORY_LIMIT_MB")
    max_compilation_input_bytes: int = Field(
        default=5 * 1024 * 1024,
        alias="MAX_COMPILATION_INPUT_BYTES",
    )
    max_compiler_stdout_bytes: int = Field(
        default=50 * 1024 * 1024,
        alias="MAX_COMPILER_STDOUT_BYTES",
    )
    max_compiler_stderr_bytes: int = Field(
        default=1024 * 1024,
        alias="MAX_COMPILER_STDERR_BYTES",
    )
    comparison_max_depth: int = Field(
        default=64,
        alias="COMPARISON_MAX_DEPTH",
    )
    comparison_max_type_visits: int = Field(
        default=4096,
        alias="COMPARISON_MAX_TYPE_VISITS",
    )
    comparison_max_entries: int = Field(
        default=2000,
        alias="COMPARISON_MAX_ENTRIES",
    )
    comparison_max_detail_lines: int = Field(
        default=8,
        alias="COMPARISON_MAX_DETAIL_LINES",
    )
    comparison_max_detail_chars: int = Field(
        default=500,
        alias="COMPARISON_MAX_DETAIL_CHARS",
    )

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
    def etherscan_keys(self) -> dict[int, str]:
        """Get Etherscan API keys by chain ID."""
        keys = {}
        if self.etherscan_api_key_1:
            keys[1] = self.etherscan_api_key_1
        return keys

    @property
    def etherscan_urls(self) -> dict[int, str]:
        """Get Etherscan API V2 base URLs by chain ID."""
        return {
            1: "https://api.etherscan.io/v2/api",
        }


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
