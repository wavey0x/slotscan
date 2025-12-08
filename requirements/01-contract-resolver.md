# Contract Resolver Service

## Overview

The Contract Resolver is responsible for taking a raw contract address and resolving all metadata needed for storage analysis: verifying it's a contract, detecting supported proxy patterns, fetching verification status, and obtaining source code. MVP scope: EIP-1967 (impl/admin) and optional EIP-1822 check only; Postgres is the sole cache; all work is in-request.

## Implementation Status: ✅ Complete

### Key Implementation Decisions

1. **Sourcify Priority with Layout Parsing**: When Sourcify returns a verified contract, the resolver now parses `storageLayout` directly from the Sourcify response using `LayoutParser.parse_from_raw_layout()`. This avoids recompilation and uses the exact layout from original deployment.

2. **Fallback to Solc Compilation**: For Etherscan-only contracts (no Sourcify match), layout is compiled from source code using solc with extracted compiler settings.

3. **Contract Name Resolution**: Uses FQName matching (`filename:ContractName`) to locate the correct contract in multi-contract compilations.

4. **Proxy Detection**: EIP-1967 implementation/admin slots checked; UUPS contracts detected via implementation slot presence.

## Location

```
backend/app/services/resolver.py
```

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `web3.py` | RPC calls (`eth_getCode`, `eth_getStorageAt`) |
| `httpx` | Async HTTP client for Sourcify/Etherscan APIs |
| Database Layer | Cache contract metadata (Postgres only) |

## Public Interface

```python
@dataclass
class ContractMetadata:
    """Result of contract resolution."""
    chain_id: int
    address: str                          # Checksummed
    code_hash: str                         # keccak256 of bytecode
    is_proxy: bool
    proxy_type: Optional[str]              # "eip1967", "eip1822", None
    implementation_address: Optional[str]  # If proxy, the impl address
    is_verified: bool
    verification_source: Optional[str]     # "sourcify", "etherscan", None
    name: Optional[str]                    # Contract name from source
    compiler_version: Optional[str]
    sources: Optional[Dict[str, str]]      # filename -> source code
    compiler_settings: Optional[Dict]      # Optimization, runs, etc.


class ContractResolver:
    """Resolves contract metadata from address."""

    async def resolve(
        self,
        chain_id: int,
        address: str,
        block_number: Optional[int] = None  # For proxy impl at specific block
    ) -> ContractMetadata:
        """
        Resolve full contract metadata.

        Raises:
            NotAContractError: If address has no code
            RPCError: If RPC calls fail
        """
        pass

    async def is_contract(
        self,
        chain_id: int,
        address: str,
        block_number: Optional[int] = None
    ) -> bool:
        """Quick check if address is a contract."""
        pass

    async def detect_proxy(
        self,
        chain_id: int,
        address: str,
        block_number: Optional[int] = None
    ) -> Optional[ProxyInfo]:
        """Detect if contract is a proxy and get implementation."""
        pass


@dataclass
class ProxyInfo:
    proxy_type: str                  # "eip1967", "eip1822"
    implementation_address: str
    admin_address: Optional[str]     # For transparent proxies
```

## Implementation Details

### 1. Contract Existence Check

```python
async def _check_is_contract(self, chain_id: int, address: str, block: Optional[int]) -> bytes:
    """
    Check if address is a contract and return bytecode.

    Returns:
        Bytecode bytes if contract exists

    Raises:
        NotAContractError: If no code at address
    """
    web3 = self._get_web3(chain_id)

    block_id = block if block else "latest"
    code = await web3.eth.get_code(address, block_identifier=block_id)

    if code == b'' or code == b'0x':
        raise NotAContractError(f"No code at {address}")

    return code
```

### 2. Proxy Detection

Check known proxy slots in order of prevalence:

