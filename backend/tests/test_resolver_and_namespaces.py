import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from eth_abi import encode
from web3 import Web3

from app.config import Settings
from app.models.domain import (
    StorageLayout,
    StorageType,
    StorageVariable,
    VerificationResult,
)
from app.services.namespace_storage import NamespaceStorageParser
from app.services.resolver import ContractResolver
from app.services.tracer.slot_resolver import SlotResolver


ADDRESS = "0x" + "11" * 20


class NamespaceParserTests(unittest.TestCase):
    def test_inferred_layout_sizes_interface_uint96_and_static_array(self):
        parser = NamespaceStorageParser()
        members = parser.parse_struct_members(
            "IERC20 token; uint96 amount; uint256[2] values;"
        )
        self.assertEqual(
            [(m.name, m.slot_offset, m.byte_offset, m.size) for m in members],
            [
                ("token", 0, 0, 20),
                ("amount", 0, 20, 12),
                ("values", 1, 0, 64),
            ],
        )

    def test_all_detected_namespaces_are_returned_as_inferred(self):
        sources = {
            "A.sol": """
                struct A { uint96 amount; }
                library LA {
                    bytes32 private constant SLOT_A = 0x100;
                    function load() internal pure returns (A storage $) {
                        assembly { $.slot := SLOT_A }
                    }
                }
            """,
            "B.sol": """
                struct B { address owner; }
                library LB {
                    bytes32 private constant SLOT_B = 0x200;
                    function load() internal pure returns (B storage $) {
                        assembly { $.slot := SLOT_B }
                    }
                }
            """,
        }
        layout = NamespaceStorageParser().parse_namespaced_storage(sources)
        self.assertEqual({v.name for v in layout.variables}, {"amount", "owner"})
        self.assertTrue(all(v.provenance == "source_inference" for v in layout.variables))
        self.assertTrue(all(v.confidence == "inferred" for v in layout.variables))

    def test_vyper_layout_reserves_lock_and_expands_declared_storage(self):
        source = """
struct StrategyParams:
    activation: uint256
    last_report: uint256
    current_debt: uint256
    max_debt: uint256

@external
@nonreentrant("lock")
def deposit():
    pass

MAX_QUEUE: constant(uint256) = 10
asset: public(address)
decimals: public(uint8)
factory: public(address)
strategies: public(HashMap[address, StrategyParams])
default_queue: DynArray[address, MAX_QUEUE]
use_default_queue: bool
balance_of: HashMap[address, uint256]
allowance: HashMap[address, HashMap[address, uint256]]
total_supply: uint256
total_debt: uint256
total_idle: uint256
"""
        layout = NamespaceStorageParser().parse_vyper_storage(
            {"ModernVault.vy": source},
            "ModernVault",
        )

        self.assertIsNotNone(layout)
        slots = {variable.name: variable.slot for variable in layout.variables}
        self.assertEqual(slots["nonreentrant.lock"], 0)
        self.assertEqual(slots["asset"], 1)
        self.assertEqual(slots["strategies"], 4)
        self.assertEqual(slots["default_queue"], 5)
        self.assertEqual(slots["use_default_queue"], 16)
        self.assertEqual(slots["total_debt"], 20)
        self.assertEqual(slots["total_idle"], 21)
        strategy_mapping = layout.types[
            layout.get_variable_by_name("strategies").type_id
        ]
        strategy_type = layout.types[strategy_mapping.value_type]
        self.assertEqual(
            [(member.name, member.slot) for member in strategy_type.members],
            [
                ("activation", 0),
                ("last_report", 1),
                ("current_debt", 2),
                ("max_debt", 3),
            ],
        )
        self.assertTrue(
            all(variable.provenance == "source_inference" for variable in layout.variables)
        )

    def test_vyper_immutables_do_not_shift_storage_or_mapping_resolution(self):
        source = """
# @version 0.3.7

struct StrategyParams:
    activation: uint256
    last_report: uint256
    current_debt: uint256
    max_debt: uint256

enum Roles:
    ADD_STRATEGY_MANAGER
    DEBT_MANAGER

@external
@nonreentrant("lock")
def deposit():
    pass

MAX_QUEUE: constant(uint256) = 10
ASSET: immutable(address)
DECIMALS: immutable(uint256)
FACTORY: public(immutable(address))
strategies: public(HashMap[address, StrategyParams])
default_queue: public(DynArray[address, MAX_QUEUE])
use_default_queue: public(bool)
balance_of: HashMap[address, uint256]
allowance: public(HashMap[address, HashMap[address, uint256]])
total_supply: public(uint256)
total_debt: uint256
total_idle: uint256
minimum_total_idle: public(uint256)
deposit_limit: public(uint256)
accountant: public(address)
deposit_limit_module: public(address)
withdraw_limit_module: public(address)
roles: public(HashMap[address, Roles])
open_roles: public(HashMap[Roles, bool])
role_manager: public(address)
future_role_manager: public(address)
name: public(String[64])
symbol: public(String[32])
"""
        layout = NamespaceStorageParser().parse_vyper_storage(
            {"ImmutableVault.vy": source},
            "ImmutableVault",
        )
        slots = {variable.name: variable.slot for variable in layout.variables}

        self.assertEqual(layout.language, "Vyper")
        self.assertNotIn("ASSET", slots)
        self.assertNotIn("DECIMALS", slots)
        self.assertNotIn("FACTORY", slots)
        self.assertEqual(slots["strategies"], 1)
        self.assertEqual(slots["withdraw_limit_module"], 23)
        self.assertEqual(slots["roles"], 24)
        self.assertEqual(slots["role_manager"], 26)
        self.assertEqual(slots["future_role_manager"], 27)
        self.assertEqual(slots["name"], 28)
        self.assertEqual(slots["symbol"], 31)

        account = "0x" + "11" * 20
        preimage = encode(["uint256", "address"], [24, account])
        slot = "0x" + Web3.keccak(preimage).hex()
        match = SlotResolver().try_match_slot_from_preimage(
            slot,
            "0x" + preimage.hex(),
            layout,
            {slot: "0x" + preimage.hex()},
        )
        self.assertEqual(match["path"], f"roles[{account}]")

    def test_legacy_vyper_layout_matches_compiler_allocation(self):
        source = """
# @version 0.2.16
implements: ERC20

struct Reward:
    token: address
    distributor: address
    period_finish: uint256
    rate: uint256
    last_update: uint256
    integral: uint256

MAX_REWARDS: constant(uint256) = 8

SDT: public(address)
voting_escrow: public(address)
veBoost_proxy: public(address)
staking_token: public(address)
decimal_staking_token: public(uint256)
balanceOf: public(HashMap[address, uint256])
totalSupply: public(uint256)
allowance: public(HashMap[address, HashMap[address, uint256]])
name: public(String[64])
symbol: public(String[32])
working_balances: public(HashMap[address, uint256])
working_supply: public(uint256)
integrate_checkpoint_of: public(HashMap[address, uint256])
reward_count: public(uint256)
reward_tokens: public(address[MAX_REWARDS])
reward_data: public(HashMap[address, Reward])
rewards_receiver: public(HashMap[address, address])
reward_integral_for: public(HashMap[address, HashMap[address, uint256]])
claim_data: HashMap[address, HashMap[address, uint256]]
admin: public(address)
future_admin: public(address)
claimer: public(address)
initialized: public(bool)

@external
@nonreentrant("lock")
def one():
    pass

@external
@nonreentrant("lock")
def two():
    pass

@external
@nonreentrant("lock")
def three():
    pass

@external
@nonreentrant("lock")
def four():
    pass

@external
@nonreentrant("lock")
def five():
    pass

@external
@nonreentrant("lock")
def six():
    pass

@external
@nonreentrant("lock")
def seven():
    pass
"""
        layout = NamespaceStorageParser().parse_vyper_storage(
            {"Vyper_contract.vy": source},
            "Vyper_contract",
        )

        self.assertIsNotNone(layout)
        slots = {variable.name: variable.slot for variable in layout.variables}
        self.assertNotIn("implements", slots)
        self.assertEqual(
            [variable.slot for variable in layout.variables if variable.name == "nonreentrant.lock"],
            list(range(7)),
        )
        self.assertEqual(slots["SDT"], 7)
        self.assertEqual(slots["balanceOf"], 12)
        self.assertEqual(slots["name"], 15)
        self.assertEqual(slots["symbol"], 19)
        self.assertEqual(slots["working_balances"], 22)
        self.assertEqual(slots["integrate_checkpoint_of"], 24)
        self.assertEqual(slots["reward_tokens"], 26)
        self.assertEqual(slots["reward_data"], 34)
        self.assertEqual(slots["reward_integral_for"], 36)
        self.assertEqual(slots["claim_data"], 37)
        self.assertEqual(slots["initialized"], 41)
        reward_tokens_type = layout.get_type(
            layout.get_variable_by_name("reward_tokens").type_id
        )
        self.assertEqual(reward_tokens_type.array_length, 8)

        user = "0x" + "11" * 20
        reward_token = "0x" + "22" * 20
        resolver = SlotResolver()

        balance_preimage = encode(["uint256", "address"], [12, user])
        balance_slot = "0x" + Web3.keccak(balance_preimage).hex()
        balance_lookup = {balance_slot: "0x" + balance_preimage.hex()}
        balance_match = resolver.try_match_slot_from_preimage(
            balance_slot,
            balance_lookup[balance_slot],
            layout,
            balance_lookup,
        )
        self.assertEqual(balance_match["path"], f"balanceOf[{user}]")

        outer_preimage = encode(["uint256", "address"], [36, reward_token])
        outer_hash = Web3.keccak(outer_preimage)
        outer_slot = "0x" + outer_hash.hex()
        inner_preimage = encode(["bytes32", "address"], [outer_hash, user])
        inner_slot = "0x" + Web3.keccak(inner_preimage).hex()
        nested_lookup = {
            outer_slot: "0x" + outer_preimage.hex(),
            inner_slot: "0x" + inner_preimage.hex(),
        }
        nested_match = resolver.try_match_slot_from_preimage(
            inner_slot,
            nested_lookup[inner_slot],
            layout,
            nested_lookup,
        )
        self.assertEqual(
            nested_match["path"],
            f"reward_integral_for[{reward_token}][{user}]",
        )

        reward_preimage = encode(["uint256", "address"], [34, reward_token])
        reward_base = Web3.keccak(reward_preimage)
        reward_base_slot = "0x" + reward_base.hex()
        reward_lookup = {reward_base_slot: "0x" + reward_preimage.hex()}
        offset_matches = list(
            resolver.find_struct_offset_matches(
                int.from_bytes(reward_base, "big") + 4,
                layout,
                reward_lookup,
            )
        )
        self.assertEqual(len(offset_matches), 1)
        offset, base_match = offset_matches[0]
        field_name, _ = resolver.resolve_match_struct_field(
            base_match,
            offset,
            layout,
        )
        self.assertEqual(field_name, "last_update")

    def test_keccak_minus_one_namespace_preserves_packed_member_offsets(self):
        source = """
struct StrategyData {
    address asset;
    uint8 decimals;
    string name;
    uint256 totalSupply;
    uint256 totalAssets;
    address emergencyAdmin;
    bool entered;
    bool shutdown;
}
library StrategyStorage {
    bytes32 private constant STORAGE =
        bytes32(uint256(keccak256("yearn.base.strategy.storage")) - 1);
    function get() internal pure returns (StrategyData storage S) {
        bytes32 slot = STORAGE;
        assembly { S.slot := slot }
    }
}
"""
        parser = NamespaceStorageParser()
        base = int.from_bytes(
            Web3.keccak(text="yearn.base.strategy.storage"), "big"
        ) - 1
        layout = parser.parse_namespaced_storage({"Strategy.sol": source})

        variables = {variable.name: variable for variable in layout.variables}
        self.assertEqual((variables["asset"].slot, variables["asset"].offset), (base, 0))
        self.assertEqual(
            (variables["decimals"].slot, variables["decimals"].offset),
            (base, 20),
        )
        self.assertEqual(variables["name"].slot, base + 1)
        self.assertEqual(variables["totalSupply"].slot, base + 2)
        self.assertEqual(variables["totalAssets"].slot, base + 3)
        self.assertEqual(
            [variables[name].slot for name in ("emergencyAdmin", "entered", "shutdown")],
            [base + 4, base + 4, base + 4],
        )

    def test_standard_and_unstructured_source_layouts(self):
        sources = {
            "Legacy.sol": """
contract Base {
    mapping(address => uint256) public wards;
}
contract Legacy is Base {
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
}
library StorageHelpers {
    bytes32 internal constant LAST_REQUEST_ID_POSITION =
        keccak256("lido.WithdrawalQueue.lastRequestId");
    function load() internal view returns (uint256) {
        return LAST_REQUEST_ID_POSITION.getStorageUint256();
    }
}
"""
        }
        parser = NamespaceStorageParser()

        standard = parser.parse_standard_storage(sources, "Legacy")
        self.assertEqual(
            [(variable.name, variable.slot) for variable in standard.variables],
            [("wards", 0), ("totalSupply", 1), ("balanceOf", 2)],
        )
        unstructured = parser.parse_unstructured_constants(sources)
        self.assertEqual(
            unstructured.variables[0].name,
            "lastRequestId",
        )
        self.assertEqual(
            unstructured.variables[0].slot,
            int.from_bytes(
                Web3.keccak(text="lido.WithdrawalQueue.lastRequestId"),
                "big",
            ),
        )


