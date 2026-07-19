import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

from web3 import Web3

from app.config import Settings
from app.models.domain import (
    ContractMetadata,
    RawCompilerArtifact,
    StorageLayout,
    StorageType,
    StorageVariable,
    VerificationResult,
)
from app.services.decoder import TypeDecoder
from app.services.layout import LayoutParser
from app.services.resolver import (
    EIP1167_PREFIX,
    EIP1167_SUFFIX,
    EIP1967_BEACON_SLOT,
    EIP1967_IMPL_SLOT,
    GNOSIS_SAFE_MASTER_COPY_SELECTOR,
    ContractResolver,
)
from app.services.storage_view import StorageViewService
from app.services.transaction_history import TransactionHistoryService
from app.services.verification import VerificationService


DIRECT = Web3.to_checksum_address("0x" + "10" * 20)
DIRECT_B = Web3.to_checksum_address("0x" + "14" * 20)
PROXY_A = Web3.to_checksum_address("0x" + "11" * 20)
PROXY_B = Web3.to_checksum_address("0x" + "12" * 20)
IMPLEMENTATION_A = Web3.to_checksum_address("0x" + "21" * 20)
IMPLEMENTATION_B = Web3.to_checksum_address("0x" + "22" * 20)
BEACON = Web3.to_checksum_address("0x" + "31" * 20)
AUTHORITY_A = Web3.to_checksum_address("0x" + "41" * 20)
AUTHORITY_B = Web3.to_checksum_address("0x" + "42" * 20)


def _address_word(address):
    return bytes(12) + bytes.fromhex(address[2:])


def _designator(address):
    return bytes.fromhex("ef0100") + bytes.fromhex(address[2:])


def _verification(name):
    return VerificationResult(
        source="sourcify",
        match_type="full",
        name=name,
        compiler_version="0.8.30",
        storage_layout={"storage": [], "types": {}},
    )


def _verification_with_layout(name, type_label):
    type_id = f"t_{type_label}"
    return VerificationResult(
        source="sourcify",
        match_type="full",
        name=name,
        compiler_version="0.8.30",
        storage_layout={
            "storage": [
                {
                    "astId": 1,
                    "contract": name,
                    "label": "value",
                    "offset": 0,
                    "slot": "0",
                    "type": type_id,
                }
            ],
            "types": {
                type_id: {
                    "encoding": "inplace",
                    "label": type_label,
                    "numberOfBytes": "32",
                }
            },
        },
    )


class _MemorySourceCache:
    def __init__(self):
        self.rows = {}

    @staticmethod
    def _key(chain_id, code_address, code_hash):
        return chain_id, code_address.lower(), code_hash.lower()

    async def get(self, chain_id, code_address, code_hash):
        return self.rows.get(self._key(chain_id, code_address, code_hash))

    async def save_verified(
        self,
        chain_id,
        code_address,
        code_hash,
        result,
    ):
        self.rows[self._key(chain_id, code_address, code_hash)] = SimpleNamespace(
            status="verified",
            result=result.to_dict(),
            checked_at=datetime.utcnow(),
        )

    async def save_not_found(self, chain_id, code_address, code_hash):
        self.rows[self._key(chain_id, code_address, code_hash)] = SimpleNamespace(
            status="not_found",
            result=None,
            checked_at=datetime.utcnow(),
        )


class _NoBindings:
    async def get(self, chain_id, address):
        return None

    async def get_at_block(self, chain_id, address, block_number):
        return None

    async def save(self, metadata):
        return None

    async def save_at_block(self, metadata, block_number):
        return None