```python
# EIP-1967 Implementation Slot
# bytes32(uint256(keccak256('eip1967.proxy.implementation')) - 1)
EIP1967_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"

# EIP-1967 Admin Slot
# bytes32(uint256(keccak256('eip1967.proxy.admin')) - 1)
EIP1967_ADMIN_SLOT = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"

# EIP-1822 UUPS Slot (optional check)
# keccak256("PROXIABLE")
EIP1822_SLOT = "0xc5f16f0fcc639fa48a6947836d9850f504798523bf8c9a3a87d5876cf622bcf7"


async def detect_proxy(self, chain_id: int, address: str, block: Optional[int] = None) -> Optional[ProxyInfo]:
    """
    Detect proxy pattern and resolve implementation.

    Detection order:
    1. EIP-1967 implementation slot (most common)
    2. EIP-1822 UUPS slot (fallback)

    Returns None if not a proxy. Out of scope (v1): beacon proxies, diamonds, legacy OZ slots.
    """
    web3 = self._get_web3(chain_id)
    block_id = block if block else "latest"

    # Check EIP-1967 first (covers Transparent + UUPS)
    impl_value = await web3.eth.get_storage_at(address, EIP1967_IMPL_SLOT, block_id)
    impl_address = self._extract_address(impl_value)

    if impl_address and impl_address != ZERO_ADDRESS:
        # Also try to get admin for transparent proxies
        admin_value = await web3.eth.get_storage_at(address, EIP1967_ADMIN_SLOT, block_id)
        admin_address = self._extract_address(admin_value)

        return ProxyInfo(
            proxy_type="eip1967",
            implementation_address=impl_address,
            admin_address=admin_address if admin_address != ZERO_ADDRESS else None
        )

    # Check EIP-1822
    uups_value = await web3.eth.get_storage_at(address, EIP1822_SLOT, block_id)
    uups_address = self._extract_address(uups_value)

    if uups_address and uups_address != ZERO_ADDRESS:
        return ProxyInfo(
            proxy_type="eip1822",
            implementation_address=uups_address,
            admin_address=None
        )

    return None


def _extract_address(self, slot_value: bytes) -> Optional[str]:
    """Extract address from 32-byte slot value (last 20 bytes)."""
    if len(slot_value) != 32:
        return None

    # Address is in the last 20 bytes
    address_bytes = slot_value[12:32]

    if address_bytes == b'\x00' * 20:
        return None

    return Web3.to_checksum_address(address_bytes)
```

### 3. Verification Lookup

Try Sourcify first (open, no API key), then Etherscan:

