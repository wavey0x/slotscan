"""Contract resolver for fetching metadata, proxy detection, and verification lookup."""

import asyncio
from dataclasses import dataclass
import json
import logging
import re
from typing import Optional

from web3 import Web3

from app.config import Settings
from app.models.domain import (
    ContractMetadata,
    ProxyInfo,
    RawCompilerArtifact,
    StorageLayout,
    VerificationResult,
)
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
EIP1967_IMPL_SLOT = (
    0x360894A13BA1A3210667C828492DB98DCA3E2076CC3735A920A3CA505D382BBC
)

# EIP-1822 UUPS Slot
EIP1822_SLOT = (
    0xC5F16F0FCC639FA48A6947836D9850F504798523BF8C9A3A87D5876CF622BCF7
)

# ZeppelinOS (pre-EIP-1967) Implementation Slot - keccak256("org.zeppelinos.proxy.implementation")
# Used by USDC and other older OpenZeppelin proxies
ZEPPELINOS_IMPL_SLOT = (
    0x7050C9E0F4CA769C69BD3A8EF740BC37934F8E2C036E5A723FD8EE048ED3F8C3
)

# EIP-1967 Beacon Slot - keccak256("eip1967.proxy.beacon") - 1
# Used by Euler EVK, OpenZeppelin BeaconProxy, and other upgradeable contracts
EIP1967_BEACON_SLOT = (
    0xA3F0AD74E5423AEFD80D3EF4346578335A9A72AEAEE59FF6CB3582B35133D50
)

# Standard beacon implementation() function selector
BEACON_IMPL_SELECTOR = "0x5c60da1b"

# ERC-897 proxyType() function selector
ERC897_PROXY_TYPE_SELECTOR = "0x4555d5c9"

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


