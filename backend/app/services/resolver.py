"""Contract resolver for fetching metadata, proxy detection, and verification lookup."""

import asyncio
import logging
from typing import Optional

from web3 import Web3

from app.config import Settings
from app.models.domain import ContractMetadata, ProxyInfo, StorageLayout
from app.models.errors import NotAContractError, RPCError
from app.repositories.compiler_artifacts import CompilerArtifactRepository
from app.repositories.contracts import ContractRepository
from app.repositories.source_cache import SourceCacheRepository
from app.services.layout import LayoutParser
from app.services.namespace_storage import NamespaceStorageParser
from app.services.verification import VerificationService
from app.services.web3_provider import Web3Provider
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

# Gnosis Safe proxy masterCopy() function selector
GNOSIS_SAFE_MASTER_COPY_SELECTOR = "0xa619486e"

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

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
        verification_service: VerificationService,
        source_cache_repo: SourceCacheRepository,
        contract_repo: Optional[ContractRepository] = None,
        layout_parser: Optional[LayoutParser] = None,
        compiler_artifact_repo: Optional[CompilerArtifactRepository] = None,
        use_binding_cache: bool = True,
    ):
        self.web3_provider = web3_provider
        self.settings = settings
        self.verification_service = verification_service
        self.source_cache_repo = source_cache_repo
        self.contract_repo = contract_repo
        self.layout_parser = layout_parser or LayoutParser()
        self.namespace_parser = NamespaceStorageParser()
        self.compiler_artifact_repo = compiler_artifact_repo
        self.use_binding_cache = use_binding_cache

    async def resolve(
        self,
        chain_id: int,
        address: str,
        block_number: Optional[int] = None,
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
            )
        if delegate_address:
            # The protocol follows a delegation exactly once. Callers that
            # already followed one hop must treat these bytes as loaded code.
            return ContractMetadata(
                chain_id=chain_id,
                address=address,
                code_hash=code_hash,
                delegation_status="nested",
            )

        # A cached address binding is usable only while its raw code identity
        # still matches the selected chain state.
        if (
            self.use_binding_cache
            and self.contract_repo
            and block_number is not None
        ):
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
                if isinstance(layout, StorageLayout) and layout.variables:
                    return metadata

        # The address cache is not block-versioned. It is safe only for latest;
        # proxy bindings remain mutable even while proxy bytecode is unchanged,
        # so only direct-contract rows can return before proxy detection.
        if self.use_binding_cache and self.contract_repo and block_number is None:
            cached = await self.contract_repo.get(chain_id, address)
            if (
                cached
                and self._cache_matches_code_hash(cached, code_hash)
                and not cached.is_proxy
            ):
                logger.debug(f"Cache hit for {address} on chain {chain_id}")
                metadata = self.contract_repo.to_metadata(cached)
                layout = metadata.storage_layout
                if isinstance(layout, StorageLayout) and layout.variables:
                    return metadata

        # Detect proxy (pass bytecode for EIP-1167 detection)
        proxy_info = (
            await self.detect_proxy(chain_id, address, block_number, bytecode)
            if follow_proxy
            else None
        )

        # Source data is keyed by the runtime code that is actually verified,
        # not by the address whose storage is being interpreted.
        code_address = address
        verification_bytecode = bytecode
        if proxy_info:
            code_address = Web3.to_checksum_address(
                proxy_info.implementation_address
            )
            verification_bytecode = await self._read_code(
                chain_id,
                code_address,
                block_number,
            )
            if not verification_bytecode:
                result = ContractMetadata(
                    chain_id=chain_id,
                    address=address,
                    code_hash=code_hash,
                    is_proxy=True,
                    proxy_type=proxy_info.proxy_type,
                    implementation_address=code_address,
                )
                await self._save_binding(
                    result,
                    block_number=block_number,
                    follow_proxy=follow_proxy,
                )
                return result
        verification_code_hash = Web3.keccak(verification_bytecode).hex()

        # Check bytecode cache for non-proxies and EIP-1167 minimal proxies
        # (EIP-1967/1822 proxies have same bytecode but different implementations, can't cache)
        parsed_layout = None
        compiler_artifact = None
        namespace_compiler_output = None
        exact_namespace_base = False
        cached_by_bytecode = None
        use_bytecode_cache = not proxy_info or proxy_info.proxy_type == "eip1167"

        if use_bytecode_cache and self.contract_repo:
            cached_by_bytecode = await self.contract_repo.get_layout_by_code_hash(
                verification_code_hash
            )
            if cached_by_bytecode and cached_by_bytecode.storage_layout:
                logger.info(
                    "Bytecode layout cache hit for %s (code_hash=%s...)",
                    code_address,
                    verification_code_hash[:16],
                )
                candidate_layout = StorageLayout.from_dict(cached_by_bytecode.storage_layout)
                if candidate_layout.variables:
                    parsed_layout = candidate_layout

        # Fetch verification only if we don't have a layout from bytecode cache
        verification = None
        language = "Solidity"
        if not parsed_layout:
            verification = await self.verification_service.resolve(
                chain_id,
                code_address,
                verification_code_hash,
                self.source_cache_repo,
            )
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

        has_erc7201_annotation = bool(
            verification
            and verification.sources
            and language == "Solidity"
            and any(
                "@custom:storage-location erc7201:" in source
                for source in verification.sources.values()
            )
        )
        if (
            has_erc7201_annotation
            and verification
            and verification.sources
            and verification.compiler_version
        ):
            compilation_target = None
            if (
                verification.compilation_target
                and len(verification.compilation_target) == 1
            ):
                target_path, target_name = next(
                    iter(verification.compilation_target.items())
                )
                compilation_target = f"{target_path}:{target_name}"
            try:
                parsed_layout, compiler_artifact = (
                    await self.layout_parser.parse_with_artifact(
                        contract_name=verification.name or "",
                        sources=verification.sources,
                        compiler_version=verification.compiler_version,
                        compiler_settings=verification.compiler_settings,
                        metadata_settings=verification.compiler_settings,
                        contract_fqname=compilation_target,
                    )
                )
                exact_namespace_base = True
                if self.compiler_artifact_repo:
                    await self.compiler_artifact_repo.save(compiler_artifact)
                harness_source = (
                    self.namespace_parser.build_exact_erc7201_harness(
                        compiler_artifact.compiler_output
                    )
                )
                if harness_source:
                    namespace_types, namespace_compiler_output = (
                        await self.layout_parser.compile_exact_namespace_types(
                            sources=verification.sources,
                            compiler_version=verification.compiler_version,
                            compiler_settings=verification.compiler_settings,
                            harness_source=harness_source,
                        )
                    )
                    for type_id, type_info in namespace_types.items():
                        existing = parsed_layout.types.get(type_id)
                        if existing is not None and existing != type_info:
                            raise ValueError(
                                f"Conflicting compiler type definition for {type_id}"
                            )
                        parsed_layout.types[type_id] = type_info
            except Exception as e:
                logger.warning(
                    "Exact ERC-7201 compiler evidence unavailable for %s: %s",
                    code_address,
                    e,
                )

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
                if not parsed_layout.variables and not exact_namespace_base:
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
                            entry_source=(
                                next(iter(verification.compilation_target))
                                if verification.compilation_target
                                and len(verification.compilation_target) == 1
                                else None
                            ),
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

        has_exact_compiler_layout = bool(
            compiler_artifact
            or (
                verification
                and verification.storage_layout is not None
                and language != "Vyper"
            )
        )
        if parsed_layout and not parsed_layout.variables and not has_exact_compiler_layout:
            parsed_layout = None
        if parsed_layout:
            if verification:
                parsed_layout.language = language
                parsed_layout.compiler_version = verification.compiler_version
                if language == "Vyper" and not parsed_layout.storage_scheme:
                    parsed_layout.storage_scheme = vyper_storage_policy(
                        verification.compiler_version
                    ).storage_scheme
                elif language == "Solidity" and not parsed_layout.storage_scheme:
                    parsed_layout.storage_scheme = "solidity"
            if (
                language == "Solidity"
                and compiler_artifact
                and verification
                and verification.sources
            ):
                parsed_layout = self.namespace_parser.promote_exact_erc7201(
                    parsed_layout,
                    compiler_output=(
                        namespace_compiler_output
                        or compiler_artifact.compiler_output
                    ),
                    sources=verification.sources,
                    compiler_version=verification.compiler_version,
                    max_slots=self.settings.max_slots_per_contract,
                )
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
                compilation_target=None,
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
                compilation_target=(
                    verification.compilation_target if verification else None
                ),
                sources=verification.sources if verification else None,
                compiler_settings=verification.compiler_settings if verification else None,
                storage_layout=parsed_layout,
                compiler_artifact_fingerprint=(
                    compiler_artifact.fingerprint if compiler_artifact else None
                ),
            )

        await self._save_binding(
            result,
            block_number=block_number,
            follow_proxy=follow_proxy,
        )

        return result

    async def _resolve_delegated(
        self,
        *,
        chain_id: int,
        authority_address: str,
        designator_hash: str,
        delegate_address: str,
        block_number: Optional[int],
    ) -> ContractMetadata:
        """Compose delegate code metadata with authority storage identity."""
        try:
            delegate = await self.resolve(
                chain_id,
                delegate_address,
                block_number=block_number,
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
            delegation_status=(
                delegate.delegation_status
                if delegate and delegate.delegation_status
                else "ok"
                if delegate
                else "empty"
            ),
            is_proxy=False,
            proxy_type=None,
            implementation_address=None,
            is_verified=delegate.is_verified if delegate else False,
            verification_source=(
                delegate.verification_source if delegate else None
            ),
            name=delegate.name if delegate else None,
            compiler_version=delegate.compiler_version if delegate else None,
            compilation_target=delegate.compilation_target if delegate else None,
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

    async def _save_binding(
        self,
        metadata: ContractMetadata,
        *,
        block_number: Optional[int],
        follow_proxy: bool,
    ) -> None:
        if not (self.use_binding_cache and follow_proxy and self.contract_repo):
            return
        if block_number is None:
            await self.contract_repo.save(metadata)
        else:
            await self.contract_repo.save_at_block(metadata, block_number)

    async def _read_code(
        self,
        chain_id: int,
        address: str,
        block: Optional[int],
    ) -> bytes:
        block_id = block if block is not None else "latest"
        try:
            code = await self.web3_provider.get_code(chain_id, address, block_id)
        except Exception as exc:
            raise RPCError("eth_getCode", str(exc)) from exc
        raw = bytes(code)
        return b"" if raw in {b"", b"0x"} else raw

    async def _check_is_contract(
        self, chain_id: int, address: str, block: Optional[int]
    ) -> bytes:
        """Check if address is a contract and return bytecode."""
        code = await self._read_code(chain_id, address, block)
        if not code:
            raise NotAContractError(address)

        return code

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
        4. ZeppelinOS and beacon slots
        5. Bytecode-advertised implementation getters
        """
        block_id = block if block is not None else "latest"

        if bytecode:
            implementation = self._detect_minimal_proxy(bytecode)
            if implementation and implementation != ZERO_ADDRESS:
                return ProxyInfo(
                    proxy_type="eip1167",
                    implementation_address=implementation,
                    admin_address=None,
                )

        impl_value, uups_value, zos_value, beacon_value = await asyncio.gather(
            self.web3_provider.get_storage_at(
                chain_id,
                address,
                EIP1967_IMPL_SLOT,
                block_id,
            ),
            self.web3_provider.get_storage_at(
                chain_id,
                address,
                EIP1822_SLOT,
                block_id,
            ),
            self.web3_provider.get_storage_at(
                chain_id,
                address,
                ZEPPELINOS_IMPL_SLOT,
                block_id,
            ),
            self.web3_provider.get_storage_at(
                chain_id,
                address,
                EIP1967_BEACON_SLOT,
                block_id,
            ),
        )

        implementation = self._extract_address(bytes(impl_value))
        if implementation and implementation != ZERO_ADDRESS:
            return ProxyInfo(
                proxy_type="eip1967",
                implementation_address=implementation,
                admin_address=None,
            )

        implementation = self._extract_address(bytes(uups_value))
        if implementation and implementation != ZERO_ADDRESS:
            return ProxyInfo(
                proxy_type="eip1822",
                implementation_address=implementation,
                admin_address=None,
            )

        implementation = self._extract_address(bytes(zos_value))
        if implementation and implementation != ZERO_ADDRESS:
            return ProxyInfo(
                proxy_type="zeppelinos",
                implementation_address=implementation,
                admin_address=None,
            )

        beacon_address = self._extract_address(bytes(beacon_value))
        if beacon_address and beacon_address != ZERO_ADDRESS:
            result = await self.web3_provider.eth_call(
                chain_id,
                {"to": beacon_address, "data": BEACON_IMPL_SELECTOR},
                block_id,
            )
            implementation = self._extract_address(bytes(result))
            if not implementation or implementation == ZERO_ADDRESS:
                raise RPCError(
                    "eth_call",
                    f"Beacon {beacon_address} returned no implementation",
                )
            return ProxyInfo(
                proxy_type="beacon",
                implementation_address=implementation,
                admin_address=None,
            )

        if bytecode and b"\xf4" in bytecode:
            callable_proxies = (
                ("aragon", BEACON_IMPL_SELECTOR),
                ("gnosis_safe", GNOSIS_SAFE_MASTER_COPY_SELECTOR),
            )
            for proxy_type, selector in callable_proxies:
                if bytes.fromhex(selector[2:]) not in bytecode:
                    continue
                result = await self.web3_provider.eth_call(
                    chain_id,
                    {"to": address, "data": selector},
                    block_id,
                )
                implementation = self._extract_address(bytes(result))
                if not implementation or implementation == ZERO_ADDRESS:
                    raise RPCError(
                        "eth_call",
                        f"{proxy_type} getter returned no implementation",
                    )
                return ProxyInfo(
                    proxy_type=proxy_type,
                    implementation_address=implementation,
                    admin_address=None,
                )

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
        merged_scopes = {
            scope.id: scope
            for scope in standard_layout.scopes + namespace_layout.scopes
        }

        return StorageLayout(
            contract_name=standard_layout.contract_name,
            variables=list({
                (variable.name, variable.slot, variable.offset, variable.type_id): variable
                for variable in merged_variables
            }.values()),
            types=merged_types,
            language=standard_layout.language or namespace_layout.language,
            compiler_version=(
                standard_layout.compiler_version or namespace_layout.compiler_version
            ),
            storage_scheme=(
                standard_layout.storage_scheme or namespace_layout.storage_scheme
            ),
            scopes=list(merged_scopes.values()),
        )
