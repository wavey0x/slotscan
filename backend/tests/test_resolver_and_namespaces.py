import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from eth_abi import encode
from web3 import Web3

from app.config import Settings
from app.models.domain import (
    StorageLayout,
    StorageType,
    StorageVariable,
    VerificationResult,
)
from app.services.namespace_storage import (
    NamespaceStorageParser,
    compute_erc7201_root,
)
from app.services.resolver import (
    BEACON_IMPL_SELECTOR,
    EIP1822_SLOT,
    EIP1967_BEACON_SLOT,
    EIP1967_IMPL_SLOT,
    ERC897_PROXY_TYPE_SELECTOR,
    EIP1167_PREFIX,
    EIP1167_SUFFIX,
    GNOSIS_SAFE_MASTER_COPY_SELECTOR,
    ZEPPELINOS_IMPL_SLOT,
    ContractResolver,
)
from app.services.tracer.slot_resolver import SlotPathResolver
from app.utils.vyper import (
    LEGACY_HASHED_STORAGE,
    LOCK_AFTER_GLOBALS,
    LOCK_AFTER_STORAGE,
    LOCK_FRONT_PER_FUNCTION,
    LOCK_FRONT_PER_KEY,
    LOCK_SENTINEL,
    SEQUENTIAL_STORAGE,
    vyper_storage_policy,
)


ADDRESS = "0x" + "11" * 20


def _make_resolver(provider, settings=None, **kwargs):
    return ContractResolver(
        provider,
        settings or Settings(),
        verification_service=AsyncMock(),
        source_cache_repo=object(),
        **kwargs,
    )