class _Resolver(ContractResolver):
    async def _check_is_contract(self, chain_id, address, block):
        return b"\x60\x00"

    async def detect_proxy(self, chain_id, address, block=None, bytecode=None):
        return None

    async def _fetch_verification(self, chain_id, address):
        return VerificationResult(
            source="sourcify",
            match_type="full",
            name="AlreadyLaidOut",
            compiler_version="0.8.30",
            sources={"C.sol": "contract AlreadyLaidOut {}"},
            storage_layout={"storage": [], "types": {}},
            language="Solidity",
        )


class ResolverRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_sourcify_v2_layout_is_parsed_without_sources_or_compilation(self):
        response = SimpleNamespace(
            status_code=200,
            json=lambda: {
                "match": "match",
                "storageLayout": {
                    "storage": [
                        {
                            "astId": 1,
                            "contract": "C.sol:C",
                            "label": "owner",
                            "offset": 0,
                            "slot": "0",
                            "type": "t_address",
                        }
                    ],
                    "types": {
                        "t_address": {
                            "encoding": "inplace",
                            "label": "address",
                            "numberOfBytes": "20",
                        }
                    },
                },
                "compilation": {
                    "language": "Solidity",
                    "compilerVersion": "0.8.26+commit.8a97fa7a",
                    "compilerSettings": {"optimizer": {"enabled": True}},
                    "name": "C",
                    "fullyQualifiedName": "src/C.sol:C",
                },
                "sources": {"src/C.sol": {"content": "contract C {}"}},
            },
        )
        client = SimpleNamespace(get=AsyncMock(return_value=response))
        resolver = ContractResolver(object(), Settings(), http_client=client)

        result = await resolver._try_sourcify(1, ADDRESS)

        self.assertEqual(result.name, "C")
        self.assertEqual(result.compilation_target, {"src/C.sol": "C"})
        self.assertEqual(result.storage_layout["storage"][0]["label"], "owner")
        self.assertEqual(result.sources, {"src/C.sol": "contract C {}"})
        client.get.assert_awaited_once_with(
            f"https://sourcify.dev/server/v2/contract/1/{ADDRESS}",
            params={"fields": "sources,storageLayout,compilation"},
        )

    async def test_verified_sources_without_layout_are_not_compiled_by_resolver(self):
        class SourceOnlyResolver(_Resolver):
            async def _fetch_verification(self, chain_id, address):
                return VerificationResult(
                    source="etherscan",
                    match_type="full",
                    name="NeedsCompilation",
                    compiler_version="0.8.30",
                    sources={"C.sol": "contract NeedsCompilation {}"},
                    storage_layout=None,
                )

        parser = SimpleNamespace(
            parse_from_raw_layout=AsyncMock(side_effect=AssertionError("not expected")),
            parse_with_artifact=AsyncMock(side_effect=AssertionError("must not compile")),
            parse_vyper_with_artifact=AsyncMock(
                side_effect=AssertionError("must not compile")
            ),
        )
        resolver = SourceOnlyResolver(object(), Settings(), layout_parser=parser)

        metadata = await resolver.resolve(1, ADDRESS)

        self.assertTrue(metadata.is_verified)
        self.assertIsNone(metadata.storage_layout)
        parser.parse_with_artifact.assert_not_awaited()
        parser.parse_vyper_with_artifact.assert_not_awaited()

    async def test_sourcify_only_mode_does_not_fall_back_to_source_apis(self):
        class SourcifyOnlyResolver(_Resolver):
            async def _try_sourcify(self, chain_id, address):
                return None

            async def _fetch_verification(self, chain_id, address):
                raise AssertionError("source fallback must not run")

        resolver = SourcifyOnlyResolver(object(), Settings())

        metadata = await resolver.resolve(
            1,
            ADDRESS,
            sourcify_layout_only=True,
        )

        self.assertFalse(metadata.is_verified)
        self.assertIsNone(metadata.storage_layout)

    async def test_supplied_storage_layout_does_not_leave_language_unbound(self):
        resolver = _Resolver(object(), Settings())
        resolver.namespace_parser.parse_namespaced_storage = lambda sources: None
        metadata = await resolver.resolve(1, ADDRESS)
        self.assertIsNone(metadata.storage_layout)

    async def test_verified_vyper_source_is_inferred_without_compilation(self):
        class VyperResolver(_Resolver):
            async def _fetch_verification(self, chain_id, address):
                return VerificationResult(
                    source="sourcify",
                    match_type="full",
                    name="Vault",
                    compiler_version="0.3.7",
                    sources={"Vault.vy": "owner: public(address)\ntotal: uint256\n"},
                    storage_layout=None,
                    language="Vyper",
                )

        metadata = await VyperResolver(object(), Settings()).resolve(1, ADDRESS)

        self.assertEqual(
            [(variable.name, variable.slot) for variable in metadata.storage_layout.variables],
            [("owner", 0), ("total", 1)],
        )
        self.assertTrue(
            all(
                variable.provenance == "source_inference"
                for variable in metadata.storage_layout.variables
            )
        )

    async def test_historical_resolution_uses_block_specific_cache(self):
        expected = SimpleNamespace(
            is_verified=True,
            storage_layout={
                "contract_name": "Cached",
                "variables": [
                    {
                        "name": "owner",
                        "slot": 0,
                        "offset": 0,
                        "size": 20,
                        "type_id": "address",
                        "label": "address",
                        "provenance": "source_inference",
                        "confidence": "inferred",
                    }
                ],
                "types": {
                    "address": {
                        "id": "address",
                        "label": "address",
                        "kind": "value",
                        "encoding": "inplace",
                        "num_bytes": 20,
                    }
                },
                "resolver_version": 4,
                "language": "Vyper",
            },
        )

        class Repo:
            async def get_at_block(self, chain_id, address, block_number):
                self.lookup = (chain_id, address, block_number)
                return expected

            def to_metadata(self, row):
                from app.models.domain import ContractMetadata, StorageLayout

                return ContractMetadata(
                    chain_id=1,
                    address=ADDRESS,
                    is_verified=True,
                    storage_layout=StorageLayout.from_dict(row.storage_layout),
                    compiler_artifact_fingerprint=None,
                )

        repo = Repo()
        resolver = _Resolver(object(), Settings(), contract_repo=repo)
        metadata = await resolver.resolve(1, ADDRESS, block_number=123)
        self.assertEqual(repo.lookup[2], 123)
        self.assertEqual(metadata.storage_layout.contract_name, "Cached")

    def test_v2_vyper_source_inference_cache_is_invalidated(self):
        value_type = StorageType(
            "uint256",
            "uint256",
            "value",
            "inplace",
            32,
        )
        layout = StorageLayout(
            contract_name="LegacyVyper",
            variables=[StorageVariable(
                "value",
                0,
                0,
                32,
                value_type.id,
                value_type.label,
                provenance="source_inference",
            )],
            types={value_type.id: value_type},
            resolver_version=2,
            language="Vyper",
        )
        self.assertFalse(ContractResolver._cache_layout_is_usable(layout))
        layout.resolver_version = 3
        self.assertFalse(ContractResolver._cache_layout_is_usable(layout))
        layout.resolver_version = 4
        self.assertTrue(ContractResolver._cache_layout_is_usable(layout))

    def test_v2_solidity_source_inference_cache_is_preserved(self):
        value_type = StorageType(
            "t_uint256",
            "uint256",
            "value",
            "inplace",
            32,
        )
        layout = StorageLayout(
            contract_name="borgCore",
            variables=[StorageVariable(
                "nativeCooldown",
                0,
                0,
                32,
                value_type.id,
                value_type.label,
                provenance="source_inference",
            )],
            types={value_type.id: value_type},
            resolver_version=2,
            language="Solidity",
        )

        self.assertTrue(ContractResolver._cache_layout_is_usable(layout))

        layout.resolver_version = 3
        self.assertTrue(ContractResolver._cache_layout_is_usable(layout))

        layout.resolver_version = 1
        self.assertFalse(ContractResolver._cache_layout_is_usable(layout))


if __name__ == "__main__":
    unittest.main()