@dataclass(frozen=True)
class _EquivalentLayout:
    source_address: str
    layout: StorageLayout
    verification: VerificationResult
    artifact: RawCompilerArtifact


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

        # Address caches may reuse a proven layout, but they do not establish
        # whether the current chain state is a proxy or which implementation it
        # targets.
        proxy_info = (
            await self.detect_proxy(chain_id, address, block_number, bytecode)
            if follow_proxy
            else None
        )

        # Source data is keyed by the runtime code that is actually verified,
        # not by the address whose storage is being interpreted. Resolve that
        # identity before consulting binding caches so cached layouts can be
        # recomposed with their separately persisted source payload.
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
                and self._cache_matches_proxy(
                    historical,
                    proxy_info,
                    follow_proxy=follow_proxy,
                )
                ):
                metadata = self.contract_repo.to_metadata(historical)
                if self._cached_layout_is_usable(metadata):
                    return await self._with_cached_sources(
                        metadata,
                        chain_id=chain_id,
                        code_address=code_address,
                        code_hash=verification_code_hash,
                    )

        if self.use_binding_cache and self.contract_repo and block_number is None:
            cached = await self.contract_repo.get(chain_id, address)
            if (
                cached
                and self._cache_matches_code_hash(cached, code_hash)
                and self._cache_matches_proxy(
                    cached,
                    proxy_info,
                    follow_proxy=follow_proxy,
                )
            ):
                logger.debug(f"Cache hit for {address} on chain {chain_id}")
                metadata = self.contract_repo.to_metadata(cached)
                if self._cached_layout_is_usable(metadata):
                    return await self._with_cached_sources(
                        metadata,
                        chain_id=chain_id,
                        code_address=code_address,
                        code_hash=verification_code_hash,
                    )

        parsed_layout = None
        compiler_artifact = None
        namespace_compiler_output = None
        exact_namespace_base = False

        language = "Solidity"
        verification = await self.verification_service.resolve(
            chain_id,
            code_address,
            verification_code_hash,
            self.source_cache_repo,
        )
        equivalent = None
        if verification is None:
            equivalent = await self._resolve_equivalent_layout(
                chain_id,
                verification_code_hash,
                verification_bytecode,
            )
            if equivalent:
                parsed_layout = equivalent.layout
                compiler_artifact = equivalent.artifact
        if verification:
            language = getattr(verification, "language", None) or "Solidity"
        elif equivalent:
            language = equivalent.verification.language or "Solidity"

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
                        compiler_artifact_repo=self.compiler_artifact_repo,
                    )
                )
                exact_namespace_base = True
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
                            compiler_artifact_repo=self.compiler_artifact_repo,
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
                            compiler_artifact_repo=self.compiler_artifact_repo,
                        )
                    )
                except Exception as e:
                    logger.warning(
                        "Exact Vyper layout unavailable for %s: %s",
                        verification.compiler_version,
                        e,
                    )
            elif not (parsed_layout and parsed_layout.variables):
                try:
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
        layout_identity = verification or (
            equivalent.verification if equivalent else None
        )
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
            name=layout_identity.name if layout_identity else None,
            compiler_version=(
                layout_identity.compiler_version if layout_identity else None
            ),
            compilation_target=(
                layout_identity.compilation_target if layout_identity else None
            ),
            sources=layout_identity.sources if layout_identity else None,
            compiler_settings=(
                layout_identity.compiler_settings if layout_identity else None
            ),
            storage_layout=parsed_layout,
            compiler_artifact_fingerprint=(
                compiler_artifact.fingerprint if compiler_artifact else None
            ),
            layout_provenance=(
                "bytecode_equivalent"
                if parsed_layout and equivalent
                else "verified_source"
                if parsed_layout and verification
                else None
            ),
            layout_source_address=(
                equivalent.source_address
                if parsed_layout and equivalent
                else code_address
                if parsed_layout and verification
                else None
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
            layout_provenance=delegate.layout_provenance if delegate else None,
            layout_source_address=(
                delegate.layout_source_address if delegate else None
            ),
        )

    async def _resolve_equivalent_layout(
        self,
        chain_id: int,
        code_hash: str,
        runtime_bytecode: bytes,
    ) -> _EquivalentLayout | None:
        candidate_lookup = getattr(
            self.contract_repo,
            "get_verified_layout_candidates",
            None,
        )
        if not candidate_lookup:
            return None
        candidates = await candidate_lookup(chain_id, code_hash)
        if not candidates or len(candidates) > 25:
            return None

        proofs: dict[tuple[str, str], _EquivalentLayout] = {}
        for candidate in candidates:
            proof = await self._prove_equivalent_candidate(
                chain_id,
                candidate,
                code_hash,
                runtime_bytecode,
            )
            if proof is None:
                continue
            identity = (
                proof.artifact.fingerprint,
                json.dumps(
                    proof.layout.to_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            proofs.setdefault(identity, proof)

        if len(proofs) != 1:
            if len(proofs) > 1:
                logger.warning(
                    "Rejecting ambiguous equivalent layouts for code hash %s",
                    code_hash,
                )
            return None
        return next(iter(proofs.values()))

    async def _prove_equivalent_candidate(
        self,
        chain_id: int,
        candidate,
        code_hash: str,
        runtime_bytecode: bytes,
    ) -> _EquivalentLayout | None:
        source_row = await self.source_cache_repo.get(
            chain_id,
            candidate.address,
            code_hash,
        )
        if (
            source_row is None
            or source_row.status != "verified"
            or not isinstance(source_row.result, dict)
        ):
            return None
        verification = VerificationResult.from_dict(source_row.result)
        if (
            verification.language not in {"Solidity", "Vyper"}
            or verification.match_type not in {"full", "exact_match"}
            or not verification.sources
            or not verification.compiler_version
        ):
            return None

        compilation_target = None
        entry_source = None
        if verification.compilation_target:
            if len(verification.compilation_target) != 1:
                return None
            target_path, target_name = next(
                iter(verification.compilation_target.items())
            )
            compilation_target = f"{target_path}:{target_name}"
            entry_source = target_path
        contract_name = verification.name or candidate.name
        if not contract_name:
            return None

        try:
            if verification.language == "Vyper":
                layout, artifact = (
                    await self.layout_parser.parse_vyper_with_artifact(
                        contract_name=contract_name,
                        sources=verification.sources,
                        compiler_version=verification.compiler_version,
                        entry_source=entry_source,
                        compiler_artifact_repo=self.compiler_artifact_repo,
                    )
                )
                if not self._vyper_artifact_matches_runtime(
                    artifact,
                    runtime_bytecode,
                ):
                    return None
            else:
                layout, artifact = await self.layout_parser.parse_with_artifact(
                    contract_name=contract_name,
                    sources=verification.sources,
                    compiler_version=verification.compiler_version,
                    compiler_settings=verification.compiler_settings,
                    metadata_settings=verification.compiler_settings,
                    contract_fqname=compilation_target,
                    compiler_artifact_repo=self.compiler_artifact_repo,
                )
                if not self._artifact_matches_runtime(
                    artifact,
                    verification,
                    runtime_bytecode,
                ):
                    return None
                layout.language = "Solidity"
                layout.compiler_version = verification.compiler_version
                layout.storage_scheme = "solidity"
                layout = self.namespace_parser.promote_exact_erc7201(
                    layout,
                    compiler_output=artifact.compiler_output,
                    sources=verification.sources,
                    compiler_version=verification.compiler_version,
                    max_slots=self.settings.max_slots_per_contract,
                )
            if not layout.variables or not self._layout_is_exact(layout):
                return None
        except Exception as exc:
            logger.info(
                "Equivalent layout proof unavailable for %s: %s",
                candidate.address,
                exc,
            )
            return None

        return _EquivalentLayout(
            source_address=Web3.to_checksum_address(candidate.address),
            layout=layout,
            verification=verification,
            artifact=artifact,
        )

    @staticmethod
    def _vyper_artifact_matches_runtime(
        artifact: RawCompilerArtifact,
        runtime_bytecode: bytes,
    ) -> bool:
        compiled = artifact.compiler_output.get("bytecodeRuntime")
        if not isinstance(compiled, str):
            return False
        clean = compiled.removeprefix("0x")
        return (
            len(clean) % 2 == 0
            and bool(re.fullmatch(r"[0-9a-fA-F]*", clean))
            and bytes.fromhex(clean) == runtime_bytecode
        )

    @staticmethod
    def _layout_is_exact(layout: StorageLayout) -> bool:
        return all(
            variable.provenance == "compiler_layout"
            and variable.confidence == "exact"
            for variable in layout.variables
        ) and all(
            scope.kind in {"default", "erc7201"}
            and scope.provenance == "compiler_layout"
            and scope.confidence == "exact"
            for scope in layout.scopes
        )

    @classmethod
    def _artifact_matches_runtime(
        cls,
        artifact: RawCompilerArtifact,
        verification: VerificationResult,
        runtime_bytecode: bytes,
    ) -> bool:
        contract_output = cls._artifact_contract_output(
            artifact,
            verification,
        )
        deployed = (
            contract_output.get("evm", {}).get("deployedBytecode", {})
            if contract_output
            else {}
        )
        compiled_hex = str(deployed.get("object") or "").removeprefix("0x")
        runtime_hex = runtime_bytecode.hex()
        if not compiled_hex or len(compiled_hex) != len(runtime_hex):
            return False

        if len(runtime_bytecode) < 2:
            return False
        metadata_length = int.from_bytes(runtime_bytecode[-2:], "big")
        metadata_start = len(runtime_bytecode) - metadata_length - 2
        if metadata_length <= 0 or metadata_start < 0:
            return False
        metadata = runtime_bytecode[metadata_start:-2]
        if not any(marker in metadata for marker in (b"ipfs", b"bzzr")):
            return False

        ignored_ranges = cls._deployed_bytecode_ranges(deployed)
        ignored_offsets: set[int] = set()
        for start, length in ignored_ranges:
            end = start + length
            if start < 0 or length <= 0 or end > metadata_start:
                return False
            ignored_offsets.update(range(start, end))

        for offset in range(len(runtime_bytecode)):
            if offset in ignored_offsets:
                continue
            compiled_byte = compiled_hex[offset * 2: offset * 2 + 2]
            if (
                len(compiled_byte) != 2
                or any(character not in "0123456789abcdefABCDEF" for character in compiled_byte)
                or compiled_byte.lower() != runtime_hex[offset * 2: offset * 2 + 2]
            ):
                return False
        return True

    @staticmethod
    def _artifact_contract_output(
        artifact: RawCompilerArtifact,
        verification: VerificationResult,
    ) -> dict | None:
        contracts = artifact.compiler_output.get("contracts", {})
        if verification.compilation_target:
            if len(verification.compilation_target) != 1:
                return None
            filename, name = next(iter(verification.compilation_target.items()))
            output = contracts.get(filename, {}).get(name)
            return output if isinstance(output, dict) else None

        matches = [
            output
            for source_contracts in contracts.values()
            for name, output in source_contracts.items()
            if name == verification.name and isinstance(output, dict)
        ]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _deployed_bytecode_ranges(deployed: dict) -> tuple[tuple[int, int], ...]:
        ranges = []
        for references in deployed.get("immutableReferences", {}).values():
            ranges.extend(
                (int(reference["start"]), int(reference["length"]))
                for reference in references
            )
        for source_references in deployed.get("linkReferences", {}).values():
            for references in source_references.values():
                ranges.extend(
                    (int(reference["start"]), int(reference["length"]))
                    for reference in references
                )
        return tuple(ranges)

    @staticmethod
    def _cached_layout_is_usable(metadata: ContractMetadata) -> bool:
        layout = metadata.storage_layout
        if not isinstance(layout, StorageLayout) or not layout.variables:
            return False
        if (layout.language or "").lower() != "vyper":
            return True
        policy = vyper_storage_policy(
            layout.compiler_version or metadata.compiler_version
        )
        return (
            not policy.compiler_layout_supported
            or bool(metadata.compiler_artifact_fingerprint)
        )

    async def _with_cached_sources(
        self,
        metadata: ContractMetadata,
        *,
        chain_id: int,
        code_address: str,
        code_hash: str,
    ) -> ContractMetadata:
        """Recompose a cached layout binding with its source-cache payload."""
        source_address = metadata.layout_source_address or code_address
        try:
            verification = await self.verification_service.resolve(
                chain_id,
                source_address,
                code_hash,
                self.source_cache_repo,
            )
        except Exception:
            logger.warning(
                "Cached source hydration failed for %s",
                source_address,
            )
            return metadata
        if verification is None:
            return metadata
        metadata.compilation_target = verification.compilation_target
        metadata.sources = verification.sources
        metadata.compiler_settings = verification.compiler_settings
        return metadata

    @staticmethod
    def _cache_matches_code_hash(row, code_hash: str) -> bool:
        cached_hash = getattr(row, "code_hash", None)
        return bool(cached_hash) and cached_hash.lower() == code_hash.lower()

    @staticmethod
    def _cache_matches_proxy(
        row,
        proxy_info: ProxyInfo | None,
        *,
        follow_proxy: bool,
    ) -> bool:
        """Require cached layout identity to match fresh proxy evidence."""
        cached_is_proxy = bool(getattr(row, "is_proxy", False))
        if not follow_proxy:
            return not cached_is_proxy
        if proxy_info is None:
            return not cached_is_proxy
        cached_implementation = getattr(row, "implementation_address", None)
        return (
            cached_is_proxy
            and getattr(row, "proxy_type", None) == proxy_info.proxy_type
            and bool(cached_implementation)
            and cached_implementation.lower()
            == proxy_info.implementation_address.lower()
        )

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
        # The first 45 bytes prove the canonical EIP-1167 control flow.
        # Trailing bytes are unreachable by that runtime and are commonly used
        # for immutable clone arguments.
        if (
            len(bytecode) >= 45
            and bytecode[:10] == EIP1167_PREFIX
            and bytecode[30:45] == EIP1167_SUFFIX
        ):
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
        """Resolve canonical proxy relationships at one chain state."""
        block_id = block if block is not None else "latest"
        proxy_address = Web3.to_checksum_address(address)

        if bytecode:
            implementation = self._detect_minimal_proxy(bytecode)
            if implementation and await self._is_valid_proxy_target(
                chain_id,
                proxy_address,
                implementation,
                block,
            ):
                return ProxyInfo(
                    proxy_type="eip1167",
                    implementation_address=implementation,
                    admin_address=None,
                )

        if not bytecode or not self._contains_opcode(bytecode, 0xF4):
            return None

        safe_candidate = self._contains_selector(
            bytecode,
            GNOSIS_SAFE_MASTER_COPY_SELECTOR,
        )
        evidence_slots = [
            EIP1967_IMPL_SLOT,
            EIP1822_SLOT,
            ZEPPELINOS_IMPL_SLOT,
            EIP1967_BEACON_SLOT,
        ]
        if safe_candidate:
            evidence_slots.append(0)
        storage_read = self.web3_provider.get_storage_values(
            chain_id,
            proxy_address,
            evidence_slots,
            block_id,
        )
        try:
            if safe_candidate:
                storage_values, safe_getter_implementation = await asyncio.gather(
                    storage_read,
                    self._call_address_getter(
                        chain_id,
                        proxy_address,
                        GNOSIS_SAFE_MASTER_COPY_SELECTOR,
                        block_id,
                    ),
                )
            else:
                storage_values = await storage_read
                safe_getter_implementation = None
        except Exception as exc:
            raise RPCError("eth_getStorageValues", str(exc)) from exc

        try:
            slot_values = {
                slot: bytes.fromhex(value[2:])
                for slot, value in storage_values.items()
            }
        except (AttributeError, ValueError) as exc:
            raise RPCError(
                "eth_getStorageValues",
                "Storage response contained an invalid hexadecimal word",
            ) from exc
        if set(slot_values) != set(evidence_slots):
            raise RPCError(
                "eth_getStorageValues",
                "Storage response omitted proxy evidence",
            )

        safe_slot_implementation = None
        if safe_candidate:
            safe_slot_implementation = self._extract_address(slot_values[0])

        for proxy_type, slot in (
            ("eip1967", EIP1967_IMPL_SLOT),
            ("eip1822", EIP1822_SLOT),
            ("zeppelinos", ZEPPELINOS_IMPL_SLOT),
        ):
            implementation = self._extract_address(slot_values[slot])
            if implementation and await self._is_valid_proxy_target(
                chain_id,
                proxy_address,
                implementation,
                block,
            ):
                return ProxyInfo(
                    proxy_type=proxy_type,
                    implementation_address=implementation,
                    admin_address=None,
                )

        beacon_address = self._extract_address(slot_values[EIP1967_BEACON_SLOT])
        if beacon_address and await self._is_valid_proxy_target(
            chain_id,
            proxy_address,
            beacon_address,
            block,
        ):
            try:
                result = await self.web3_provider.eth_call(
                    chain_id,
                    {"to": beacon_address, "data": BEACON_IMPL_SELECTOR},
                    block_id,
                )
            except Exception as exc:
                raise RPCError("eth_call", str(exc)) from exc
            implementation = self._extract_address(bytes(result))
            if implementation and await self._is_valid_proxy_target(
                chain_id,
                proxy_address,
                implementation,
                block,
            ):
                return ProxyInfo(
                    proxy_type="beacon",
                    implementation_address=implementation,
                    admin_address=None,
                )

        # Safe's proxy-owned masterCopy() branch returns the singleton in slot
        # zero. The selector literal is only a cheap prefilter; matching the
        # getter and slot at the same block is the proxy proof.
        if (
            safe_slot_implementation
            and safe_getter_implementation
            and safe_slot_implementation.lower()
            == safe_getter_implementation.lower()
            and await self._is_valid_proxy_target(
                chain_id,
                proxy_address,
                safe_slot_implementation,
                block,
            )
        ):
            return ProxyInfo(
                proxy_type="gnosis_safe",
                implementation_address=safe_slot_implementation,
                admin_address=None,
            )

        # Aragon AppProxy and other ERC-897 proxies advertise both methods.
        # The proxyType() check distinguishes the standard from unrelated
        # contracts that happen to expose an implementation() getter.
        if (
            self._contains_selector(bytecode, BEACON_IMPL_SELECTOR)
            and self._contains_selector(bytecode, ERC897_PROXY_TYPE_SELECTOR)
        ):
            implementation, proxy_type_value = await asyncio.gather(
                self._call_address_getter(
                    chain_id,
                    proxy_address,
                    BEACON_IMPL_SELECTOR,
                    block_id,
                ),
                self._call_uint256_getter(
                    chain_id,
                    proxy_address,
                    ERC897_PROXY_TYPE_SELECTOR,
                    block_id,
                ),
            )
            if (
                proxy_type_value in {1, 2}
                and implementation
                and await self._is_valid_proxy_target(
                    chain_id,
                    proxy_address,
                    implementation,
                    block,
                )
            ):
                return ProxyInfo(
                    proxy_type="erc897",
                    implementation_address=implementation,
                    admin_address=None,
                )
        return None

    async def _is_valid_proxy_target(
        self,
        chain_id: int,
        proxy_address: str,
        target_address: str,
        block: Optional[int],
    ) -> bool:
        if target_address.lower() in {
            ZERO_ADDRESS.lower(),
            proxy_address.lower(),
        }:
            return False
        return bool(await self._read_code(chain_id, target_address, block))

    @staticmethod
    def _contains_opcode(bytecode: bytes, target: int) -> bool:
        """Find an opcode without treating PUSH data as executable code."""
        offset = 0
        while offset < len(bytecode):
            opcode = bytecode[offset]
            if opcode == target:
                return True
            if 0x60 <= opcode <= 0x7F:
                offset += 1 + opcode - 0x5F
            else:
                offset += 1
        return False

    @staticmethod
    def _contains_selector(bytecode: bytes, selector: str) -> bool:
        """Use a selector literal as a non-evidentiary probing prefilter."""
        target = bytes.fromhex(selector.removeprefix("0x"))
        return target in bytecode

    async def _call_address_getter(
        self,
        chain_id: int,
        address: str,
        selector: str,
        block_id: int | str,
    ) -> str | None:
        try:
            result = await self.web3_provider.eth_call(
                chain_id,
                {"to": address, "data": selector},
                block_id,
            )
        except Exception as exc:
            logger.info("Proxy getter %s failed for %s: %s", selector, address, exc)
            return None
        return self._extract_address(bytes(result))

    async def _call_uint256_getter(
        self,
        chain_id: int,
        address: str,
        selector: str,
        block_id: int | str,
    ) -> int | None:
        try:
            result = bytes(
                await self.web3_provider.eth_call(
                    chain_id,
                    {"to": address, "data": selector},
                    block_id,
                )
            )
        except Exception as exc:
            logger.info("Proxy getter %s failed for %s: %s", selector, address, exc)
            return None
        return int.from_bytes(result, "big") if len(result) == 32 else None

    def _extract_address(self, slot_value: bytes) -> Optional[str]:
        """Extract address from 32-byte slot value (last 20 bytes)."""
        if len(slot_value) != 32 or slot_value[:12] != bytes(12):
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