```python
async def _fetch_verification(
    self,
    chain_id: int,
    address: str
) -> Optional[VerificationResult]:
    """
    Fetch verified source from Sourcify or Etherscan.

    Returns None if not verified on either. Cache in Postgres and refresh periodically (e.g., every 24 hours).
    """
    # Try Sourcify first (no API key needed, open source)
    sourcify_result = await self._try_sourcify(chain_id, address)
    if sourcify_result:
        return sourcify_result

    # Fall back to Etherscan
    etherscan_result = await self._try_etherscan(chain_id, address)
    if etherscan_result:
        return etherscan_result

    return None


async def _try_sourcify(self, chain_id: int, address: str) -> Optional[VerificationResult]:
    """
    Query Sourcify API for verified source.

    Sourcify API: https://sourcify.dev/server/

    Endpoints:
    - GET /files/{chain_id}/{address}  (full match)
    - GET /files/any/{chain_id}/{address}  (partial match OK)
    """
    base_url = "https://sourcify.dev/server"

    # Try full match first
    url = f"{base_url}/files/{chain_id}/{address}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url)

            if response.status_code == 200:
                data = response.json()
                return self._parse_sourcify_response(data, "full")

            # Try partial match
            url = f"{base_url}/files/any/{chain_id}/{address}"
            response = await client.get(url)

            if response.status_code == 200:
                data = response.json()
                return self._parse_sourcify_response(data, "partial")

        except httpx.RequestError:
            pass  # Sourcify unavailable, try Etherscan; do not fail

    return None

### 5. Degraded Modes
- If explorer APIs are unavailable, return best-effort metadata without failing the request.
- If proxy detection RPC reads fail, fall back to “not detected” and proceed.


def _parse_sourcify_response(self, data: dict, match_type: str) -> VerificationResult:
    """Parse Sourcify response into VerificationResult."""
    sources = {}
    metadata = None

    for file_info in data.get("files", []):
        name = file_info.get("name", "")
        content = file_info.get("content", "")

        if name == "metadata.json":
            metadata = json.loads(content)
        elif name.endswith(".sol"):
            sources[name] = content

    compiler_version = None
    compiler_settings = None
    contract_name = None

    if metadata:
        compiler_version = metadata.get("compiler", {}).get("version")
        compiler_settings = metadata.get("settings", {})
        # Extract contract name from metadata target
        target = metadata.get("settings", {}).get("compilationTarget", {})
        if target:
            contract_name = list(target.values())[0]

    return VerificationResult(
        source="sourcify",
        match_type=match_type,
        name=contract_name,
        compiler_version=compiler_version,
        compiler_settings=compiler_settings,
        sources=sources
    )


async def _try_etherscan(self, chain_id: int, address: str) -> Optional[VerificationResult]:
    """
    Query Etherscan API for verified source.

    Requires API key configured per chain.
    """
    api_config = self._get_etherscan_config(chain_id)
    if not api_config:
        return None

    params = {
        "module": "contract",
        "action": "getsourcecode",
        "address": address,
        "apikey": api_config.api_key
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(api_config.base_url, params=params)

            if response.status_code != 200:
                return None

            data = response.json()

            if data.get("status") != "1":
                return None

            result = data.get("result", [{}])[0]

            if not result.get("SourceCode"):
                return None

            return self._parse_etherscan_response(result)

        except httpx.RequestError:
            return None


def _parse_etherscan_response(self, result: dict) -> VerificationResult:
    """Parse Etherscan getsourcecode response."""
    source_code = result.get("SourceCode", "")
    contract_name = result.get("ContractName", "")
    compiler_version = result.get("CompilerVersion", "")

    # Handle Etherscan's weird double-brace JSON format
    sources = {}
    if source_code.startswith("{{"):
        # Multi-file JSON format
        source_code = source_code[1:-1]  # Remove outer braces
        parsed = json.loads(source_code)
        if "sources" in parsed:
            for filename, content in parsed["sources"].items():
                sources[filename] = content.get("content", "")
    elif source_code.startswith("{"):
        # Standard JSON input format
        parsed = json.loads(source_code)
        if "sources" in parsed:
            for filename, content in parsed["sources"].items():
                sources[filename] = content.get("content", "")
    else:
        # Single file
        sources[f"{contract_name}.sol"] = source_code

    # Parse compiler settings
    optimization = result.get("OptimizationUsed") == "1"
    runs = int(result.get("Runs", "200"))

    compiler_settings = {
        "optimizer": {
            "enabled": optimization,
            "runs": runs
        }
    }

    return VerificationResult(
        source="etherscan",
        match_type="full",
        name=contract_name,
        compiler_version=compiler_version,
        compiler_settings=compiler_settings,
        sources=sources
    )
```

### 4. Main Resolution Flow

