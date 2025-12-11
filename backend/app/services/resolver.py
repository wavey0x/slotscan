"""Contract resolver for fetching metadata, proxy detection, and verification lookup."""

import asyncio
import json
import logging
from typing import Optional

import httpx
from web3 import Web3

from app.config import Settings
from app.models.domain import ContractMetadata, ProxyInfo, StorageLayout, VerificationResult
from app.models.errors import NotAContractError, RPCError, UnsupportedCompilerVersionError
from app.repositories.contracts import ContractRepository
from app.services.layout import LayoutParser
from app.services.namespace_storage import NamespaceStorageParser
from app.services.web3_provider import Web3Provider

logger = logging.getLogger(__name__)

# EIP-1967 Implementation Slot
EIP1967_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"

# EIP-1967 Admin Slot
EIP1967_ADMIN_SLOT = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"

# EIP-1822 UUPS Slot
EIP1822_SLOT = "0xc5f16f0fcc639fa48a6947836d9850f504798523bf8c9a3a87d5876cf622bcf7"

# ZeppelinOS (pre-EIP-1967) Implementation Slot - keccak256("org.zeppelinos.proxy.implementation")
# Used by USDC and other older OpenZeppelin proxies
ZEPPELINOS_IMPL_SLOT = "0x7050c9e0f4ca769c69bd3a8ef740bc37934f8e2c036e5a723fd8ee048ed3f8c3"

# ZeppelinOS Admin Slot - keccak256("org.zeppelinos.proxy.admin")
ZEPPELINOS_ADMIN_SLOT = "0x10d6a54a4754c8869d6886b5f5d7fbfa5b4522237ea5c60d11bc4e7a1ff9390b"

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# EIP-1167 Minimal Proxy bytecode patterns
# Standard: 363d3d373d3d3d363d73<address>5af43d82803e903d91602b57fd5bf3
EIP1167_PREFIX = bytes.fromhex("363d3d373d3d3d363d73")
EIP1167_SUFFIX = bytes.fromhex("5af43d82803e903d91602b57fd5bf3")

# Vyper minimal proxy variant
VYPER_PROXY_PREFIX = bytes.fromhex("366000600037611000600036600073")
VYPER_PROXY_SUFFIX = bytes.fromhex("5af4602c57600080fd5b6110006000f3")


