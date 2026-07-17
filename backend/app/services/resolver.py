"""Contract resolver for fetching metadata, proxy detection, and verification lookup."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

import httpx
from web3 import Web3

from app.config import Settings
from app.models.domain import ContractMetadata, ProxyInfo, StorageLayout, VerificationResult
from app.models.errors import NotAContractError, RPCError, VerificationProviderError
from app.repositories.contracts import ContractRepository
from app.services.layout import LayoutParser
from app.services.namespace_storage import NamespaceStorageParser
from app.services.web3_provider import Web3Provider
from app.repositories.compiler_artifacts import CompilerArtifactRepository
from app.utils.vyper import vyper_storage_policy

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

# EIP-1967 Beacon Slot - keccak256("eip1967.proxy.beacon") - 1
# Used by Euler EVK, OpenZeppelin BeaconProxy, and other upgradeable contracts
EIP1967_BEACON_SLOT = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"

# Standard beacon implementation() function selector
BEACON_IMPL_SELECTOR = "0x5c60da1b"

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
LAYOUT_RESOLVER_VERSION = 5

# EIP-7702 delegation designator: 0xef0100 || 20-byte delegate address.
EIP7702_PREFIX = bytes.fromhex("ef0100")

# EIP-1167 Minimal Proxy bytecode patterns
# Standard: 363d3d373d3d3d363d73<address>5af43d82803e903d91602b57fd5bf3
EIP1167_PREFIX = bytes.fromhex("363d3d373d3d3d363d73")
EIP1167_SUFFIX = bytes.fromhex("5af43d82803e903d91602b57fd5bf3")

# Vyper minimal proxy variant
VYPER_PROXY_PREFIX = bytes.fromhex("366000600037611000600036600073")
VYPER_PROXY_SUFFIX = bytes.fromhex("5af4602c57600080fd5b6110006000f3")


def _parse_eip7702_designator(bytecode: bytes) -> Optional[str]:
    """Return the one-hop delegate from an exact EIP-7702 designator."""
    if len(bytecode) != 23 or not bytecode.startswith(EIP7702_PREFIX):
        return None
    return Web3.to_checksum_address(bytecode[3:])


class ContractResolver:
    """Resolves contract metadata from address."""

    def __init__(
        self,
        web3_provider: Web3Provider,
        settings: Settings,
        contract_repo: Optional[ContractRepository] = None,
        layout_parser: Optional[LayoutParser] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        compiler_artifact_repo: Optional[CompilerArtifactRepository] = None,
    ):
        self.web3_provider = web3_provider
        self.settings = settings
        self.contract_repo = contract_repo
        self.layout_parser = layout_parser or LayoutParser()
        self.namespace_parser = NamespaceStorageParser()
        self.http_client = http_client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds
        )
        self.compiler_artifact_repo = compiler_artifact_repo

    async def resolve(
        self,
        chain_id: int,
        address: str,
        block_number: Optional[int] = None,
        sourcify_layout_only: bool = False,
        follow_proxy: bool = True,
        follow_delegation: bool = True,
    ) -> ContractMetadata:
        """
        Resolve full contract metadata.

        Chain code is checked before address caches so mutable EIP-7702
        delegations cannot return a stale layout.
        """
        address = Web3.to_checksum_address(address)

        bytecode = await self._check_is_contract(chain_id, address, block_number)
        code_hash = Web3.keccak(bytecode).hex()
        delegate_address = _parse_eip7702_designator(bytecode)
        if delegate_address and follow_delegation:
            return await self._resolve_delegated(
                chain_id=chain_id,
                authority_address=address,
                designator_hash=code_hash,
                delegate_address=delegate_address,
                block_number=block_number,
                sourcify_layout_only=sourcify_layout_only,
            )
        if delegate_address:
            # The protocol follows a delegation exactly once. Callers that
            # already followed one hop must treat these bytes as loaded code.
            return ContractMetadata(
                chain_id=chain_id,
                address=address,
                code_hash=code_hash,
            )

        # A cached address binding is usable only while its raw code identity
        # still matches the selected chain state.
        if self.contract_repo and block_number is not None:
            historical = await self.contract_repo.get_at_block(
                chain_id, address, block_number
            )
            if (
                historical
                and self._cache_matches_code_hash(historical, code_hash)
                and (follow_proxy or not historical.is_proxy)
            ):
                metadata = self.contract_repo.to_metadata(historical)
                layout = metadata.storage_layout
                if (
                    isinstance(layout, StorageLayout)
                    and self._cache_layout_is_usable(layout)
                ):
                    layout.resolver_version = LAYOUT_RESOLVER_VERSION
                    await self._hydrate_compiler_inputs(metadata)
                    return metadata
                if (
                    (not historical.is_verified or not historical.storage_layout)
                    and self._source_check_is_fresh(historical)
                ):
                    await self._hydrate_compiler_inputs(metadata)
                    return metadata

        # The address cache is not block-versioned. It is safe only for latest;
        # historical proxy/address resolution must inspect chain state at the
        # requested block instead of reusing today's implementation/layout.
        if self.contract_repo and block_number is None:
            cached = await self.contract_repo.get(chain_id, address)
            if (
                cached
                and self._cache_matches_code_hash(cached, code_hash)
                and (follow_proxy or not cached.is_proxy)
            ):
                logger.debug(f"Cache hit for {address} on chain {chain_id}")
                metadata = self.contract_repo.to_metadata(cached)
                layout = metadata.storage_layout
                if (
                    isinstance(layout, StorageLayout)
                    and self._cache_layout_is_usable(layout)
                ):
                    layout.resolver_version = LAYOUT_RESOLVER_VERSION
                    await self._hydrate_compiler_inputs(metadata)
                    return metadata
                if (
                    (not cached.is_verified or not cached.storage_layout)
                    and self._source_check_is_fresh(cached)
                ):
                    await self._hydrate_compiler_inputs(metadata)
                    return metadata

        # Detect proxy (pass bytecode for EIP-1167 detection)
        proxy_info = (
            await self.detect_proxy(chain_id, address, block_number, bytecode)
            if follow_proxy
            else None
        )

        # Determine which address to verify
        verify_address = address
        if proxy_info:
            verify_address = proxy_info.implementation_address

        # Check bytecode cache for non-proxies and EIP-1167 minimal proxies
        # (EIP-1967/1822 proxies have same bytecode but different implementations, can't cache)
        parsed_layout = None
        compiler_artifact = None
        cached_by_bytecode = None
        use_bytecode_cache = not proxy_info or proxy_info.proxy_type == "eip1167"

        if use_bytecode_cache and self.contract_repo:
            cached_by_bytecode = await self.contract_repo.get_layout_by_code_hash(code_hash)
            if cached_by_bytecode and cached_by_bytecode.storage_layout:
                logger.info(f"Bytecode cache hit for {address} (code_hash={code_hash[:16]}...)")
                candidate_layout = StorageLayout.from_dict(cached_by_bytecode.storage_layout)
                if self._cache_layout_is_usable(candidate_layout):
                    candidate_layout.resolver_version = LAYOUT_RESOLVER_VERSION
                    parsed_layout = candidate_layout

        # Fetch verification only if we don't have a layout from bytecode cache
        verification = None
        language = "Solidity"
        if not parsed_layout:
            if sourcify_layout_only:
                verification = await self._try_sourcify(chain_id, verify_address)
            else:
                verification = await self._fetch_verification(chain_id, verify_address)
            if verification:
                language = getattr(verification, "language", None) or "Solidity"

        if not parsed_layout and verification and verification.storage_layout:
            try:
                if "types" in verification.storage_layout and "storage" in verification.storage_layout:
                    parsed_layout = self.layout_parser.parse_from_raw_layout(
                        contract_name=verification.name or "",
                        raw_layout=verification.storage_layout,
                    )
                else:
                    parsed_layout = StorageLayout.from_dict(verification.storage_layout)
                if parsed_layout and language == "Vyper":
                    parsed_layout.compiler_version = verification.compiler_version
                    parsed_layout.storage_scheme = vyper_storage_policy(
                        verification.compiler_version
                    ).storage_scheme
                if parsed_layout and verification.sources and verification.compiler_version:
                    standard_input = {
                        "language": language,
                        "sources": {
                            filename: {"content": content}
                            for filename, content in verification.sources.items()
                        },
                        "settings": verification.compiler_settings or {},
                    }
                    compiler_artifact = self.layout_parser._make_artifact(
                        language=language,
                        compiler_version=verification.compiler_version,
                        pipeline="verified-layout",
                        standard_input=standard_input,
                        compiler_output={
                            "storageLayout": verification.storage_layout,
                        },
                        sources=verification.sources,
                    )
                    if self.compiler_artifact_repo:
                        await self.compiler_artifact_repo.save(compiler_artifact)
            except Exception as e:
                logger.warning(f"Failed to parse layout from verification: {e}")
                parsed_layout = None
        # Sourcify can return a deliberately empty compiler layout for old
        # compiler versions and contracts that exclusively use custom storage
        # pointers. Derive those layouts from verified source without compiling.
        if verification and verification.sources and language != "Vyper":
            try:
                if parsed_layout is None:
                    parsed_layout = StorageLayout(
                        contract_name=verification.name or "",
                        variables=[],
                        types={},
                        language=language,
                    )
                if not parsed_layout.variables:
                    conventional_layout = self.namespace_parser.parse_standard_storage(
                        verification.sources,
                        verification.name or parsed_layout.contract_name,
                    )
                    if conventional_layout:
                        parsed_layout = self._merge_layouts(parsed_layout, conventional_layout)
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
                unstructured_layout = self.namespace_parser.parse_unstructured_constants(
                    verification.sources
                )
                if unstructured_layout and len(unstructured_layout.variables) > 0:
                    parsed_layout = self._merge_layouts(parsed_layout, unstructured_layout)
            except Exception as e:
                logger.warning(f"Failed to parse verified source storage: {e}")

        if (
            verification
            and verification.sources
            and language == "Vyper"
            and not (parsed_layout and parsed_layout.variables)
        ):
            policy = vyper_storage_policy(verification.compiler_version)
            if policy.compiler_layout_supported:
                try:
                    parsed_layout, compiler_artifact = (
                        await self.layout_parser.parse_vyper_with_artifact(
                            verification.name or "",
                            verification.sources,
                            verification.compiler_version or "",
                        )
                    )
                    if self.compiler_artifact_repo:
                        await self.compiler_artifact_repo.save(compiler_artifact)
                except Exception as e:
                    logger.warning(
                        "Exact Vyper layout unavailable for %s: %s",
                        verification.compiler_version,
                        e,
                    )
            try:
                if not (parsed_layout and parsed_layout.variables):
                    parsed_layout = self.namespace_parser.parse_vyper_storage(
                        verification.sources,
                        verification.name or "",
                        verification.compiler_version,
                    )
            except Exception as e:
                logger.warning(f"Failed to parse verified Vyper storage: {e}")

        if parsed_layout and not parsed_layout.variables:
            parsed_layout = None
        if parsed_layout:
            if verification:
                parsed_layout.language = language
                parsed_layout.compiler_version = verification.compiler_version
                if language == "Vyper" and not parsed_layout.storage_scheme:
                    parsed_layout.storage_scheme = vyper_storage_policy(
                        verification.compiler_version
                    ).storage_scheme
            parsed_layout.resolver_version = LAYOUT_RESOLVER_VERSION

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
                compiler_artifact_fingerprint=cached_by_bytecode.compiler_artifact_fingerprint,
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
                compiler_artifact_fingerprint=(
                    compiler_artifact.fingerprint if compiler_artifact else None
                ),
            )

        await self._hydrate_compiler_inputs(result)

        # Cache every conclusive source lookup. Confirmed misses and verified
        # identities without layouts expire separately from usable layouts.
        if follow_proxy and self.contract_repo and block_number is None:
            await self.contract_repo.save(result)
        elif follow_proxy and self.contract_repo and block_number is not None:
            await self.contract_repo.save_at_block(result, block_number)

        return result

    async def _resolve_delegated(
        self,
        *,
        chain_id: int,
        authority_address: str,
        designator_hash: str,
        delegate_address: str,
        block_number: Optional[int],
        sourcify_layout_only: bool,
    ) -> ContractMetadata:
        """Compose delegate code metadata with authority storage identity."""
        try:
            delegate = await self.resolve(
                chain_id,
                delegate_address,
                block_number=block_number,
                sourcify_layout_only=sourcify_layout_only,
                follow_proxy=False,
                follow_delegation=False,
            )
        except NotAContractError:
            delegate = None

        return ContractMetadata(
            chain_id=chain_id,
            address=authority_address,
            code_hash=designator_hash,
            is_delegated=True,
            delegate_address=delegate_address,
            delegate_code_hash=delegate.code_hash if delegate else None,
            is_proxy=False,
            proxy_type=None,
            implementation_address=None,
            is_verified=delegate.is_verified if delegate else False,
            verification_source=(
                delegate.verification_source if delegate else None
            ),
            name=delegate.name if delegate else None,
            compiler_version=delegate.compiler_version if delegate else None,
            sources=delegate.sources if delegate else None,
            compiler_settings=delegate.compiler_settings if delegate else None,
            storage_layout=delegate.storage_layout if delegate else None,
            compiler_artifact_fingerprint=(
                delegate.compiler_artifact_fingerprint if delegate else None
            ),
        )

    @staticmethod
    def _cache_matches_code_hash(row, code_hash: str) -> bool:
        cached_hash = getattr(row, "code_hash", None)
        return bool(cached_hash) and cached_hash.lower() == code_hash.lower()

    def _source_check_is_fresh(self, row) -> bool:
        checked_at = getattr(row, "source_checked_at", None)
        if checked_at is None:
            return False
        age = datetime.utcnow() - checked_at
        return age.total_seconds() <= self.settings.no_source_cache_ttl_seconds

    @staticmethod
    def _cache_layout_is_usable(layout: StorageLayout) -> bool:
        if layout.resolver_version >= LAYOUT_RESOLVER_VERSION:
            return bool(layout.variables)
        # Exact compiler-produced variables do not change when the enrichment
        # resolver changes. Preserve those valuable layouts (notably historical
        # Vyper layouts).
        if bool(layout.variables) and all(
            variable.provenance == "compiler_layout"
            for variable in layout.variables
        ):
            return True

        # Resolver versions 3 and 4 corrected only Vyper source inference.
        # Preserve compatible Solidity layouts instead of discarding verified
        # names when Sourcify does not cover the address. New layouts carry an
        # explicit language; legacy rows fall back to their stable type-ID
        # distinction (Vyper source spellings versus Solidity ``t_*`` IDs).
        if layout.resolver_version >= 2:
            inferred = [
                variable
                for variable in layout.variables
                if variable.provenance == "source_inference"
            ]
            is_vyper_source_layout = layout.language == "Vyper" or (
                layout.language is None
                and bool(inferred)
                and any(
                    not variable.type_id.startswith("t_")
                    for variable in inferred
                )
            )
            return bool(layout.variables) and not is_vyper_source_layout

        return False

    async def _hydrate_compiler_inputs(self, metadata: ContractMetadata) -> None:
        """Restore sources/settings retained with the raw compiler artifact."""
        if not (
            metadata.compiler_artifact_fingerprint and self.compiler_artifact_repo
        ):
            return
        artifact = await self.compiler_artifact_repo.get(
            metadata.compiler_artifact_fingerprint
        )
        if not artifact:
            return
        metadata.sources = {
            filename: source.get("content", "")
            for filename, source in artifact.standard_input.get("sources", {}).items()
        }
        metadata.compiler_settings = artifact.standard_input.get("settings")

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
        block_id = block if block is not None else "latest"

        try:
            code = await self.web3_provider.get_code(chain_id, address, block_id)
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
        block_id = block if block is not None else "latest"

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
            # Fetch EIP-1967, EIP-1822, ZeppelinOS, and Beacon slots in parallel
            impl_task = self.web3_provider.get_storage_at(
                chain_id, address, EIP1967_IMPL_SLOT, block_id
            )
            uups_task = self.web3_provider.get_storage_at(
                chain_id, address, EIP1822_SLOT, block_id
            )
            zos_task = self.web3_provider.get_storage_at(
                chain_id, address, ZEPPELINOS_IMPL_SLOT, block_id
            )
            beacon_task = self.web3_provider.get_storage_at(
                chain_id, address, EIP1967_BEACON_SLOT, block_id
            )
            impl_value, uups_value, zos_value, beacon_value = await asyncio.gather(
                impl_task, uups_task, zos_task, beacon_task
            )

            impl_address = self._extract_address(bytes(impl_value))

            if impl_address and impl_address != ZERO_ADDRESS:
                # EIP-1967 found, fetch admin slot
                admin_value = await self.web3_provider.get_storage_at(
                    chain_id, address, EIP1967_ADMIN_SLOT, block_id
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
                zos_admin_value = await self.web3_provider.get_storage_at(
                    chain_id, address, ZEPPELINOS_ADMIN_SLOT, block_id
                )
                zos_admin_address = self._extract_address(bytes(zos_admin_value))

                return ProxyInfo(
                    proxy_type="zeppelinos",
                    implementation_address=zos_address,
                    admin_address=(
                        zos_admin_address if zos_admin_address != ZERO_ADDRESS else None
                    ),
                )

            # Check EIP-1967 Beacon Proxy (used by Euler EVK, OpenZeppelin BeaconProxy)
            beacon_address = self._extract_address(bytes(beacon_value))

            if beacon_address and beacon_address != ZERO_ADDRESS:
                # Beacon found, call implementation() on the beacon to get actual impl
                try:
                    impl_result = await self.web3_provider.eth_call(
                        chain_id,
                        {"to": beacon_address, "data": BEACON_IMPL_SELECTOR},
                        block_id,
                    )
                    beacon_impl_address = self._extract_address(bytes(impl_result))

                    if beacon_impl_address and beacon_impl_address != ZERO_ADDRESS:
                        return ProxyInfo(
                            proxy_type="beacon",
                            implementation_address=beacon_impl_address,
                            admin_address=None,  # Beacon proxies don't have admin in proxy
                        )
                except Exception as e:
                    logger.warning(f"Failed to get implementation from beacon {beacon_address}: {e}")

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
            variables=list({
                (variable.name, variable.slot, variable.offset, variable.type_id): variable
                for variable in merged_variables
            }.values()),
            types=merged_types,
            resolver_version=LAYOUT_RESOLVER_VERSION,
            language=standard_layout.language or namespace_layout.language,
            compiler_version=(
                standard_layout.compiler_version or namespace_layout.compiler_version
            ),
            storage_scheme=(
                standard_layout.storage_scheme or namespace_layout.storage_scheme
            ),
        )

    async def _fetch_verification(
        self, chain_id: int, address: str
    ) -> Optional[VerificationResult]:
        """Fetch verified source from Sourcify or Etherscan."""
        failures: list[str] = []
        try:
            sourcify_result = await self._try_sourcify(chain_id, address)
            if sourcify_result:
                return sourcify_result
        except VerificationProviderError as exc:
            failures.extend(exc.errors)

        try:
            etherscan_result = await self._try_etherscan(chain_id, address)
            if etherscan_result:
                return etherscan_result
        except VerificationProviderError as exc:
            failures.extend(exc.errors)

        if failures:
            raise VerificationProviderError(failures)
        return None

    async def _try_sourcify(
        self, chain_id: int, address: str
    ) -> Optional[VerificationResult]:
        """Fetch Sourcify's compiler-produced layout without local compilation."""
        url = f"https://sourcify.dev/server/v2/contract/{chain_id}/{address}"

        try:
            response = await self.http_client.get(
                url,
                params={"fields": "sources,storageLayout,compilation"},
            )
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                raise VerificationProviderError(
                    [f"sourcify HTTP {response.status_code}"]
                )

            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
            compilation = data.get("compilation") or {}
            if not isinstance(compilation, dict):
                raise ValueError("expected compilation metadata to be an object")
            fully_qualified_name = compilation.get("fullyQualifiedName") or ""
            compilation_target = None
            target_name = None
            if ":" in fully_qualified_name:
                source_path, target_name = fully_qualified_name.rsplit(":", 1)
                compilation_target = {source_path: target_name}

            raw_sources = data.get("sources") or {}
            if not isinstance(raw_sources, dict):
                raise ValueError("expected sources to be an object")
            sources: dict[str, str] = {}
            for filename, source in raw_sources.items():
                if isinstance(source, str):
                    sources[filename] = source
                elif isinstance(source, dict) and isinstance(source.get("content"), str):
                    sources[filename] = source["content"]

            return VerificationResult(
                source="sourcify",
                match_type=data.get("match") or "unknown",
                name=compilation.get("name") or target_name,
                compilation_target=compilation_target,
                compiler_version=compilation.get("compilerVersion"),
                compiler_settings=compilation.get("compilerSettings"),
                sources=sources or None,
                storage_layout=data.get("storageLayout"),
                language=compilation.get("language") or "Solidity",
            )
        except httpx.RequestError as e:
            logger.warning(f"Sourcify request failed: {e}")
            raise VerificationProviderError(
                [f"sourcify {type(e).__name__}"]
            ) from e
        except (TypeError, ValueError) as e:
            logger.warning(f"Invalid Sourcify response for {address}: {e}")
            raise VerificationProviderError(["sourcify invalid response"]) from e

        return None

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

        try:
            response = await self.http_client.get(base_url, params=params)

            if response.status_code != 200:
                raise VerificationProviderError(
                    [f"etherscan HTTP {response.status_code}"]
                )

            data = response.json()

            if data.get("status") != "1":
                detail = f"{data.get('message', '')} {data.get('result', '')}"
                normalized = detail.lower()
                if "not verified" in normalized or "no data found" in normalized:
                    return None
                raise VerificationProviderError(["etherscan unavailable"])

            result = data.get("result", [{}])[0]

            if not result.get("SourceCode"):
                return None

            return self._parse_etherscan_response(result)

        except httpx.RequestError as e:
            logger.warning(f"Etherscan request failed: {e}")
            raise VerificationProviderError(
                [f"etherscan {type(e).__name__}"]
            ) from e

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
