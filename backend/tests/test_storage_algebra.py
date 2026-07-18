import unittest
from unittest.mock import Mock, patch

from eth_abi import encode
from web3 import Web3

from app.api.routes.transactions import _group_changes_by_slot
from app.models.domain import StorageLayout, StorageType, StorageVariable
from app.services.layout_index import LayoutIndex, array_packing
from app.services.namespace_storage import NamespaceStorageParser
from app.config import Settings
from app.services.decoder import TypeDecoder
from app.services.tracer.tracer import TransactionAnalysisService
from app.services.tracer.slot_resolver import SlotPathResolver
from app.services.tracer.preimage_resolver import PreimageResolver
from app.utils.slots import compute_mapping_slot, encode_mapping_key


class MappingSlotTests(unittest.TestCase):
    def test_constant_mapping_candidates_are_capped_before_hashing(self):
        address_type = StorageType(
            "t_address",
            "address",
            "value",
            "inplace",
            20,
        )
        value_type = StorageType(
            "t_uint256",
            "uint256",
            "value",
            "inplace",
            32,
        )
        mapping_type = StorageType(
            "t_mapping",
            "mapping(address => uint256)",
            "mapping",
            "mapping",
            32,
            key_type=address_type.id,
            value_type=value_type.id,
        )
        layout = StorageLayout(
            "Constants",
            [
                StorageVariable("first", 0, 0, 32, mapping_type.id, mapping_type.label),
                StorageVariable("second", 1, 0, 32, mapping_type.id, mapping_type.label),
            ],
            {
                address_type.id: address_type,
                value_type.id: value_type,
                mapping_type.id: mapping_type,
            },
        )
        sources = {
            "Constants.sol": """
                address constant FIRST = 0x1111111111111111111111111111111111111111;
                address constant SECOND = 0x2222222222222222222222222222222222222222;
            """
        }

        with patch(
            "app.services.tracer.preimage_resolver.Web3.keccak"
        ) as keccak:
            lookup = PreimageResolver(
                max_constant_mapping_candidates=3
            ).build_constant_preimage_lookup(sources, layout)

        self.assertEqual(lookup, {})
        keccak.assert_not_called()
        self.assertEqual(
            len(
                PreimageResolver(
                    max_constant_mapping_candidates=4
                ).build_constant_preimage_lookup(sources, layout)
            ),
            4,
        )

    def test_vyper_024_bounded_string_resolves_hashed_length_and_data(self):
        layout = NamespaceStorageParser().parse_vyper_storage(
            {"Token.vy": "# @version 0.2.4\nname: public(String[64])\n"},
            "Token",
            "0.2.4",
        )
        preimage = encode(["uint256"], [0])
        data_start = int.from_bytes(Web3.keccak(preimage), "big")
        lookup = {f"0x{data_start:064x}": "0x" + preimage.hex()}
        raw_changes = [
            (
                f"0x{data_start:064x}",
                "0x" + "00" * 32,
                f"0x{4:064x}",
                0,
                0,
            ),
            (
                f"0x{data_start + 1:064x}",
                "0x" + "00" * 32,
                "0x" + b"Test".hex().ljust(64, "0"),
                1,
                1,
            ),
        ]

        changes = TransactionAnalysisService(object(), Settings(), TypeDecoder())._decode_changes(
            raw_changes,
            layout,
            lookup,
        )

        self.assertEqual(
            [change.variable_path for change in changes],
            ["name (length)", "name (data 0)"],
        )
        self.assertEqual(changes[0].new_decoded.decoded, 4)
        self.assertEqual(changes[1].new_decoded.type_label, "bytes32")

    def test_vyper_024_crv_transfer_resolves_legacy_balance_mapping(self):
        source = """
# @version 0.2.4
name: public(String[64])
symbol: public(String[32])
decimals: public(uint256)
balanceOf: public(HashMap[address, uint256])
allowances: public(HashMap[address, HashMap[address, uint256]])
total_supply: public(uint256)
minter: public(address)
admin: public(address)
mining_epoch: public(int128)
start_epoch_time: public(uint256)
rate: public(uint256)
start_epoch_supply: public(uint256)
"""
        layout = NamespaceStorageParser().parse_vyper_storage(
            {"CRV.vy": source},
            "Vyper_contract",
            "0.2.4+commit.7949850",
        )
        addresses = [
            "0x8867df8d263077f94ddb5e86c4328fd8d2c0e818",
            "0xc5184cccf85b81eddc661330acb3e41bd89f34a1",
        ]
        expected_slots = [
            "0x2a6488878e7a00f49b2124abf19b9d69a2b24e46f85aeae123432ab9927bae86",
            "0x166b3d23a4a6249cce3c0abf0c9267e72f3cb9dce86caa61b487b9c55a7a969c",
        ]
        lookup = {
            slot: "0x" + encode(["uint256", "address"], [3, address]).hex()
            for slot, address in zip(expected_slots, addresses, strict=True)
        }
        raw_changes = [
            (slot, "0x" + "00" * 32, f"0x{index + 1:064x}", index, index)
            for index, slot in enumerate(expected_slots)
        ]

        changes = TransactionAnalysisService(object(), Settings(), TypeDecoder())._decode_changes(
            raw_changes,
            layout,
            lookup,
        )

        self.assertEqual(
            [change.variable_path for change in changes],
            [f"balanceOf[{address}]" for address in addresses],
        )
        self.assertTrue(all(change.variable is not None for change in changes))

    def test_vyper_024_voting_escrow_transaction_resolves_all_legacy_paths(self):
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
controller: public(address)
transfersEnabled: public(bool)
name: public(String[64])
symbol: public(String[32])
version: public(String[32])
decimals: public(uint256)
future_smart_wallet_checker: public(address)
smart_wallet_checker: public(address)
admin: public(address)
future_admin: public(address)
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
"""
        layout = NamespaceStorageParser().parse_vyper_storage(
            {"VotingEscrow.vy": source},
            "VotingEscrow",
            "0.2.4+commit.7949850",
        )
        user = "0x490b8c6007ffa5d3728a49c2ee199e51f05d2f7e"
        lookup = {}

        def hash_preimage(preimage: bytes) -> int:
            output = int.from_bytes(Web3.keccak(preimage), "big")
            lookup[f"0x{output:064x}"] = "0x" + preimage.hex()
            return output

        locked_mapping = hash_preimage(encode(["uint256", "address"], [2, user]))
        locked_fields = hash_preimage(locked_mapping.to_bytes(32, "big"))

        point_array = hash_preimage(encode(["uint256"], [4]))
        point_element = point_array + 64026
        point_fields = hash_preimage(point_element.to_bytes(32, "big"))

        user_history_mapping = hash_preimage(
            encode(["uint256", "address"], [5, user])
        )
        user_history_array = hash_preimage(
            user_history_mapping.to_bytes(32, "big")
        )
        user_history_element = user_history_array + 133
        user_history_fields = hash_preimage(
            user_history_element.to_bytes(32, "big")
        )

        user_epoch = hash_preimage(encode(["uint256", "address"], [6, user]))
        slope_first = hash_preimage(
            encode(["uint256", "uint256"], [7, 1908144000])
        )
        slope_second = hash_preimage(
            encode(["uint256", "uint256"], [7, 1909353600])
        )

        intermediate_index = SlotPathResolver().build_legacy_vyper_slot_index(
            layout,
            lookup,
            {locked_mapping, point_element, user_history_element},
        )
        self.assertEqual(intermediate_index, {})

        slots_and_paths = [
            (0xFFFFFF, "nonreentrant.lock"),
            (1, "supply"),
            (locked_fields, f"locked[{user}].amount"),
            (locked_fields + 1, f"locked[{user}].end"),
            (3, "epoch"),
            (point_fields, "point_history[64026].bias"),
            (point_fields + 1, "point_history[64026].slope"),
            (point_fields + 2, "point_history[64026].ts"),
            (point_fields + 3, "point_history[64026].blk"),
            (slope_first, "slope_changes[1908144000]"),
            (slope_second, "slope_changes[1909353600]"),
            (user_epoch, f"user_point_epoch[{user}]"),
            (user_history_fields, f"user_point_history[{user}][133].bias"),
            (user_history_fields + 1, f"user_point_history[{user}][133].slope"),
            (user_history_fields + 2, f"user_point_history[{user}][133].ts"),
            (user_history_fields + 3, f"user_point_history[{user}][133].blk"),
        ]
        raw_changes = [
            (
                f"0x{slot:064x}",
                "0x" + "00" * 32,
                f"0x{index + 1:064x}",
                index,
                index,
            )
            for index, (slot, _) in enumerate(slots_and_paths)
        ]

        changes = TransactionAnalysisService(object(), Settings(), TypeDecoder())._decode_changes(
            raw_changes,
            layout,
            lookup,
        )

        self.assertEqual(
            [change.variable_path for change in changes],
            [path for _, path in slots_and_paths],
        )
        self.assertTrue(all(change.variable is not None for change in changes))
        self.assertEqual(
            [slot.variable_path for slot in _group_changes_by_slot(changes, layout)],
            [path for _, path in slots_and_paths],
        )

    def test_segmented_sha3_memory_words_build_canonical_preimage_lookup(self):
        preimage = encode(["address", "uint256"], ["0x" + "11" * 20, 7])
        segmented = "0x" + preimage[:32].hex() + "0x" + preimage[32:].hex()
        expected_hash = "0x" + Web3.keccak(preimage).hex()

        lookup = PreimageResolver().build_preimage_lookup(
            [{"preimage": segmented, "hash": None}]
        )

        self.assertEqual(lookup[expected_hash], "0x" + preimage.hex())

    def test_dynamic_bytes_uses_unpadded_contents(self):
        slot_word = encode(["uint256"], [7])
        expected = int.from_bytes(Web3.keccak(b"abc" + slot_word), "big")
        self.assertEqual(compute_mapping_slot(7, b"abc", "bytes"), expected)

    def test_string_uses_utf8_contents(self):
        slot_word = encode(["uint256"], [2])
        expected = int.from_bytes(Web3.keccak("héllo".encode() + slot_word), "big")
        self.assertEqual(compute_mapping_slot(2, "héllo", "string"), expected)

    def test_fixed_bytes_is_abi_word_not_dynamic_bytes(self):
        self.assertEqual(encode_mapping_key(b"\xab", "bytes1"), b"\xab" + bytes(31))
        self.assertNotEqual(
            compute_mapping_slot(1, b"\xab", "bytes1"),
            compute_mapping_slot(1, b"\xab", "bytes"),
        )

    def test_bool_enum_and_signed_integer(self):
        self.assertEqual(encode_mapping_key(True, "bool"), bytes(31) + b"\x01")
        self.assertEqual(encode_mapping_key(3, "t_enum$_Status_$42"), bytes(31) + b"\x03")
        self.assertEqual(encode_mapping_key(-1, "int8"), bytes([0xFF]) * 32)

    def test_unknown_mapping_key_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported mapping key type"):
            compute_mapping_slot(0, "anything", "SomeStruct")

    def test_runtime_string_preimage_uses_declared_key_type(self):
        value_type = StorageType("t_uint256", "uint256", "value", "inplace", 32)
        mapping_type = StorageType(
            "t_mapping_string_uint",
            "mapping(string => uint256)",
            "mapping",
            "mapping",
            32,
            key_type="t_string_storage",
            value_type="t_uint256",
        )
        variable = StorageVariable(
            "names", 4, 0, 32, mapping_type.id, mapping_type.label
        )
        layout = StorageLayout(
            "Strings",
            [variable],
            {value_type.id: value_type, mapping_type.id: mapping_type},
        )
        preimage = b"alice" + encode(["uint256"], [4])
        slot = Web3.keccak(preimage).hex()
        match = SlotPathResolver().try_match_slot_from_preimage(
            slot,
            "0x" + preimage.hex(),
            layout,
            {},
        )
        self.assertEqual(match["path"], "names[alice]")
        self.assertEqual(match["key_type"], "t_string_storage")

    def test_segmented_rpc_preimage_prefixes_are_normalized(self):
        value_type = StorageType("t_uint256", "uint256", "value", "inplace", 32)
        mapping_type = StorageType(
            "t_mapping_string_uint",
            "mapping(string => uint256)",
            "mapping",
            "mapping",
            32,
            key_type="t_string_storage",
            value_type=value_type.id,
        )
        variable = StorageVariable(
            "names", 4, 0, 32, mapping_type.id, mapping_type.label
        )
        layout = StorageLayout(
            "Strings",
            [variable],
            {value_type.id: value_type, mapping_type.id: mapping_type},
        )
        preimage = b"alice" + encode(["uint256"], [4])
        segmented_preimage = "0x" + preimage[:5].hex() + "0x" + preimage[5:].hex()
        slot = Web3.keccak(preimage).hex()

        match = SlotPathResolver().try_match_slot_from_preimage(
            slot,
            segmented_preimage,
            layout,
            {},
        )

        self.assertEqual(match["path"], "names[alice]")

    def test_nested_solidity_mapping_keeps_intermediate_hash_candidate(self):
        value_type = StorageType("t_uint256", "uint256", "value", "inplace", 32)
        inner_type = StorageType(
            "t_mapping_address_uint",
            "mapping(address => uint256)",
            "mapping",
            "mapping",
            32,
            key_type="t_address",
            value_type=value_type.id,
        )
        outer_type = StorageType(
            "t_mapping_address_mapping",
            "mapping(address => mapping(address => uint256))",
            "mapping",
            "mapping",
            32,
            key_type="t_address",
            value_type=inner_type.id,
        )
        variable = StorageVariable(
            "configs", 8, 0, 32, outer_type.id, outer_type.label
        )
        layout = StorageLayout(
            "Nested",
            [variable],
            {
                value_type.id: value_type,
                inner_type.id: inner_type,
                outer_type.id: outer_type,
            },
        )
        outer_key = "0x" + "11" * 20
        inner_key = "0x" + "22" * 20
        outer_preimage = encode(["address", "uint256"], [outer_key, 8])
        outer_hash = Web3.keccak(outer_preimage)
        outer_hash_hex = "0x" + outer_hash.hex()
        inner_preimage = encode(["address", "bytes32"], [inner_key, outer_hash])
        inner_hash = "0x" + Web3.keccak(inner_preimage).hex()
        lookup = {
            outer_hash_hex: "0x" + outer_preimage.hex(),
            inner_hash: "0x" + inner_preimage.hex(),
        }

        match = SlotPathResolver().try_match_slot_from_preimage(
            inner_hash,
            lookup[inner_hash],
            layout,
            lookup,
        )

        self.assertEqual(match["path"], f"configs[{outer_key}][{inner_key}]")

    def test_nested_mapping_array_uses_step_time_length_evidence(self):
        address_type = StorageType(
            "t_address", "address", "value", "inplace", 20
        )
        uint_type = StorageType(
            "t_uint256", "uint256", "value", "inplace", 32
        )
        address_array_type = StorageType(
            "t_array(t_address)dyn_storage",
            "address[]",
            "array",
            "dynamic_array",
            32,
            element_type=address_type.id,
        )
        member_specs = [
            ("token", address_type),
            ("amount", uint_type),
            ("maxPerVote", uint_type),
            ("distributed", uint_type),
            ("recycled", uint_type),
            ("depositor", address_type),
            ("excluded", address_array_type),
        ]
        incentive_type = StorageType(
            "t_struct(Incentive)83_storage",
            "struct Incentive",
            "struct",
            "inplace",
            224,
            members=[
                StorageVariable(
                    name,
                    slot,
                    0,
                    member_type.num_bytes or 32,
                    member_type.id,
                    member_type.label,
                )
                for slot, (name, member_type) in enumerate(member_specs)
            ],
        )
        incentive_array_type = StorageType(
            "t_array(t_struct(Incentive)83_storage)dyn_storage",
            "struct Incentive[]",
            "array",
            "dynamic_array",
            32,
            element_type=incentive_type.id,
        )
        inner_mapping_type = StorageType(
            "t_mapping(t_address,t_array(t_struct(Incentive)83_storage)dyn_storage)",
            "mapping(address => struct Incentive[])",
            "mapping",
            "mapping",
            32,
            key_type=address_type.id,
            value_type=incentive_array_type.id,
        )
        outer_mapping_type = StorageType(
            "t_mapping(t_uint256,t_mapping(t_address,t_array(t_struct(Incentive)83_storage)dyn_storage))",
            "mapping(uint256 => mapping(address => struct Incentive[]))",
            "mapping",
            "mapping",
            32,
            key_type=uint_type.id,
            value_type=inner_mapping_type.id,
        )
        incentives = StorageVariable(
            "incentives", 15, 0, 32, outer_mapping_type.id, outer_mapping_type.label
        )
        layout = StorageLayout(
            "Votium",
            [incentives],
            {
                storage_type.id: storage_type
                for storage_type in (
                    address_type,
                    uint_type,
                    address_array_type,
                    incentive_type,
                    incentive_array_type,
                    inner_mapping_type,
                    outer_mapping_type,
                )
            },
        )

        round_number = 126
        gauge = "0xaf01d68714e7ea67f43f08b5947e367126b889b1"
        outer_preimage = encode(["uint256", "uint256"], [round_number, 15])
        outer_hash = Web3.keccak(outer_preimage)
        inner_preimage = encode(["address", "bytes32"], [gauge, outer_hash])
        length_hash = Web3.keccak(inner_preimage)
        array_preimage = encode(["bytes32"], [length_hash])
        data_start = int.from_bytes(Web3.keccak(array_preimage), "big")
        length_slot = "0x" + length_hash.hex()
        data_start_slot = f"0x{data_start:064x}"
        lookup = {
            "0x" + outer_hash.hex(): "0x" + outer_preimage.hex(),
            length_slot: "0x" + inner_preimage.hex(),
            data_start_slot: "0x" + array_preimage.hex(),
        }

        # These are the actual array length/data slots from the reported
        # transaction, tying the algebraic regression to that production case.
        self.assertEqual(
            length_slot,
            "0x283e5d16b59690bbdd0ba707448646ea51cc76f8918d36a29e5a85ddf32d41cd",
        )
        self.assertEqual(
            data_start_slot,
            "0x36eac35083b7928db06e30b5d8301b2ef26535cc322c18fe88b6787b3e40faab",
        )

        raw_changes = [
            (length_slot, f"0x{0:064x}", f"0x{1:064x}", 1, 1),
            *[
                (
                    f"0x{data_start + slot:064x}",
                    f"0x{0:064x}",
                    f"0x{slot + 1:064x}",
                    slot + 2,
                    slot + 2,
                )
                for slot in range(7)
            ],
            # The observed length is one, so the next element must not be
            # claimed merely because its numeric slot follows the data start.
            (
                f"0x{data_start + 7:064x}",
                f"0x{0:064x}",
                f"0x{99:064x}",
                9,
                9,
            ),
        ]

        changes = TransactionAnalysisService(object(), Settings(), TypeDecoder())._decode_changes(
            raw_changes,
            layout,
            lookup,
            {
                int(length_slot, 16): (
                    0,
                    ((1, 1),),
                )
            },
        )

        base_path = f"incentives[{round_number}][{gauge}]"
        self.assertEqual(changes[0].variable_path, base_path)
        self.assertEqual(
            [change.variable_path for change in changes[1:8]],
            [f"{base_path}[0].{name}" for name, _ in member_specs],
        )
        self.assertTrue(all(change.variable is incentives for change in changes[:8]))
        self.assertTrue(all(change.array_index == 0 for change in changes[1:8]))
        self.assertTrue(
            all(change.encoding == "mapping_to_array" for change in changes[1:8])
        )
        self.assertIsNone(changes[8].variable)
        self.assertIsNone(changes[8].variable_path)

        slot_responses = _group_changes_by_slot(changes, layout)
        self.assertEqual(slot_responses[0].variable_path, base_path)
        self.assertEqual(
            [slot.variable_path for slot in slot_responses[1:8]],
            [f"{base_path}[0].{name}" for name, _ in member_specs],
        )
        self.assertTrue(
            all(slot.variable_name == "incentives" for slot in slot_responses[:8])
        )
        self.assertEqual(
            [slot.struct_field for slot in slot_responses[1:8]],
            [name for name, _ in member_specs],
        )
        self.assertIsNone(slot_responses[8].variable_name)

    def test_nested_vyper_mapping_uses_hash_before_key(self):
        value_type = StorageType("uint256", "uint256", "value", "inplace", 32)
        inner_type = StorageType(
            "HashMap[address, uint256]",
            "HashMap[address, uint256]",
            "mapping",
            "mapping",
            32,
            key_type="address",
            value_type=value_type.id,
        )
        outer_type = StorageType(
            "HashMap[address, HashMap[address, uint256]]",
            "HashMap[address, HashMap[address, uint256]]",
            "mapping",
            "mapping",
            32,
            key_type="address",
            value_type=inner_type.id,
        )
        variable = StorageVariable(
            "allowance", 18, 0, 32, outer_type.id, outer_type.label
        )
        layout = StorageLayout(
            "Vault",
            [variable],
            {
                value_type.id: value_type,
                inner_type.id: inner_type,
                outer_type.id: outer_type,
            },
        )
        owner = "0x" + "11" * 20
        spender = "0x" + "22" * 20
        outer_preimage = encode(["uint256", "address"], [18, owner])
        outer_hash = Web3.keccak(outer_preimage)
        outer_hash_hex = "0x" + outer_hash.hex()
        inner_preimage = encode(["bytes32", "address"], [outer_hash, spender])
        inner_hash = "0x" + Web3.keccak(inner_preimage).hex()
        lookup = {
            outer_hash_hex: "0x" + outer_preimage.hex(),
            inner_hash: "0x" + inner_preimage.hex(),
        }

        match = SlotPathResolver().try_match_slot_from_preimage(
            inner_hash,
            lookup[inner_hash],
            layout,
            lookup,
        )

        self.assertEqual(match["path"], f"allowance[{owner}][{spender}]")

    def test_inferred_vyper_layout_is_rejected_when_trace_mapping_base_disagrees(self):
        value_type = StorageType("Roles", "Roles", "value", "inplace", 32)
        mapping_type = StorageType(
            "HashMap[address, Roles]",
            "HashMap[address, Roles]",
            "mapping",
            "mapping",
            32,
            key_type="address",
            value_type=value_type.id,
        )
        variable = StorageVariable(
            "roles",
            27,
            0,
            32,
            mapping_type.id,
            mapping_type.label,
            provenance="source_inference",
            confidence="inferred",
        )
        layout = StorageLayout(
            "ModernVault",
            [variable],
            {value_type.id: value_type, mapping_type.id: mapping_type},
            language="Vyper",
        )
        account = "0x" + "11" * 20
        preimage = encode(["uint256", "address"], [24, account])
        slot = "0x" + Web3.keccak(preimage).hex()
        raw_changes = [(slot, "0x" + "00" * 32, "0x" + "01" * 32, 1, 1)]
        lookup = {slot: "0x" + preimage.hex()}

        self.assertEqual(
            TransactionAnalysisService._vyper_layout_evidence_conflicts(
                layout,
                raw_changes,
                lookup,
            ),
            [24],
        )
        tracer = TransactionAnalysisService(None, Settings(), TypeDecoder())
        self.assertIsNone(
            tracer._decode_changes(raw_changes, layout, lookup)[0].variable_path
        )

        variable.slot = 24
        self.assertEqual(
            TransactionAnalysisService._vyper_layout_evidence_conflicts(
                layout,
                raw_changes,
                lookup,
            ),
            [],
        )
        self.assertEqual(
            tracer._decode_changes(raw_changes, layout, lookup)[0].variable_path,
            f"roles[{account}]",
        )

    def test_struct_offset_search_does_not_scan_every_observed_preimage(self):
        value_type = StorageType("t_uint256", "uint256", "value", "inplace", 32)
        struct_type = StorageType(
            "t_struct_Record",
            "struct Record",
            "struct",
            "inplace",
            96,
            members=[
                StorageVariable("first", 0, 0, 32, value_type.id, value_type.label),
                StorageVariable("target", 2, 0, 32, value_type.id, value_type.label),
            ],
        )
        mapping_type = StorageType(
            "t_mapping_address_record",
            "mapping(address => Record)",
            "mapping",
            "mapping",
            32,
            key_type="t_address",
            value_type=struct_type.id,
        )
        variable = StorageVariable(
            "records", 4, 0, 32, mapping_type.id, mapping_type.label
        )
        layout = StorageLayout(
            "Records",
            [variable],
            {
                value_type.id: value_type,
                struct_type.id: struct_type,
                mapping_type.id: mapping_type,
            },
        )
        key = bytes.fromhex("11" * 20).rjust(32, b"\x00")
        preimage = key + encode(["uint256"], [4])
        base_hash = int.from_bytes(Web3.keccak(preimage), "big")
        lookup = {
            f"0x{base_hash:064x}": "0x" + preimage.hex(),
            **{
                f"0x{i + 1000:064x}": "0x" + bytes(64).hex()
                for i in range(500)
            },
        }

        class CountingResolver(SlotPathResolver):
            calls = 0

            def try_match_slot_from_preimage(self, *args, **kwargs):
                self.calls += 1
                return super().try_match_slot_from_preimage(*args, **kwargs)

        resolver = CountingResolver()
        matches = list(
            resolver.find_struct_offset_matches(base_hash + 2, layout, lookup)
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0][0], 2)
        self.assertLessEqual(resolver.calls, 2)

    def test_nested_mapping_inside_mapping_struct_resolves_inner_struct_field(self):
        uint_type = StorageType("t_uint256", "uint256", "value", "inplace", 32)
        bool_type = StorageType("t_bool", "bool", "value", "inplace", 1)
        method_type = StorageType(
            "t_struct_MethodConstraint",
            "struct MethodConstraint",
            "struct",
            "inplace",
            128,
            members=[
                StorageVariable("enabled", 0, 0, 1, bool_type.id, bool_type.label),
                StorageVariable(
                    "lastExecutionTimestamp",
                    3,
                    0,
                    32,
                    uint_type.id,
                    uint_type.label,
                ),
            ],
        )
        methods_mapping = StorageType(
            "t_mapping_bytes4_method",
            "mapping(bytes4 => MethodConstraint)",
            "mapping",
            "mapping",
            32,
            key_type="t_bytes4",
            value_type=method_type.id,
        )
        policy_type = StorageType(
            "t_struct_PolicyItem",
            "struct PolicyItem",
            "struct",
            "inplace",
            64,
            members=[
                StorageVariable(
                    "methods",
                    1,
                    0,
                    32,
                    methods_mapping.id,
                    methods_mapping.label,
                ),
            ],
        )
        policy_mapping = StorageType(
            "t_mapping_address_policy",
            "mapping(address => PolicyItem)",
            "mapping",
            "mapping",
            32,
            key_type="t_address",
            value_type=policy_type.id,
        )
        variable = StorageVariable(
            "policy", 9, 0, 32, policy_mapping.id, policy_mapping.label
        )
        layout = StorageLayout(
            "borgCore",
            [variable],
            {
                uint_type.id: uint_type,
                bool_type.id: bool_type,
                method_type.id: method_type,
                methods_mapping.id: methods_mapping,
                policy_type.id: policy_type,
                policy_mapping.id: policy_mapping,
            },
        )

        owner = "0x" + "11" * 20
        selector = bytes.fromhex("8d80ff0a")
        outer_preimage = encode(["address", "uint256"], [owner, 9])
        policy_hash = int.from_bytes(Web3.keccak(outer_preimage), "big")
        methods_slot = policy_hash + 1
        inner_preimage = selector.ljust(32, b"\x00") + methods_slot.to_bytes(32, "big")
        method_hash = int.from_bytes(Web3.keccak(inner_preimage), "big")
        target_slot = method_hash + 3
        lookup = {
            f"0x{policy_hash:064x}": "0x" + outer_preimage.hex(),
            f"0x{method_hash:064x}": "0x" + inner_preimage.hex(),
        }

        resolver = SlotPathResolver()
        matches = list(
            resolver.find_struct_offset_matches(target_slot, layout, lookup)
        )

        self.assertEqual(len(matches), 1)
        offset, base_match = matches[0]
        self.assertEqual(offset, 3)
        self.assertEqual(
            base_match["path"],
            f"policy[{owner}].methods[0x{selector.hex()}]",
        )
        field_name, field_type = resolver.resolve_match_struct_field(
            base_match,
            offset,
            layout,
        )
        self.assertEqual(field_name, "lastExecutionTimestamp")
        self.assertIs(field_type, uint_type)

        tracer = TransactionAnalysisService(object(), Settings(), TypeDecoder())
        tracer.slot_resolver.get_struct_offsets = Mock(
            wraps=tracer.slot_resolver.get_struct_offsets
        )
        decoded = tracer._decode_changes(
            [
                (
                    f"0x{target_slot:064x}",
                    f"0x{1779904547:064x}",
                    f"0x{1780454411:064x}",
                    20869,
                    3523,
                )
            ],
            layout,
            lookup,
        )
        self.assertEqual(len(decoded), 1)
        self.assertEqual(
            decoded[0].variable_path,
            f"policy[{owner}].methods[0x{selector.hex()}].lastExecutionTimestamp",
        )
        self.assertEqual(decoded[0].value_type, uint_type.id)
        self.assertEqual(decoded[0].new_decoded.decoded, 1780454411)
        tracer.slot_resolver.get_struct_offsets.assert_called_once_with(layout)


class PackedArrayLayoutTests(unittest.TestCase):
    def setUp(self):
        self.element = StorageType(
            id="t_uint32",
            label="uint32",
            kind="value",
            encoding="inplace",
            num_bytes=4,
        )
        self.array = StorageType(
            id="t_array(t_uint32)10_storage",
            label="uint32[10]",
            kind="array",
            encoding="inplace",
            num_bytes=64,
            element_type="t_uint32",
            array_length=10,
        )
        self.variable = StorageVariable(
            name="values",
            slot=5,
            offset=0,
            size=64,
            type_id=self.array.id,
            label=self.array.label,
        )
        self.layout = StorageLayout(
            contract_name="Packed",
            variables=[self.variable],
            types={self.element.id: self.element, self.array.id: self.array},
        )

    def test_static_array_span_uses_packed_slot_count(self):
        index = LayoutIndex(self.layout)
        self.assertIsNotNone(index.first_at(5))
        self.assertIsNotNone(index.first_at(6))
        self.assertIsNone(index.first_at(7))

    def test_every_element_in_packed_word_has_exact_offset(self):
        locations = self.layout.get_static_array_locations(self.variable, 5)
        self.assertEqual([index for index, _ in locations], list(range(8)))
        self.assertEqual([location.byte_offset for _, location in locations], list(range(0, 32, 4)))

        tail = self.layout.get_static_array_locations(self.variable, 6)
        self.assertEqual([index for index, _ in tail], [8, 9])
        self.assertEqual([location.byte_offset for _, location in tail], [0, 4])

    def test_dynamic_array_location_uses_same_packing(self):
        packing = array_packing(self.element)
        self.assertEqual((packing.location(100, 9).slot, packing.location(100, 9).byte_offset), (101, 4))

    def test_bounded_vyper_dynamic_array_does_not_claim_unrelated_high_slot(self):
        dynamic_array = StorageType(
            id="DynArray[uint32, 10]",
            label="DynArray[uint32, 10]",
            kind="array",
            encoding="dynamic_array",
            num_bytes=96,
            element_type="t_uint32",
            array_length=10,
        )
        variable = StorageVariable(
            name="values",
            slot=3,
            offset=0,
            size=96,
            type_id=dynamic_array.id,
            label=dynamic_array.label,
        )
        layout = StorageLayout(
            contract_name="BoundedDynamic",
            variables=[variable],
            types={self.element.id: self.element, dynamic_array.id: dynamic_array},
        )
        resolver = SlotPathResolver()
        index = resolver.build_dynamic_array_index(layout)
        data_start = next(iter(index))

        self.assertIsNotNone(
            resolver.try_match_dynamic_array_slot(data_start + 1, layout, index)
        )
        self.assertIsNone(
            resolver.try_match_dynamic_array_slot(data_start + 2, layout, index)
        )

    def test_mapping_array_roots_are_reused_without_resorting(self):
        class NoIterationIndex(dict):
            def __iter__(self):
                raise AssertionError("mapping roots must be precomputed")

            def items(self):
                raise AssertionError("mapping roots must be precomputed")

        variable = StorageVariable(
            "values",
            0,
            0,
            32,
            self.array.id,
            self.array.label,
        )
        index = NoIterationIndex({
            100: {
                "array_length": 10,
                "array_packing": array_packing(self.element),
                "base_slot": 0,
                "element_type": self.element,
                "key": "1",
                "path": "values[1]",
                "variable": variable,
            }
        })

        match = SlotPathResolver().try_match_mapping_to_array_slot(
            100,
            self.layout,
            index,
            (100,),
        )

        self.assertEqual(match["path"], "values[1] (packed word)")

    def test_unbounded_dynamic_array_slots_require_proven_length(self):
        dynamic_array = StorageType(
            id="t_array(t_uint32)dyn_storage",
            label="uint32[]",
            kind="array",
            encoding="dynamic_array",
            num_bytes=32,
            element_type="t_uint32",
        )
        variable = StorageVariable(
            name="values",
            slot=3,
            offset=0,
            size=32,
            type_id=dynamic_array.id,
            label=dynamic_array.label,
        )
        layout = StorageLayout(
            contract_name="PackedDynamic",
            variables=[variable],
            types={self.element.id: self.element, dynamic_array.id: dynamic_array},
        )
        data_start = int.from_bytes(Web3.keccak(encode(["uint256"], [3])), "big")
        tracer = TransactionAnalysisService(object(), Settings(), TypeDecoder())
        changes = tracer._decode_changes(
            [
                (
                    f"0x{data_start:064x}",
                    "0x" + "00" * 32,
                    f"0x{7 << 32:064x}",
                    10,
                    20,
                )
            ],
            layout,
        )
        self.assertEqual(len(changes), 1)
        self.assertIsNone(changes[0].variable)
        self.assertIsNone(changes[0].variable_path)
        self.assertIsNone(changes[0].array_index)
        index = SlotPathResolver().build_dynamic_array_index(layout)
        self.assertIn(data_start, index)
        self.assertIsNone(
            SlotPathResolver().try_match_dynamic_array_slot(
                data_start,
                layout,
                index,
            )
        )

        changes = tracer._decode_changes(
            [
                (
                    f"0x{data_start:064x}",
                    "0x" + "00" * 32,
                    f"0x{7 << 32:064x}",
                    10,
                    20,
                )
            ],
            layout,
            storage_timelines={3: (2, ())},
        )
        self.assertEqual([change.variable_path for change in changes], ["values[1]"])

    def test_mixed_step_time_array_bounds_leave_grouped_slot_raw(self):
        dynamic_array = StorageType(
            id="t_array(t_uint32)dyn_storage",
            label="uint32[]",
            kind="array",
            encoding="dynamic_array",
            num_bytes=32,
            element_type=self.element.id,
        )
        variable = StorageVariable(
            name="values",
            slot=3,
            offset=0,
            size=32,
            type_id=dynamic_array.id,
            label=dynamic_array.label,
        )
        layout = StorageLayout(
            contract_name="PackedDynamic",
            variables=[variable],
            types={self.element.id: self.element, dynamic_array.id: dynamic_array},
        )
        data_start = int.from_bytes(Web3.keccak(encode(["uint256"], [3])), "big")
        tracer = TransactionAnalysisService(object(), Settings(), TypeDecoder())

        changes = tracer._decode_changes(
            [
                (
                    f"0x{data_start:064x}",
                    "0x" + "00" * 32,
                    f"0x{7 << 32:064x}",
                    10,
                    20,
                ),
                (
                    f"0x{data_start:064x}",
                    f"0x{7 << 32:064x}",
                    f"0x{8 << 32:064x}",
                    11,
                    30,
                ),
            ],
            layout,
            storage_timelines={3: (2, ((25, 1),))},
        )

        self.assertTrue(all(change.variable is None for change in changes))
        self.assertTrue(all(change.variable_path is None for change in changes))


if __name__ == "__main__":
    unittest.main()