```python
async def resolve(
    self,
    chain_id: int,
    address: str,
    block_number: Optional[int] = None
) -> ContractMetadata:
    """
    Full resolution pipeline.

    1. Check cache first
    2. Verify it's a contract
    3. Detect proxy pattern
    4. Fetch verification from Sourcify/Etherscan
    5. Cache and return result
    """
    address = Web3.to_checksum_address(address)

    # Check cache
    cached = await self.cache.get_contract(chain_id, address)
    if cached and not self._needs_refresh(cached):
        return cached

    # Verify it's a contract
    bytecode = await self._check_is_contract(chain_id, address, block_number)
    code_hash = Web3.keccak(bytecode).hex()

    # Detect proxy
    proxy_info = await self.detect_proxy(chain_id, address, block_number)

    # Determine which address to verify
    # For proxies, we want the implementation's source
    verify_address = address
    if proxy_info:
        verify_address = proxy_info.implementation_address

    # Fetch verification
    verification = await self._fetch_verification(chain_id, verify_address)

    # Build result
    result = ContractMetadata(
        chain_id=chain_id,
        address=address,
        code_hash=code_hash,
        is_proxy=proxy_info is not None,
        proxy_type=proxy_info.proxy_type if proxy_info else None,
        implementation_address=proxy_info.implementation_address if proxy_info else None,
        is_verified=verification is not None,
        verification_source=verification.source if verification else None,
        name=verification.name if verification else None,
        compiler_version=verification.compiler_version if verification else None,
        sources=verification.sources if verification else None,
        compiler_settings=verification.compiler_settings if verification else None
    )

    # Cache result
    await self.cache.save_contract(result)

    return result
```

## Caching Strategy

| Data | Cache Key | TTL |
|------|-----------|-----|
| Contract metadata | `(chain_id, address)` | Permanent (until code changes) |
| Verification status | Part of metadata | Revalidate every 24h |

### Cache Invalidation

- If `code_hash` changes (rare, upgradeable proxy changed impl), refresh
- If `is_verified=False` and >24h old, retry verification lookup

## Error Handling

```python
class NotAContractError(Exception):
    """Raised when address has no bytecode."""
    def __init__(self, address: str):
        self.address = address
        super().__init__(f"No contract code at {address}")


class RPCError(Exception):
    """Raised when RPC call fails."""
    def __init__(self, method: str, error: str):
        self.method = method
        self.error = error
        super().__init__(f"RPC {method} failed: {error}")
```

## Configuration

```python
@dataclass
class ResolverConfig:
    # Etherscan API keys per chain
    etherscan_keys: Dict[int, str]  # chain_id -> api_key

    # Etherscan base URLs per chain
    etherscan_urls: Dict[int, str] = field(default_factory=lambda: {
        1: "https://api.etherscan.io/api",
        11155111: "https://api-sepolia.etherscan.io/api",
    })

    # Sourcify base URL
    sourcify_url: str = "https://sourcify.dev/server"

    # Request timeouts
    http_timeout: float = 10.0
    rpc_timeout: float = 5.0

    # Cache settings
    verification_refresh_hours: int = 24
```

## Testing Strategy

### Unit Tests

1. **Proxy detection**
   - Test EIP-1967 transparent proxy
   - Test EIP-1967 UUPS proxy
   - Test EIP-1822 proxy
   - Test non-proxy contract
   - Test empty slots

2. **Sourcify parsing**
   - Test full match response
   - Test partial match response
   - Test multi-file sources

3. **Etherscan parsing**
   - Test single file source
   - Test multi-file JSON format
   - Test double-brace format

### Integration Tests

1. **Real contract resolution**
   - Resolve known verified contract (USDC, WETH)
   - Resolve known proxy (Aave pools)
   - Resolve unverified contract

2. **Error cases**
   - Non-contract address (EOA)
   - Invalid address format
   - RPC unavailable

## Performance Considerations

1. **Parallel slot reads**: Read proxy slots in parallel
2. **HTTP connection reuse**: Use shared `httpx.AsyncClient`
3. **Cache aggressively**: Contract metadata rarely changes
4. **Fail fast**: If RPC fails, don't retry excessively

## Example Usage

```python
resolver = ContractResolver(config, cache, web3_provider)

# Resolve USDC on mainnet
metadata = await resolver.resolve(
    chain_id=1,
    address="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
)

print(f"Contract: {metadata.name}")
print(f"Verified: {metadata.is_verified} ({metadata.verification_source})")
print(f"Proxy: {metadata.is_proxy} ({metadata.proxy_type})")
if metadata.is_proxy:
    print(f"Implementation: {metadata.implementation_address}")
```