class NamespaceParserTests(unittest.TestCase):
    def test_vyper_storage_policy_has_explicit_compiler_boundaries(self):
        cases = {
            "0.2.8": (LEGACY_HASHED_STORAGE, LOCK_SENTINEL, False),
            "0.2.9": (LEGACY_HASHED_STORAGE, LOCK_AFTER_GLOBALS, False),
            "0.2.12": (LEGACY_HASHED_STORAGE, LOCK_AFTER_GLOBALS, False),
            "0.2.13": (SEQUENTIAL_STORAGE, LOCK_AFTER_STORAGE, False),
            "0.2.14": (SEQUENTIAL_STORAGE, LOCK_AFTER_STORAGE, False),
            "0.2.15": (SEQUENTIAL_STORAGE, LOCK_FRONT_PER_FUNCTION, False),
            "0.2.16": (SEQUENTIAL_STORAGE, LOCK_FRONT_PER_FUNCTION, True),
            "0.3.0": (SEQUENTIAL_STORAGE, LOCK_FRONT_PER_FUNCTION, True),
            "0.3.1": (SEQUENTIAL_STORAGE, LOCK_FRONT_PER_KEY, True),
        }
        for version, expected in cases.items():
            with self.subTest(version=version):
                policy = vyper_storage_policy(version)
                self.assertEqual(
                    (
                        policy.storage_scheme,
                        policy.lock_scheme,
                        policy.compiler_layout_supported,
                    ),
                    expected,
                )

    def test_vyper_024_uses_hashed_composites_and_sentinel_lock(self):
        source = """
# @version 0.2.4
struct Point:
    bias: int128
    slope: int128
    ts: uint256
    blk: uint256
struct LockedBalance:
    amount: int128
    end: uint256
token: public(address)
supply: public(uint256)
locked: public(HashMap[address, LockedBalance])
epoch: public(uint256)
point_history: public(Point[100000000000000000000000000000])
user_point_history: public(HashMap[address, Point[1000000000]])
user_point_epoch: public(HashMap[address, uint256])
slope_changes: public(HashMap[uint256, int128])
name: public(String[64])
@external
@nonreentrant("lock")
def one():
    pass
@external
@nonreentrant("lock")
def two():
    pass
"""
        layout = NamespaceStorageParser().parse_vyper_storage(
            {"VotingEscrow.vy": source},
            "VotingEscrow",
            "0.2.4+commit.7949850",
        )

        self.assertEqual(layout.storage_scheme, LEGACY_HASHED_STORAGE)
        self.assertEqual(layout.compiler_version, "0.2.4+commit.7949850")
        self.assertEqual(
            {
                variable.name: variable.slot
                for variable in layout.variables
                if not variable.name.startswith("nonreentrant.")
            },
            {
                "token": 0,
                "supply": 1,
                "locked": 2,
                "epoch": 3,
                "point_history": 4,
                "user_point_history": 5,
                "user_point_epoch": 6,
                "slope_changes": 7,
                "name": 8,
            },
        )
        locks = [
            variable
            for variable in layout.variables
            if variable.name == "nonreentrant.lock"
        ]
        point_history = next(
            variable for variable in layout.variables
            if variable.name == "point_history"
        )
        self.assertEqual([variable.slot for variable in locks], [0xFFFFFF])
        self.assertEqual(point_history.size, 32)
        point_type = layout.get_type(
            layout.get_type(point_history.type_id).element_type
        )
        self.assertEqual(
            [(member.name, member.slot) for member in point_type.members],
            [("bias", 0), ("slope", 1), ("ts", 2), ("blk", 3)],
        )

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
        strategies = next(
            variable for variable in layout.variables
            if variable.name == "strategies"
        )
        strategy_mapping = layout.types[strategies.type_id]
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
        match = SlotPathResolver().try_match_slot_from_preimage(
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
        reward_tokens = next(
            variable for variable in layout.variables
            if variable.name == "reward_tokens"
        )
        reward_tokens_type = layout.get_type(reward_tokens.type_id)
        self.assertEqual(reward_tokens_type.array_length, 8)

        user = "0x" + "11" * 20
        reward_token = "0x" + "22" * 20
        resolver = SlotPathResolver()

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
    def __init__(self, web3_provider, settings, **kwargs):
        verification_service = AsyncMock()
        verification_service.resolve.side_effect = self._resolve_verification
        super().__init__(
            web3_provider,
            settings,
            verification_service=verification_service,
            source_cache_repo=object(),
            **kwargs,
        )

    async def _resolve_verification(
        self,
        chain_id,
        address,
        code_hash,
        source_cache_repo,
    ):
        return await self._fetch_verification(chain_id, address)

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


class ProxyDetectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_push_data_does_not_trigger_proxy_slot_reads(self):
        class Provider:
            def __init__(self):
                self.storage_calls = []

            async def get_storage_at(self, chain_id, address, slot, block):
                self.storage_calls.append(slot)

        provider = Provider()
        detected = await _make_resolver(provider).detect_proxy(
            1,
            ADDRESS,
            block=123,
            bytecode=b"\x64\x00\xf4\x00\x00\x00",
        )

        self.assertIsNone(detected)
        self.assertEqual(provider.storage_calls, [])

    async def test_eip1167_is_detected_without_slot_reads(self):
        implementation = Web3.to_checksum_address("0x" + "22" * 20)
        test = self

        class Provider:
            async def get_storage_at(self, *args):
                raise AssertionError("minimal proxy must not read proxy slots")

            async def get_code(self, chain_id, address, block):
                test.assertEqual(address, implementation)
                return b"\x60\x00"

        bytecode = (
            EIP1167_PREFIX
            + bytes.fromhex(implementation[2:])
            + EIP1167_SUFFIX
        )
        detected = await _make_resolver(Provider()).detect_proxy(
            1,
            ADDRESS,
            block=123,
            bytecode=bytecode,
        )

        self.assertEqual(detected.proxy_type, "eip1167")
        self.assertEqual(detected.implementation_address, implementation)

    async def test_eip1167_with_appended_bytes_is_not_treated_as_exact(self):
        implementation = Web3.to_checksum_address("0x" + "22" * 20)

        class Provider:
            async def get_storage_at(self, chain_id, address, slot, block):
                return bytes(32)

        bytecode = (
            EIP1167_PREFIX
            + bytes.fromhex(implementation[2:])
            + EIP1167_SUFFIX
            + b"\x00"
        )
        detected = await _make_resolver(Provider()).detect_proxy(
            1,
            ADDRESS,
            block=123,
            bytecode=bytecode,
        )

        self.assertIsNone(detected)

    async def test_eip1967_implementation_requires_code_at_the_same_block(self):
        implementation = Web3.to_checksum_address("0x" + "22" * 20)
        test = self

        class Provider:
            async def get_storage_at(self, chain_id, address, slot, block):
                test.assertEqual(block, 123)
                if slot == EIP1967_IMPL_SLOT:
                    return bytes(12) + bytes.fromhex(implementation[2:])
                return bytes(32)

            async def get_code(self, chain_id, address, block):
                test.assertEqual((address, block), (implementation, 123))
                return b"\x60\x00"

        detected = await _make_resolver(Provider()).detect_proxy(
            1,
            ADDRESS,
            block=123,
            bytecode=b"\x60\x00\xf4",
        )

        self.assertEqual(detected.proxy_type, "eip1967")
        self.assertEqual(detected.implementation_address, implementation)

    async def test_eip1967_rejects_dirty_address_words_and_empty_targets(self):
        implementation = Web3.to_checksum_address("0x" + "22" * 20)

        class Provider:
            async def get_storage_at(self, chain_id, address, slot, block):
                if slot == EIP1967_IMPL_SLOT:
                    return b"\x01" + bytes(11) + bytes.fromhex(implementation[2:])
                return bytes(32)

            async def get_code(self, *args):
                raise AssertionError("malformed address must not be probed")

        detected = await _make_resolver(Provider()).detect_proxy(
            1,
            ADDRESS,
            block=123,
            bytecode=b"\xf4",
        )

        self.assertIsNone(detected)

    async def test_eip1967_beacon_resolves_implementation(self):
        beacon = Web3.to_checksum_address("0x" + "33" * 20)
        implementation = Web3.to_checksum_address("0x" + "22" * 20)
        test = self

        class Provider:
            async def get_storage_at(self, chain_id, address, slot, block):
                if slot == EIP1967_BEACON_SLOT:
                    return bytes(12) + bytes.fromhex(beacon[2:])
                return bytes(32)

            async def get_code(self, chain_id, address, block):
                return b"\x60\x00" if address in {beacon, implementation} else b""

            async def eth_call(self, chain_id, transaction, block):
                test.assertEqual(
                    transaction,
                    {"to": beacon, "data": BEACON_IMPL_SELECTOR},
                )
                return bytes(12) + bytes.fromhex(implementation[2:])

        detected = await _make_resolver(Provider()).detect_proxy(
            1,
            ADDRESS,
            block=123,
            bytecode=b"\xf4",
        )

        self.assertEqual(detected.proxy_type, "beacon")
        self.assertEqual(detected.implementation_address, implementation)

    async def test_legacy_standard_slots_resolve_only_deployed_targets(self):
        implementation = Web3.to_checksum_address("0x" + "22" * 20)
        cases = (
            ("eip1822", EIP1822_SLOT),
            ("zeppelinos", ZEPPELINOS_IMPL_SLOT),
        )

        for expected_type, implementation_slot in cases:
            with self.subTest(expected_type=expected_type):
                class Provider:
                    async def get_storage_at(
                        self,
                        chain_id,
                        address,
                        slot,
                        block,
                    ):
                        if slot == implementation_slot:
                            return bytes(12) + bytes.fromhex(implementation[2:])
                        return bytes(32)

                    async def get_code(self, chain_id, address, block):
                        return b"\x60\x00" if address == implementation else b""

                detected = await _make_resolver(Provider()).detect_proxy(
                    1,
                    ADDRESS,
                    block=123,
                    bytecode=b"\xf4",
                )

                self.assertEqual(detected.proxy_type, expected_type)
                self.assertEqual(
                    detected.implementation_address,
                    implementation,
                )

    async def test_safe_push4_dispatch_resolves_matching_slot_zero_singleton(self):
        implementation = Web3.to_checksum_address("0x" + "22" * 20)
        test = self

        class Provider:
            async def get_storage_at(
                self,
                chain_id,
                address,
                slot,
                block,
            ):
                if slot == 0:
                    return bytes(12) + bytes.fromhex(implementation[2:])
                return bytes(32)

            async def eth_call(self, chain_id, transaction, block):
                test.assertEqual(
                    transaction["data"],
                    GNOSIS_SAFE_MASTER_COPY_SELECTOR,
                )
                return bytes(12) + bytes.fromhex(implementation[2:])

            async def get_code(self, chain_id, address, block):
                return b"\x60\x00" if address == implementation else b""

        detected = await _make_resolver(Provider()).detect_proxy(
            1,
            ADDRESS,
            block=123,
            bytecode=(
                b"\x63"
                + bytes.fromhex(GNOSIS_SAFE_MASTER_COPY_SELECTOR[2:])
                + b"\x50\xf4"
            ),
        )

        self.assertEqual(detected.proxy_type, "gnosis_safe")
        self.assertEqual(detected.implementation_address, implementation)

    async def test_deployed_safe_push32_dispatch_resolves_singleton(self):
        implementation = Web3.to_checksum_address(
            "0xfb1bffC9d739B8D520DaF37dF666da4C687191EA"
        )
        runtime = bytes.fromhex(
            "608060405273ffffffffffffffffffffffffffffffffffffffff600054167f"
            "a619486e00000000000000000000000000000000000000000000000000000000"
            "60003514156050578060005260206000f35b3660008037600080366000845af4"
            "3d6000803e60008114156070573d6000fd5b3d6000f3fea26469706673582212"
            "20d1429297349653a4918076d650332de1a1068c5f3e07c5c82360c277770b9"
            "55264736f6c63430007060033"
        )
        test = self

        class Provider:
            async def get_storage_at(
                self,
                chain_id,
                address,
                slot,
                block,
            ):
                if slot == 0:
                    return bytes(12) + bytes.fromhex(implementation[2:])
                return bytes(32)

            async def eth_call(self, chain_id, transaction, block):
                test.assertEqual(
                    transaction,
                    {
                        "to": ADDRESS,
                        "data": GNOSIS_SAFE_MASTER_COPY_SELECTOR,
                    },
                )
                return bytes(12) + bytes.fromhex(implementation[2:])

            async def get_code(self, chain_id, address, block):
                return b"\x60\x00" if address == implementation else b""

        self.assertEqual(len(runtime), 171)
        detected = await _make_resolver(Provider()).detect_proxy(
            1,
            ADDRESS,
            block=25_559_529,
            bytecode=runtime,
        )

        self.assertEqual(detected.proxy_type, "gnosis_safe")
        self.assertEqual(detected.implementation_address, implementation)

    async def test_safe_requires_slot_zero_and_getter_to_agree(self):
        slot_implementation = Web3.to_checksum_address("0x" + "22" * 20)
        getter_implementation = Web3.to_checksum_address("0x" + "33" * 20)

        class Provider:
            async def get_storage_at(
                self,
                chain_id,
                address,
                slot,
                block,
            ):
                if slot == 0:
                    return bytes(12) + bytes.fromhex(slot_implementation[2:])
                return bytes(32)

            async def eth_call(self, chain_id, transaction, block):
                return bytes(12) + bytes.fromhex(getter_implementation[2:])

            async def get_code(self, *args):
                raise AssertionError("mismatched Safe evidence must not be followed")

        detected = await _make_resolver(Provider()).detect_proxy(
            1,
            ADDRESS,
            block=123,
            bytecode=(
                b"\x63"
                + bytes.fromhex(GNOSIS_SAFE_MASTER_COPY_SELECTOR[2:])
                + b"\x50\xf4"
            ),
        )

        self.assertIsNone(detected)

    async def test_safe_requires_deployed_singleton(self):
        implementation = Web3.to_checksum_address("0x" + "22" * 20)

        class Provider:
            async def get_storage_at(
                self,
                chain_id,
                address,
                slot,
                block,
            ):
                if slot == 0:
                    return bytes(12) + bytes.fromhex(implementation[2:])
                return bytes(32)

            async def eth_call(self, chain_id, transaction, block):
                return bytes(12) + bytes.fromhex(implementation[2:])

            async def get_code(self, chain_id, address, block):
                return b""

        detected = await _make_resolver(Provider()).detect_proxy(
            1,
            ADDRESS,
            block=123,
            bytecode=(
                b"\x63"
                + bytes.fromhex(GNOSIS_SAFE_MASTER_COPY_SELECTOR[2:])
                + b"\x50\xf4"
            ),
        )

        self.assertIsNone(detected)

    async def test_erc897_requires_proxy_type_and_implementation_getters(self):
        implementation = Web3.to_checksum_address("0x" + "22" * 20)

        class Provider:
            async def get_storage_at(self, *args):
                return bytes(32)

            async def eth_call(self, chain_id, transaction, block):
                if transaction["data"] == BEACON_IMPL_SELECTOR:
                    return bytes(12) + bytes.fromhex(implementation[2:])
                if transaction["data"] == ERC897_PROXY_TYPE_SELECTOR:
                    return (2).to_bytes(32, "big")
                raise AssertionError("unexpected getter")

            async def get_code(self, chain_id, address, block):
                return b"\x60\x00" if address == implementation else b""

        bytecode = (
            b"\x63"
            + bytes.fromhex(BEACON_IMPL_SELECTOR[2:])
            + b"\x50\x63"
            + bytes.fromhex(ERC897_PROXY_TYPE_SELECTOR[2:])
            + b"\x50\xf4"
        )
        detected = await _make_resolver(Provider()).detect_proxy(
            1,
            ADDRESS,
            block=123,
            bytecode=bytecode,
        )

        self.assertEqual(detected.proxy_type, "erc897")
        self.assertEqual(detected.implementation_address, implementation)

    async def test_implementation_getter_alone_is_not_proxy_proof(self):
        class Provider:
            async def get_storage_at(self, *args):
                return bytes(32)

            async def eth_call(self, *args):
                raise AssertionError("generic getter must not be probed")

        detected = await _make_resolver(Provider()).detect_proxy(
            1,
            ADDRESS,
            block=123,
            bytecode=(
                b"\x63"
                + bytes.fromhex(BEACON_IMPL_SELECTOR[2:])
                + b"\x50\xf4"
            ),
        )

        self.assertIsNone(detected)


class ResolverRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_vyper_0216_prefers_exact_compiler_layout(self):
        class VyperResolver(_Resolver):
            async def _fetch_verification(self, chain_id, address):
                return VerificationResult(
                    source="etherscan",
                    match_type="full",
                    name="Vault",
                    compiler_version="0.2.16+commit.59e1bdd",
                    sources={"Vault.vy": "# @version 0.2.16\nowner: address\n"},
                    storage_layout=None,
                    language="Vyper",
                )

        value_type = StorageType("address", "address", "value", "inplace", 20)
        exact_layout = StorageLayout(
            contract_name="Vault",
            variables=[StorageVariable(
                "owner",
                0,
                0,
                20,
                "address",
                "address",
                provenance="compiler_layout",
                confidence="exact",
            )],
            types={"address": value_type},
        )
        parser = SimpleNamespace(
            parse_vyper_with_artifact=AsyncMock(
                return_value=(exact_layout, SimpleNamespace(fingerprint="exact-vyper"))
            )
        )
        resolver = VyperResolver(object(), Settings(), layout_parser=parser)
        resolver.namespace_parser.parse_vyper_storage = Mock(
            side_effect=AssertionError("exact compiler layout must be preferred")
        )

        metadata = await resolver.resolve(1, ADDRESS)

        parser.parse_vyper_with_artifact.assert_awaited_once()
        resolver.namespace_parser.parse_vyper_storage.assert_not_called()
        self.assertEqual(metadata.storage_layout.variables[0].provenance, "compiler_layout")
        self.assertEqual(metadata.storage_layout.storage_scheme, SEQUENTIAL_STORAGE)

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

    async def test_supplied_empty_compiler_layout_is_preserved(self):
        resolver = _Resolver(object(), Settings())
        resolver.namespace_parser.parse_namespaced_storage = lambda sources: None
        metadata = await resolver.resolve(1, ADDRESS)
        self.assertIsNotNone(metadata.storage_layout)
        self.assertEqual(metadata.storage_layout.language, "Solidity")
        self.assertEqual(metadata.storage_layout.variables, [])
        self.assertEqual(
            [(scope.id, scope.kind, scope.confidence) for scope in metadata.storage_layout.scopes],
            [("default", "default", "exact")],
        )

    async def test_erc7201_annotations_use_compiler_derived_harness_types(self):
        identifier = "slotscan.resolver"
        root = compute_erc7201_root(identifier)
        source = f"""
            library Example {{
                /// @custom:storage-location erc7201:{identifier}
                struct Layout {{
                    uint64 initialized;
                    bool initializing;
                }}
                bytes32 private constant SLOT = 0x{root:064x};
                function load() internal pure returns (Layout storage $) {{
                    assembly {{ $.slot := SLOT }}
                }}
            }}
            contract Namespaced {{}}
        """
        compiler_output = {
            "sources": {
                "Namespaced.sol": {
                    "ast": {
                        "nodeType": "SourceUnit",
                        "nodes": [
                            {
                                "nodeType": "StructDefinition",
                                "name": "Layout",
                                "canonicalName": "Example.Layout",
                                "documentation": {
                                    "text": (
                                        "@custom:storage-location "
                                        f"erc7201:{identifier}"
                                    )
                                },
                            }
                        ],
                    }
                }
            }
        }
        uint64 = StorageType(
            "t_uint64",
            "uint64",
            "value",
            "inplace",
            8,
        )
        boolean = StorageType(
            "t_bool",
            "bool",
            "value",
            "inplace",
            1,
        )
        struct = StorageType(
            "t_struct(Layout)1_storage",
            "struct Example.Layout",
            "struct",
            "inplace",
            32,
            members=[
                StorageVariable(
                    "initialized",
                    0,
                    0,
                    8,
                    uint64.id,
                    uint64.label,
                ),
                StorageVariable(
                    "initializing",
                    0,
                    8,
                    1,
                    boolean.id,
                    boolean.label,
                ),
            ],
        )
        exact_default = StorageLayout(
            contract_name="Namespaced",
            variables=[],
            types={},
            language="Solidity",
            compiler_version="0.8.30",
            storage_scheme="solidity",
        )
        artifact = SimpleNamespace(
            fingerprint="exact-namespace",
            compiler_output=compiler_output,
        )
        parser = SimpleNamespace(
            parse_from_raw_layout=Mock(return_value=exact_default),
            _make_artifact=Mock(return_value=artifact),
            parse_with_artifact=AsyncMock(
                return_value=(exact_default, artifact)
            ),
            compile_exact_namespace_types=AsyncMock(
                return_value=(
                    {
                        struct.id: struct,
                        uint64.id: uint64,
                        boolean.id: boolean,
                    },
                    compiler_output,
                )
            ),
        )

        class NamespacedResolver(_Resolver):
            async def _fetch_verification(self, chain_id, address):
                return VerificationResult(
                    source="sourcify",
                    match_type="full",
                    name="Namespaced",
                    compiler_version="0.8.30",
                    compilation_target={
                        "Namespaced.sol": "Namespaced"
                    },
                    compiler_settings={
                        "optimizer": {"enabled": True, "runs": 200}
                    },
                    sources={"Namespaced.sol": source},
                    storage_layout={"storage": [], "types": {}},
                    language="Solidity",
                )

        metadata = await NamespacedResolver(
            object(),
            Settings(),
            layout_parser=parser,
        ).resolve(1, ADDRESS)

        parser.parse_with_artifact.assert_awaited_once()
        parser.compile_exact_namespace_types.assert_awaited_once()
        scope = next(
            item
            for item in metadata.storage_layout.scopes
            if item.kind == "erc7201"
        )
        self.assertEqual(scope.root_slot, root)
        self.assertEqual(
            [
                (item.name, item.slot, item.offset, item.confidence)
                for item in metadata.storage_layout.variables
                if item.scope_id == scope.id
            ],
            [
                ("initialized", root, 0, "exact"),
                ("initializing", root, 8, "exact"),
            ],
        )

    async def test_pre_layout_vyper_source_is_inferred_without_compilation(self):
        class VyperResolver(_Resolver):
            async def _fetch_verification(self, chain_id, address):
                return VerificationResult(
                    source="sourcify",
                    match_type="full",
                    name="Vault",
                    compiler_version="0.2.4",
                    sources={
                        "Vault.vy": (
                            "# @version 0.2.4\n"
                            "owner: public(address)\n"
                            "total: uint256\n"
                        )
                    },
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
            code_hash=Web3.keccak(b"\x60\x00").hex(),
            is_verified=True,
            storage_layout={
                "contract_name": "Cached",
                "scopes": [
                    {
                        "id": "default",
                        "kind": "default",
                        "root_slot": 0,
                        "formula": None,
                        "provenance": "compiler_layout",
                        "confidence": "exact",
                    }
                ],
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
                        "scope_id": "default",
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
                "language": "Vyper",
                "compiler_version": "0.3.7",
                "storage_scheme": "vyper_sequential",
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

if __name__ == "__main__":
    unittest.main()