class ContractResolver:
    """Resolves contract metadata from address."""

    def __init__(
        self,
        web3_provider: Web3Provider,
        settings: Settings,
        contract_repo: Optional[ContractRepository] = None,
        layout_parser: Optional[LayoutParser] = None,
    ):
        self.web3_provider = web3_provider
        self.settings = settings
        self.contract_repo = contract_repo
        self.layout_parser = layout_parser or LayoutParser()
        self.namespace_parser = NamespaceStorageParser()

    async def resolve(
        self,
        chain_id: int,
        address: str,
        block_number: Optional[int] = None,
    ) -> ContractMetadata:
        """
        Resolve full contract metadata.

        1. Check cache first
        2. Verify it's a contract
        3. Detect proxy pattern
        4. Fetch verification from Sourcify/Etherscan
        5. Cache and return result
        """
        address = Web3.to_checksum_address(address)

        # Check cache first
        if self.contract_repo:
            cached = await self.contract_repo.get(chain_id, address)
            if cached and cached.is_verified and cached.storage_layout:
                logger.debug(f"Cache hit for {address} on chain {chain_id}")
                return self.contract_repo.to_metadata(cached)

        # Verify it's a contract
        bytecode = await self._check_is_contract(chain_id, address, block_number)
        code_hash = Web3.keccak(bytecode).hex()

        # Detect proxy (pass bytecode for EIP-1167 detection)
        proxy_info = await self.detect_proxy(chain_id, address, block_number, bytecode)

        # Determine which address to verify
        verify_address = address
        if proxy_info:
            verify_address = proxy_info.implementation_address

        # Check bytecode cache for non-proxies and EIP-1167 minimal proxies
        # (EIP-1967/1822 proxies have same bytecode but different implementations, can't cache)
        parsed_layout = None
        cached_by_bytecode = None
        use_bytecode_cache = not proxy_info or proxy_info.proxy_type == "eip1167"

        if use_bytecode_cache and self.contract_repo:
            cached_by_bytecode = await self.contract_repo.get_layout_by_code_hash(code_hash)
            if cached_by_bytecode and cached_by_bytecode.storage_layout:
                logger.info(f"Bytecode cache hit for {address} (code_hash={code_hash[:16]}...)")
                parsed_layout = StorageLayout.from_dict(cached_by_bytecode.storage_layout)

        # Fetch verification only if we don't have a layout from bytecode cache
        verification = None
        if not parsed_layout:
            verification = await self._fetch_verification(chain_id, verify_address)

        if not parsed_layout and verification and verification.storage_layout:
            try:
                if "types" in verification.storage_layout and "storage" in verification.storage_layout:
                    parsed_layout = self.layout_parser.parse_from_raw_layout(
                        contract_name=verification.name or "",
                        raw_layout=verification.storage_layout,
                    )
                else:
                    parsed_layout = StorageLayout.from_dict(verification.storage_layout)
            except Exception as e:
                logger.warning(f"Failed to parse layout from verification: {e}")
                parsed_layout = None
        # If no layout from verification but sources available, compile
        if not parsed_layout and verification and verification.sources and verification.compiler_version:
            language = getattr(verification, 'language', 'Solidity')
            logger.info(f"Compiling {language} layout for {verification.name} with {len(verification.sources)} source files")
            try:
                if language == "Vyper":
                    # Compile Vyper to get storage layout
                    parsed_layout = await self.layout_parser.parse_vyper(
                        contract_name=verification.name or "",
                        sources=verification.sources,
                        compiler_version=verification.compiler_version,
                    )
                else:
                    # Solidity compilation
                    parsed_layout = await self.layout_parser.parse(
                        contract_name=verification.name or "",
                        sources=verification.sources,
                        compiler_version=verification.compiler_version,
                        compiler_settings=verification.compiler_settings,
                        metadata_settings=verification.compiler_settings,
                        contract_fqname=self._get_compilation_target(verification),
                    )
                logger.info(f"Layout compiled: {len(parsed_layout.variables) if parsed_layout else 0} variables")
            except UnsupportedCompilerVersionError as e:
                # Log the compiler version issue and continue without layout
                logger.info(f"Layout unavailable for {address}: {e}")
                parsed_layout = None
            except Exception as e:
                logger.warning(f"Failed to compile layout: {e}", exc_info=True)
                parsed_layout = None

        # Check for namespaced storage (ERC-7201 pattern)
        # If the compiled layout has very few variables but sources are available,
        # the contract might be using namespaced storage
        if (parsed_layout and
            len(parsed_layout.variables) < 10 and
            verification and
            verification.sources and
            language != "Vyper"):
            try:
                namespace_layout = self.namespace_parser.parse_namespaced_storage(
                    verification.sources
                )
                if namespace_layout and len(namespace_layout.variables) > 0:
                    logger.info(
                        f"Found namespaced storage with {len(namespace_layout.variables)} "
                        f"additional variables"
                    )
                    # Merge namespace variables with standard layout
                    parsed_layout = self._merge_layouts(parsed_layout, namespace_layout)
            except Exception as e:
                logger.warning(f"Failed to parse namespace storage: {e}")

        # Build result - use bytecode cache metadata if verification was skipped
        if cached_by_bytecode and parsed_layout and not verification:
            # Reuse metadata from the cached contract with same bytecode
            result = ContractMetadata(
                chain_id=chain_id,
                address=address,
                code_hash=code_hash,
                is_proxy=proxy_info is not None,
                proxy_type=proxy_info.proxy_type if proxy_info else None,
                implementation_address=(
                    proxy_info.implementation_address if proxy_info else None
                ),
                is_verified=True,  # Same bytecode as a verified contract
                verification_source=cached_by_bytecode.verification_source,
                name=cached_by_bytecode.name,
                compiler_version=cached_by_bytecode.compiler_version,
                sources=None,  # Don't copy large source data
                compiler_settings=None,
                storage_layout=parsed_layout,
            )
        else:
            result = ContractMetadata(
                chain_id=chain_id,
                address=address,
                code_hash=code_hash,
                is_proxy=proxy_info is not None,
                proxy_type=proxy_info.proxy_type if proxy_info else None,
                implementation_address=(
                    proxy_info.implementation_address if proxy_info else None
                ),
                is_verified=verification is not None,
                verification_source=verification.source if verification else None,
                name=verification.name if verification else None,
                compiler_version=verification.compiler_version if verification else None,
                sources=verification.sources if verification else None,
                compiler_settings=verification.compiler_settings if verification else None,
                storage_layout=parsed_layout,
            )

        # Cache result only if verified AND has storage layout
        # (compilation may fail temporarily, we'll retry next request)
        if self.contract_repo and result.is_verified and result.storage_layout:
            await self.contract_repo.save(result)

        return result

    async def is_contract(
        self,
        chain_id: int,
        address: str,
        block_number: Optional[int] = None,
    ) -> bool:
        """Quick check if address is a contract."""
        try:
            await self._check_is_contract(chain_id, address, block_number)
            return True
        except NotAContractError:
            return False

    async def _check_is_contract(
        self, chain_id: int, address: str, block: Optional[int]
    ) -> bytes:
        """Check if address is a contract and return bytecode."""
        web3 = self.web3_provider.get_web3(chain_id)
        block_id = block if block else "latest"

        try:
            code = await web3.eth.get_code(address, block_identifier=block_id)
        except Exception as e:
            raise RPCError("eth_getCode", str(e))

        if code == b"" or code == b"0x" or code == bytes.fromhex(""):
            raise NotAContractError(address)

        return bytes(code)

    def _detect_minimal_proxy(self, bytecode: bytes) -> Optional[str]:
        """
        Detect EIP-1167 minimal proxy pattern and extract implementation address.

        Returns the implementation address if detected, None otherwise.
        """
        # Standard EIP-1167 pattern
        if (len(bytecode) == 45 and
            bytecode[:10] == EIP1167_PREFIX and
            bytecode[-15:] == EIP1167_SUFFIX):
            impl_bytes = bytecode[10:30]
            try:
                return Web3.to_checksum_address(impl_bytes)
            except Exception:
                pass

        # Also check for slight variations (some compilers add metadata)
        if bytecode.startswith(EIP1167_PREFIX):
            # Find the suffix
            suffix_pos = bytecode.find(EIP1167_SUFFIX)
            if suffix_pos > 10:
                impl_bytes = bytecode[10:30]
                try:
                    return Web3.to_checksum_address(impl_bytes)
                except Exception:
                    pass

        return None

    async def detect_proxy(
        self,
        chain_id: int,
        address: str,
        block: Optional[int] = None,
        bytecode: Optional[bytes] = None,
    ) -> Optional[ProxyInfo]:
        """
        Detect proxy pattern and resolve implementation.

        Detection order:
        1. EIP-1167 minimal proxy (bytecode pattern)
        2. EIP-1967 implementation slot
        3. EIP-1822 UUPS slot
        """
        web3 = self.web3_provider.get_web3(chain_id)
        block_id = block if block else "latest"

        # Check EIP-1167 minimal proxy first (from bytecode)
        if bytecode:
            impl_address = self._detect_minimal_proxy(bytecode)
            if impl_address and impl_address != ZERO_ADDRESS:
                return ProxyInfo(
                    proxy_type="eip1167",
                    implementation_address=impl_address,
                    admin_address=None,
                )

        try:
            # Fetch EIP-1967, EIP-1822, and ZeppelinOS slots in parallel
            impl_task = web3.eth.get_storage_at(
                address, EIP1967_IMPL_SLOT, block_identifier=block_id
            )
            uups_task = web3.eth.get_storage_at(
                address, EIP1822_SLOT, block_identifier=block_id
            )
            zos_task = web3.eth.get_storage_at(
                address, ZEPPELINOS_IMPL_SLOT, block_identifier=block_id
            )
            impl_value, uups_value, zos_value = await asyncio.gather(
                impl_task, uups_task, zos_task
            )

            impl_address = self._extract_address(bytes(impl_value))

            if impl_address and impl_address != ZERO_ADDRESS:
                # EIP-1967 found, fetch admin slot
                admin_value = await web3.eth.get_storage_at(
                    address, EIP1967_ADMIN_SLOT, block_identifier=block_id
                )
                admin_address = self._extract_address(bytes(admin_value))

                return ProxyInfo(
                    proxy_type="eip1967",
                    implementation_address=impl_address,
                    admin_address=(
                        admin_address if admin_address != ZERO_ADDRESS else None
                    ),
                )

            # Check EIP-1822 (already fetched)
            uups_address = self._extract_address(bytes(uups_value))

            if uups_address and uups_address != ZERO_ADDRESS:
                return ProxyInfo(
                    proxy_type="eip1822",
                    implementation_address=uups_address,
                    admin_address=None,
                )

            # Check ZeppelinOS (pre-EIP-1967, used by USDC and other older proxies)
            zos_address = self._extract_address(bytes(zos_value))

            if zos_address and zos_address != ZERO_ADDRESS:
                # ZeppelinOS found, fetch admin slot
                zos_admin_value = await web3.eth.get_storage_at(
                    address, ZEPPELINOS_ADMIN_SLOT, block_identifier=block_id
                )
                zos_admin_address = self._extract_address(bytes(zos_admin_value))

                return ProxyInfo(
                    proxy_type="zeppelinos",
                    implementation_address=zos_address,
                    admin_address=(
                        zos_admin_address if zos_admin_address != ZERO_ADDRESS else None
                    ),
                )

        except Exception as e:
            logger.warning(f"Proxy detection failed for {address}: {e}")

        return None

    def _extract_address(self, slot_value: bytes) -> Optional[str]:
        """Extract address from 32-byte slot value (last 20 bytes)."""
        if len(slot_value) != 32:
            return None

        address_bytes = slot_value[12:32]

        if address_bytes == b"\x00" * 20:
            return None

        try:
            return Web3.to_checksum_address(address_bytes)
        except Exception:
            return None

    def _get_compilation_target(self, verification: VerificationResult) -> Optional[str]:
        """Return fully qualified contract name from metadata compilationTarget if available."""
        if verification.compilation_target:
            # Expecting a dict { "path": "Contract" }
            try:
                # Take first entry
                path, name = next(iter(verification.compilation_target.items()))
                return f"{path}:{name}"
            except Exception:
                return None
        return None

    def _merge_layouts(
        self, standard_layout: StorageLayout, namespace_layout: StorageLayout
    ) -> StorageLayout:
        """
        Merge a standard storage layout with a namespaced storage layout.

        The standard layout contains variables at sequential slots (0, 1, 2, ...).
        The namespace layout contains variables at high slots (base_slot + offset).

        Returns a combined layout with all variables and types.
        """
        # Combine variables (standard first, then namespace)
        merged_variables = list(standard_layout.variables) + list(namespace_layout.variables)

        # Combine types
        merged_types = dict(standard_layout.types)
        merged_types.update(namespace_layout.types)

        return StorageLayout(
            contract_name=standard_layout.contract_name,
            variables=merged_variables,
            types=merged_types,
        )

    async def _fetch_verification(
        self, chain_id: int, address: str
    ) -> Optional[VerificationResult]:
        """Fetch verified source from Sourcify or Etherscan."""
        # Try Sourcify first
        sourcify_result = await self._try_sourcify(chain_id, address)
        if sourcify_result:
            return sourcify_result

        # Fall back to Etherscan
        etherscan_result = await self._try_etherscan(chain_id, address)
        if etherscan_result:
            return etherscan_result

        return None

    async def _try_sourcify(
        self, chain_id: int, address: str
    ) -> Optional[VerificationResult]:
        """Query Sourcify API for verified source."""
        base_url = "https://sourcify.dev/server"

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                # Try full match first
                url = f"{base_url}/files/{chain_id}/{address}"
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

            except httpx.RequestError as e:
                logger.warning(f"Sourcify request failed: {e}")

        return None

    def _parse_sourcify_response(
        self, data: dict | list, match_type: str
    ) -> VerificationResult:
        """Parse Sourcify response into VerificationResult."""
        sources = {}
        metadata = None
        storage_layout = None

        # Sourcify API returns either a list of files directly, or a dict with "files" key
        files = data if isinstance(data, list) else data.get("files", [])

        for file_info in files:
            name = file_info.get("name", "")
            path = file_info.get("path", "")
            content = file_info.get("content", "")

            if name == "metadata.json":
                try:
                    metadata = json.loads(content)
                except json.JSONDecodeError:
                    pass
            elif name.endswith("storageLayout.json"):
                try:
                    storage_layout = json.loads(content)
                except json.JSONDecodeError:
                    pass
            elif name.endswith(".sol") or name.endswith(".vy"):
                # Extract original path from Sourcify's path field
                # Format: contracts/.../sources/node_modules/@openzeppelin/...
                # We need everything after /sources/
                if "/sources/" in path:
                    original_path = path.split("/sources/", 1)[1]
                else:
                    original_path = name
                sources[original_path] = content

        compiler_version = None
        compiler_settings = None
        contract_name = None
        language = "Solidity"  # Default

        if metadata:
            compiler_version = metadata.get("compiler", {}).get("version")
            compiler_settings = metadata.get("settings", {})
            compilation_target = metadata.get("settings", {}).get("compilationTarget", {})
            target = metadata.get("settings", {}).get("compilationTarget", {})
            if target:
                contract_name = list(target.values())[0]
            # Detect language from metadata (Vyper contracts have "language": "Vyper")
            language = metadata.get("language", "Solidity")

        # Fallback: detect Vyper from file extensions if metadata doesn't specify
        if language == "Solidity" and sources:
            if any(name.endswith(".vy") for name in sources.keys()):
                language = "Vyper"

        return VerificationResult(
            source="sourcify",
            match_type=match_type,
            name=contract_name,
            compilation_target=compilation_target if metadata else None,
            compiler_version=compiler_version,
            compiler_settings=compiler_settings,
            sources=sources,
            storage_layout=storage_layout,
            language=language,
        )

    async def _try_etherscan(
        self, chain_id: int, address: str
    ) -> Optional[VerificationResult]:
        """Query Etherscan API for verified source."""
        api_key = self.settings.etherscan_keys.get(chain_id)
        base_url = self.settings.etherscan_urls.get(chain_id)

        if not api_key or not base_url:
            return None

        params = {
            "chainid": str(chain_id),  # Required for V2 API
            "module": "contract",
            "action": "getsourcecode",
            "address": address,
            "apikey": api_key,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(base_url, params=params)

                if response.status_code != 200:
                    return None

                data = response.json()

                if data.get("status") != "1":
                    return None

                result = data.get("result", [{}])[0]

                if not result.get("SourceCode"):
                    return None

                return self._parse_etherscan_response(result)

            except httpx.RequestError as e:
                logger.warning(f"Etherscan request failed: {e}")

        return None

    def _parse_etherscan_response(self, result: dict) -> VerificationResult:
        """Parse Etherscan getsourcecode response."""
        source_code = result.get("SourceCode", "")
        contract_name = result.get("ContractName", "")
        compiler_version = result.get("CompilerVersion", "")
        evm_version = result.get("EVMVersion", "")

        # Detect Vyper from compiler version (e.g., "vyper:0.2.4" or "v0.2.4")
        is_vyper = "vyper" in compiler_version.lower()
        language = "Vyper" if is_vyper else "Solidity"
        file_extension = ".vy" if is_vyper else ".sol"

        sources = {}
        metadata_settings = {
            "optimizer": {
                "enabled": result.get("OptimizationUsed") == "1",
                "runs": int(result.get("Runs", "200")),
            }
        }
        if evm_version and evm_version != "default":
            metadata_settings["evmVersion"] = evm_version

        # Handle Etherscan's various source code formats
        if source_code.startswith("{{"):
            # Multi-file JSON format (double braces)
            try:
                source_code = source_code[1:-1]
                parsed = json.loads(source_code)
                if "sources" in parsed:
                    for filename, content in parsed["sources"].items():
                        sources[filename] = content.get("content", "")
                if "settings" in parsed:
                    metadata_settings.update(parsed["settings"])
            except json.JSONDecodeError:
                sources[f"{contract_name}{file_extension}"] = source_code

        elif source_code.startswith("{"):
            # Standard JSON input format
            try:
                parsed = json.loads(source_code)
                if "sources" in parsed:
                    for filename, content in parsed["sources"].items():
                        sources[filename] = content.get("content", "")
                if "settings" in parsed:
                    metadata_settings.update(parsed["settings"])
            except json.JSONDecodeError:
                sources[f"{contract_name}{file_extension}"] = source_code
        else:
            # Single file
            sources[f"{contract_name}{file_extension}"] = source_code

        # Secondary detection: check for .vy files in sources
        if not is_vyper and any(f.endswith(".vy") for f in sources.keys()):
            language = "Vyper"

        # Parse compiler settings
        optimization = result.get("OptimizationUsed") == "1"
        runs = int(result.get("Runs", "200"))

        compiler_settings = {
            "optimizer": {
                "enabled": optimization,
                "runs": runs,
            }
        }

        return VerificationResult(
            source="etherscan",
            match_type="full",
            name=contract_name,
            compilation_target=None,
            compiler_version=compiler_version,
            compiler_settings=metadata_settings or compiler_settings,
            sources=sources,
            language=language,
        )