class _MemoryBindings(_NoBindings):
    def __init__(self):
        self.rows = {}

    async def get(self, chain_id, address):
        return self.rows.get((chain_id, address.lower()))

    async def save(self, metadata):
        values = dict(metadata.__dict__)
        values["storage_layout"] = (
            metadata.storage_layout.to_dict()
            if metadata.storage_layout
            else None
        )
        row = SimpleNamespace(**values)
        self.rows[(metadata.chain_id, metadata.address.lower())] = row
        return row

    async def get_verified_layout_candidates(
        self,
        chain_id,
        code_hash,
        *,
        limit=26,
    ):
        return [
            row
            for (row_chain_id, _), row in sorted(self.rows.items())
            if row_chain_id == chain_id
            and row.code_hash.lower() == code_hash.lower()
            and row.is_verified
            and not row.is_proxy
            and row.storage_layout
        ][:limit]


class _CachedBindings(_NoBindings):
    def __init__(self, row, metadata):
        self.row = row
        self.metadata = metadata
        self.saved = []

    async def get(self, chain_id, address):
        return self.row

    async def get_at_block(self, chain_id, address, block_number):
        return self.row

    def to_metadata(self, row):
        return self.metadata

    async def save(self, metadata):
        self.saved.append(metadata)
        return self.row

    async def save_at_block(self, metadata, block_number):
        self.saved.append(metadata)
        return self.row


class _Provider:
    def __init__(
        self,
        *,
        codes=None,
        implementations=None,
        beacons=None,
        beacon_implementations=None,
    ):
        self.codes = codes or {}
        self.implementations = implementations or {}
        self.beacons = beacons or {}
        self.beacon_implementations = beacon_implementations or {}
        self.code_calls = []
        self.storage_calls = []

    @staticmethod
    def _at_block(values, address, block):
        value = values.get(address.lower())
        if isinstance(value, dict):
            return value.get(block)
        return value

    async def get_code(self, chain_id, address, block):
        self.code_calls.append((address.lower(), block))
        value = self.codes.get(address.lower(), b"")
        if isinstance(value, dict):
            return value.get(block, b"")
        return value

    async def get_storage_values(self, chain_id, address, slots, block):
        values = {}
        for slot in slots:
            self.storage_calls.append((address.lower(), slot, block))
            value = bytes(32)
            if slot == EIP1967_IMPL_SLOT:
                implementation = self._at_block(
                    self.implementations,
                    address,
                    block,
                )
                if implementation:
                    value = _address_word(implementation)
            elif slot == EIP1967_BEACON_SLOT:
                beacon = self._at_block(self.beacons, address, block)
                if beacon:
                    value = _address_word(beacon)
            values[slot] = "0x" + value.hex()
        return values

    async def eth_call(self, chain_id, transaction, block):
        implementation = self._at_block(
            self.beacon_implementations,
            transaction["to"],
            block,
        )
        return _address_word(implementation) if implementation else bytes(32)


class _SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def _service():
    service = VerificationService(Settings(), http_client=object())

    async def fetch(chain_id, address):
        return _verification(address.lower())

    service._fetch_verification = AsyncMock(side_effect=fetch)
    return service


def _resolver(
    provider,
    service,
    cache,
    *,
    bindings=None,
    use_binding_cache=True,
):
    return ContractResolver(
        web3_provider=provider,
        settings=Settings(),
        verification_service=service,
        source_cache_repo=cache,
        contract_repo=bindings or _NoBindings(),
        layout_parser=LayoutParser(),
        use_binding_cache=use_binding_cache,
    )


class ResolverSourceIdentityTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _equivalence_fixture(runtime):
        verification = VerificationResult(
            source="sourcify",
            match_type="exact_match",
            name="Equivalent",
            compilation_target={"Equivalent.sol": "Equivalent"},
            compiler_version="0.8.30",
            compiler_settings={"optimizer": {"enabled": False}},
            sources={
                "Equivalent.sol": (
                    "contract Equivalent { uint256 public value; }"
                )
            },
            language="Solidity",
        )
        value_type = StorageType(
            "t_uint256",
            "uint256",
            "value",
            "inplace",
            32,
        )
        layout = StorageLayout(
            "Equivalent",
            [
                StorageVariable(
                    "value",
                    0,
                    0,
                    32,
                    value_type.id,
                    value_type.label,
                )
            ],
            {value_type.id: value_type},
        )
        artifact = RawCompilerArtifact(
            fingerprint="ab" * 32,
            language="Solidity",
            compiler_version="0.8.30",
            pipeline="solc-standard-json",
            standard_input={},
            compiler_output={
                "contracts": {
                    "Equivalent.sol": {
                        "Equivalent": {
                            "evm": {
                                "deployedBytecode": {
                                    "object": runtime.hex(),
                                    "immutableReferences": {},
                                    "linkReferences": {},
                                }
                            },
                            "storageLayout": layout.to_dict(),
                        }
                    }
                }
            },
            source_hashes={},
        )
        return verification, layout, artifact

    @staticmethod
    def _vyper_equivalence_fixture(runtime):
        verification = VerificationResult(
            source="sourcify",
            match_type="exact_match",
            name="Equivalent",
            compilation_target={"Equivalent.vy": "Equivalent"},
            compiler_version="0.3.10",
            compiler_settings={},
            sources={
                "Equivalent.vy": (
                    "# @version 0.3.10\nvalue: public(uint256)\n"
                )
            },
            language="Vyper",
        )
        value_type = StorageType(
            "uint256",
            "uint256",
            "value",
            "inplace",
            32,
        )
        layout = StorageLayout(
            "Equivalent",
            [
                StorageVariable(
                    "value",
                    0,
                    0,
                    32,
                    value_type.id,
                    value_type.label,
                )
            ],
            {value_type.id: value_type},
            language="Vyper",
            compiler_version="0.3.10",
            storage_scheme="sequential",
        )
        artifact = RawCompilerArtifact(
            fingerprint="cd" * 32,
            language="Vyper",
            compiler_version="0.3.10",
            pipeline="vvm-layout",
            standard_input={},
            compiler_output={
                "storageLayout": layout.to_dict(),
                "bytecodeRuntime": "0x" + runtime.hex(),
            },
            source_hashes={},
        )
        return verification, layout, artifact

    async def test_unverified_duplicate_reuses_only_compiler_proven_layout(self):
        source = Web3.to_checksum_address("0x" + "15" * 20)
        metadata = b"\xa1\x64ipfs\x41\x01"
        runtime = b"\x60\x00" + metadata + len(metadata).to_bytes(2, "big")
        code_hash = Web3.keccak(runtime).hex()
        verification, layout, artifact = self._equivalence_fixture(runtime)
        cache = _MemorySourceCache()
        await cache.save_verified(1, source, code_hash, verification)
        bindings = _MemoryBindings()
        bindings.rows[(1, source.lower())] = SimpleNamespace(
            address=source.lower(),
            code_hash=code_hash,
            is_verified=True,
            is_proxy=False,
            storage_layout=layout.to_dict(),
            name="Equivalent",
        )
        provider = _Provider(codes={DIRECT.lower(): runtime})
        service = VerificationService(Settings(), http_client=object())
        service._fetch_verification = AsyncMock(return_value=None)
        parser = LayoutParser()
        parser.parse_with_artifact = AsyncMock(
            return_value=(layout, artifact)
        )
        resolver = ContractResolver(
            web3_provider=provider,
            settings=Settings(),
            verification_service=service,
            source_cache_repo=cache,
            contract_repo=bindings,
            layout_parser=parser,
        )

        result = await resolver.resolve(1, DIRECT)

        self.assertFalse(result.is_verified)
        self.assertEqual(result.layout_provenance, "bytecode_equivalent")
        self.assertEqual(result.layout_source_address, source)
        self.assertEqual(result.name, "Equivalent")
        self.assertEqual(result.storage_layout.to_dict(), layout.to_dict())
        self.assertEqual(
            result.compiler_artifact_fingerprint,
            artifact.fingerprint,
        )

    async def test_metadata_free_duplicate_remains_unresolved(self):
        source = Web3.to_checksum_address("0x" + "15" * 20)
        runtime = b"\x60\x00"
        code_hash = Web3.keccak(runtime).hex()
        verification, layout, artifact = self._equivalence_fixture(runtime)
        cache = _MemorySourceCache()
        await cache.save_verified(1, source, code_hash, verification)
        bindings = _MemoryBindings()
        bindings.rows[(1, source.lower())] = SimpleNamespace(
            address=source.lower(),
            code_hash=code_hash,
            is_verified=True,
            is_proxy=False,
            storage_layout=layout.to_dict(),
            name="Equivalent",
        )
        service = VerificationService(Settings(), http_client=object())
        service._fetch_verification = AsyncMock(return_value=None)
        parser = LayoutParser()
        parser.parse_with_artifact = AsyncMock(
            return_value=(layout, artifact)
        )
        resolver = ContractResolver(
            web3_provider=_Provider(codes={DIRECT.lower(): runtime}),
            settings=Settings(),
            verification_service=service,
            source_cache_repo=cache,
            contract_repo=bindings,
            layout_parser=parser,
        )

        result = await resolver.resolve(1, DIRECT)

        self.assertIsNone(result.storage_layout)
        self.assertIsNone(result.layout_provenance)
        self.assertIsNone(result.layout_source_address)

    async def test_unverified_vyper_duplicate_requires_exact_compiled_runtime(self):
        source = Web3.to_checksum_address("0x" + "15" * 20)
        runtime = b"\x5f\x5f\xfd"
        code_hash = Web3.keccak(runtime).hex()
        verification, layout, artifact = self._vyper_equivalence_fixture(runtime)
        cache = _MemorySourceCache()
        await cache.save_verified(1, source, code_hash, verification)
        bindings = _MemoryBindings()
        bindings.rows[(1, source.lower())] = SimpleNamespace(
            address=source.lower(),
            code_hash=code_hash,
            is_verified=True,
            is_proxy=False,
            storage_layout=layout.to_dict(),
            name="Equivalent",
        )
        service = VerificationService(Settings(), http_client=object())
        service._fetch_verification = AsyncMock(return_value=None)
        parser = LayoutParser()
        parser.parse_vyper_with_artifact = AsyncMock(
            return_value=(layout, artifact)
        )
        resolver = ContractResolver(
            web3_provider=_Provider(codes={DIRECT.lower(): runtime}),
            settings=Settings(),
            verification_service=service,
            source_cache_repo=cache,
            contract_repo=bindings,
            layout_parser=parser,
        )

        result = await resolver.resolve(1, DIRECT)

        self.assertFalse(result.is_verified)
        self.assertEqual(result.layout_provenance, "bytecode_equivalent")
        self.assertEqual(result.layout_source_address, source)
        self.assertEqual(result.storage_layout.to_dict(), layout.to_dict())
        parser.parse_vyper_with_artifact.assert_awaited_once_with(
            contract_name="Equivalent",
            sources=verification.sources,
            compiler_version="0.3.10",
            entry_source="Equivalent.vy",
        )

    async def test_vyper_duplicate_rejects_runtime_mismatch(self):
        source = Web3.to_checksum_address("0x" + "15" * 20)
        runtime = b"\x5f\x5f\xfd"
        code_hash = Web3.keccak(runtime).hex()
        verification, layout, artifact = self._vyper_equivalence_fixture(
            b"\x60\x00\xfd"
        )
        cache = _MemorySourceCache()
        await cache.save_verified(1, source, code_hash, verification)
        bindings = _MemoryBindings()
        bindings.rows[(1, source.lower())] = SimpleNamespace(
            address=source.lower(),
            code_hash=code_hash,
            is_verified=True,
            is_proxy=False,
            storage_layout=layout.to_dict(),
            name="Equivalent",
        )
        service = VerificationService(Settings(), http_client=object())
        service._fetch_verification = AsyncMock(return_value=None)
        parser = LayoutParser()
        parser.parse_vyper_with_artifact = AsyncMock(
            return_value=(layout, artifact)
        )
        resolver = ContractResolver(
            web3_provider=_Provider(codes={DIRECT.lower(): runtime}),
            settings=Settings(),
            verification_service=service,
            source_cache_repo=cache,
            contract_repo=bindings,
            layout_parser=parser,
        )

        result = await resolver.resolve(1, DIRECT)

        self.assertIsNone(result.storage_layout)
        self.assertIsNone(result.layout_provenance)

    async def test_identical_bytecode_does_not_share_layouts_across_addresses(self):
        provider = _Provider(
            codes={
                DIRECT.lower(): b"\x60\x00",
                DIRECT_B.lower(): b"\x60\x00",
            }
        )
        service = VerificationService(Settings(), http_client=object())

        async def fetch(chain_id, address):
            type_label = "uint256" if address == DIRECT.lower() else "address"
            return _verification_with_layout(address, type_label)

        service._fetch_verification = AsyncMock(side_effect=fetch)
        resolver = _resolver(
            provider,
            service,
            _MemorySourceCache(),
            bindings=_MemoryBindings(),
        )

        first = await resolver.resolve(1, DIRECT)
        second = await resolver.resolve(1, DIRECT_B)

        self.assertEqual(first.name, DIRECT.lower())
        self.assertEqual(second.name, DIRECT_B.lower())
        self.assertEqual(
            first.storage_layout.get_type("t_uint256").label,
            "uint256",
        )
        self.assertEqual(
            second.storage_layout.get_type("t_address").label,
            "address",
        )
        self.assertEqual(
            service._fetch_verification.await_args_list,
            [
                call(1, DIRECT.lower()),
                call(1, DIRECT_B.lower()),
            ],
        )

    async def test_direct_contract_is_reused_across_historical_blocks(self):
        provider = _Provider(codes={DIRECT.lower(): b"\x60\x00"})
        service = _service()
        cache = _MemorySourceCache()
        resolver = _resolver(provider, service, cache)

        first = await resolver.resolve(1, DIRECT, block_number=100)
        second = await resolver.resolve(1, DIRECT, block_number=200)

        self.assertEqual(first.name, second.name)
        service._fetch_verification.assert_awaited_once_with(1, DIRECT.lower())

    async def test_storage_view_and_transaction_history_share_source_entries(self):
        provider = _Provider(codes={DIRECT.lower(): b"\x60\x00"})
        service = _service()
        cache = _MemorySourceCache()
        base_resolver = _resolver(provider, service, cache)
        storage_view = StorageViewService(
            web3_provider=provider,
            resolver=base_resolver,
            layout_parser=base_resolver.layout_parser,
            settings=Settings(),
            decoder=TypeDecoder(),
        )

        storage_resolver = storage_view._attempt_resolver(provider)
        await storage_resolver.resolve(1, DIRECT, block_number=100)

        history = TransactionHistoryService(
            tracer=None,
            web3_provider=provider,
            settings=Settings(),
            layout_parser=base_resolver.layout_parser,
            verification_service=service,
        )
        with (
            patch(
                "app.services.transaction_history.async_session_factory",
                return_value=_SessionContext(),
            ),
            patch(
                "app.services.transaction_history.SourceCacheRepository",
                return_value=cache,
            ),
            patch(
                "app.services.transaction_history.ContractRepository",
                return_value=_NoBindings(),
            ),
            patch(
                "app.services.transaction_history.CompilerArtifactRepository",
                return_value=None,
            ),
        ):
            await history._resolve_metadata(1, DIRECT, 200)

        service._fetch_verification.assert_awaited_once_with(1, DIRECT.lower())

    async def test_proxy_slot_values_do_not_cross_source_identities(self):
        provider = _Provider(
            codes={
                PROXY_A.lower(): b"\x60\x01",
                PROXY_B.lower(): b"\x60\x02",
                IMPLEMENTATION_A.lower(): b"\x60\xaa",
                IMPLEMENTATION_B.lower(): b"\x60\xbb",
            },
            implementations={
                PROXY_A.lower(): {
                    100: IMPLEMENTATION_A,
                    200: IMPLEMENTATION_B,
                },
                PROXY_B.lower(): IMPLEMENTATION_A,
            },
        )
        service = _service()
        resolver = _resolver(provider, service, _MemorySourceCache())

        first = await resolver.resolve(1, PROXY_A, block_number=100)
        second = await resolver.resolve(1, PROXY_B, block_number=100)
        unchanged = await resolver.resolve(1, PROXY_A, block_number=200)

        self.assertFalse(first.is_proxy)
        self.assertFalse(second.is_proxy)
        self.assertIsNone(unchanged.implementation_address)
        self.assertEqual(
            service._fetch_verification.await_args_list,
            [
                call(1, PROXY_A.lower()),
                call(1, PROXY_B.lower()),
            ],
        )
        self.assertEqual(provider.storage_calls, [])

    async def test_canonical_minimal_proxy_allows_trailing_immutable_arguments(self):
        clone = Web3.to_checksum_address("0x" + "13" * 20)
        clone_with_args = Web3.to_checksum_address("0x" + "16" * 20)
        clone_code = (
            EIP1167_PREFIX
            + bytes.fromhex(IMPLEMENTATION_A[2:])
            + EIP1167_SUFFIX
        )
        provider = _Provider(
            codes={
                PROXY_A.lower(): b"\x60\x01",
                clone.lower(): clone_code,
                clone_with_args.lower(): clone_code + b"immutable arguments",
                IMPLEMENTATION_A.lower(): b"\x60\xaa",
            },
            beacons={PROXY_A.lower(): BEACON},
            beacon_implementations={BEACON.lower(): IMPLEMENTATION_A},
        )
        service = _service()
        resolver = _resolver(provider, service, _MemorySourceCache())

        beacon_like = await resolver.resolve(1, PROXY_A, block_number=100)
        minimal = await resolver.resolve(1, clone, block_number=100)
        with_args = await resolver.resolve(
            1,
            clone_with_args,
            block_number=100,
        )

        self.assertFalse(beacon_like.is_proxy)
        self.assertIsNone(beacon_like.implementation_address)
        self.assertEqual(minimal.implementation_address, IMPLEMENTATION_A)
        self.assertEqual(with_args.implementation_address, IMPLEMENTATION_A)
        self.assertEqual(
            service._fetch_verification.await_args_list,
            [
                call(1, PROXY_A.lower()),
                call(1, IMPLEMENTATION_A.lower()),
            ],
        )
        self.assertEqual(provider.storage_calls, [])

    def test_minimal_proxy_rejects_changes_inside_the_executable_core(self):
        resolver = _resolver(
            _Provider(),
            _service(),
            _MemorySourceCache(),
        )
        mutated = (
            EIP1167_PREFIX
            + bytes.fromhex(IMPLEMENTATION_A[2:])
            + b"\x00"
            + EIP1167_SUFFIX
        )

        self.assertIsNone(resolver._detect_minimal_proxy(mutated))

    async def test_proxy_slot_signal_does_not_suppress_source_lookup(self):
        provider = _Provider(
            codes={PROXY_A.lower(): b"\x60\x01"},
            implementations={PROXY_A.lower(): IMPLEMENTATION_A},
        )
        service = _service()
        resolver = _resolver(provider, service, _MemorySourceCache())

        result = await resolver.resolve(1, PROXY_A, block_number=100)

        self.assertFalse(result.is_proxy)
        self.assertIsNone(result.implementation_address)
        self.assertTrue(result.is_verified)
        service._fetch_verification.assert_awaited_once_with(1, PROXY_A.lower())
        self.assertEqual(provider.storage_calls, [])

    async def test_fresh_safe_evidence_replaces_stale_direct_binding(self):
        runtime = bytes.fromhex(
            "608060405273ffffffffffffffffffffffffffffffffffffffff600054167f"
            "a619486e00000000000000000000000000000000000000000000000000000000"
            "60003514156050578060005260206000f35b3660008037600080366000845af4"
            "3d6000803e60008114156070573d6000fd5b3d6000f3fea26469706673582212"
            "20d1429297349653a4918076d650332de1a1068c5f3e07c5c82360c277770b9"
            "55264736f6c63430007060033"
        )
        code_hash = Web3.keccak(runtime).hex()
        stale_layout = StorageLayout(
            "StaleProxy",
            [
                StorageVariable(
                    "singleton",
                    0,
                    0,
                    32,
                    "t_address",
                    "address",
                )
            ],
            {
                "t_address": StorageType(
                    "t_address",
                    "address",
                    "value",
                    "inplace",
                    20,
                )
            },
        )
        row = SimpleNamespace(
            code_hash=code_hash,
            is_proxy=False,
            proxy_type=None,
            implementation_address=None,
        )
        stale = ContractMetadata(
            chain_id=1,
            address=PROXY_A,
            code_hash=code_hash,
            storage_layout=stale_layout,
        )
        bindings = _CachedBindings(row, stale)
        test = self

        class Provider:
            async def get_code(self, chain_id, address, block):
                if address == PROXY_A:
                    return runtime
                if address == IMPLEMENTATION_A:
                    return b"\x60\x00"
                return b""

            async def get_storage_values(
                self,
                chain_id,
                address,
                slots,
                block,
            ):
                return {
                    slot: "0x"
                    + (
                        _address_word(IMPLEMENTATION_A)
                        if slot == 0
                        else bytes(32)
                    ).hex()
                    for slot in slots
                }

            async def eth_call(self, chain_id, transaction, block):
                test.assertEqual(
                    transaction["data"],
                    GNOSIS_SAFE_MASTER_COPY_SELECTOR,
                )
                return _address_word(IMPLEMENTATION_A)

        service = VerificationService(Settings(), http_client=object())
        service._fetch_verification = AsyncMock(
            return_value=_verification_with_layout(
                "SafeImplementation",
                "uint256",
            )
        )
        resolver = _resolver(
            Provider(),
            service,
            _MemorySourceCache(),
            bindings=bindings,
        )

        result = await resolver.resolve(1, PROXY_A)

        self.assertTrue(result.is_proxy)
        self.assertEqual(result.proxy_type, "gnosis_safe")
        self.assertEqual(result.implementation_address, IMPLEMENTATION_A)
        self.assertEqual(result.name, "SafeImplementation")
        service._fetch_verification.assert_awaited_once_with(
            1,
            IMPLEMENTATION_A.lower(),
        )
        self.assertTrue(bindings.saved[-1].is_proxy)

    async def test_changed_proxy_target_replaces_historical_binding(self):
        runtime = b"\x60\x00\xf4"
        code_hash = Web3.keccak(runtime).hex()
        stale_layout = StorageLayout(
            "OldImplementation",
            [
                StorageVariable(
                    "value",
                    0,
                    0,
                    32,
                    "t_uint256",
                    "uint256",
                )
            ],
            {
                "t_uint256": StorageType(
                    "t_uint256",
                    "uint256",
                    "value",
                    "inplace",
                    32,
                )
            },
        )
        row = SimpleNamespace(
            code_hash=code_hash,
            is_proxy=True,
            proxy_type="eip1967",
            implementation_address=IMPLEMENTATION_A.lower(),
        )
        stale = ContractMetadata(
            chain_id=1,
            address=PROXY_A,
            code_hash=code_hash,
            is_proxy=True,
            proxy_type="eip1967",
            implementation_address=IMPLEMENTATION_A,
            name="OldImplementation",
            storage_layout=stale_layout,
        )
        bindings = _CachedBindings(row, stale)
        provider = _Provider(
            codes={
                PROXY_A.lower(): runtime,
                IMPLEMENTATION_B.lower(): b"\x60\xbb",
            },
            implementations={PROXY_A.lower(): IMPLEMENTATION_B},
        )
        service = VerificationService(Settings(), http_client=object())
        service._fetch_verification = AsyncMock(
            return_value=_verification_with_layout(
                "NewImplementation",
                "address",
            )
        )
        resolver = _resolver(
            provider,
            service,
            _MemorySourceCache(),
            bindings=bindings,
        )

        result = await resolver.resolve(1, PROXY_A, block_number=123)

        self.assertTrue(result.is_proxy)
        self.assertEqual(result.proxy_type, "eip1967")
        self.assertEqual(result.implementation_address, IMPLEMENTATION_B)
        self.assertEqual(result.name, "NewImplementation")
        service._fetch_verification.assert_awaited_once_with(
            1,
            IMPLEMENTATION_B.lower(),
        )
        self.assertEqual(bindings.saved[-1].implementation_address, IMPLEMENTATION_B)

    async def test_authorities_share_delegate_and_changes_select_new_identity(self):
        provider = _Provider(
            codes={
                AUTHORITY_A.lower(): {
                    100: _designator(IMPLEMENTATION_A),
                    200: _designator(IMPLEMENTATION_B),
                },
                AUTHORITY_B.lower(): _designator(IMPLEMENTATION_A),
                IMPLEMENTATION_A.lower(): b"\x60\xaa",
                IMPLEMENTATION_B.lower(): b"\x60\xbb",
            }
        )
        service = _service()
        resolver = _resolver(provider, service, _MemorySourceCache())

        first = await resolver.resolve(1, AUTHORITY_A, block_number=100)
        shared = await resolver.resolve(1, AUTHORITY_B, block_number=100)
        changed = await resolver.resolve(1, AUTHORITY_A, block_number=200)

        self.assertEqual(first.delegate_address, IMPLEMENTATION_A)
        self.assertEqual(shared.name, first.name)
        self.assertEqual(changed.delegate_address, IMPLEMENTATION_B)
        self.assertEqual(
            service._fetch_verification.await_count,
            2,
        )

    async def test_delegate_hash_change_misses_and_proxy_bytecode_is_not_followed(self):
        proxy_like_delegate = b"\x60\x00\xf4"
        provider = _Provider(
            codes={
                AUTHORITY_A.lower(): _designator(IMPLEMENTATION_A),
                IMPLEMENTATION_A.lower(): {
                    100: proxy_like_delegate,
                    200: proxy_like_delegate + b"\x00",
                },
            },
            implementations={IMPLEMENTATION_A.lower(): IMPLEMENTATION_B},
        )
        service = _service()
        resolver = _resolver(provider, service, _MemorySourceCache())

        await resolver.resolve(1, AUTHORITY_A, block_number=100)
        await resolver.resolve(1, AUTHORITY_A, block_number=200)

        self.assertEqual(service._fetch_verification.await_count, 2)
        self.assertFalse(any(
            address == IMPLEMENTATION_A.lower()
            for address, _, _ in provider.storage_calls
        ))

    async def test_source_cache_stays_active_without_binding_cache(self):
        provider = _Provider(codes={DIRECT.lower(): b"\x60\x00"})
        service = _service()
        cache = _MemorySourceCache()
        resolver = _resolver(
            provider,
            service,
            cache,
            use_binding_cache=False,
        )

        await resolver.resolve(1, DIRECT, block_number=100)
        await resolver.resolve(1, DIRECT, block_number=200)

        service._fetch_verification.assert_awaited_once_with(1, DIRECT.lower())


if __name__ == "__main__":
    unittest.main()
