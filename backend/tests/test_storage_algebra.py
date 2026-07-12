import unittest

from eth_abi import encode
from web3 import Web3

from app.models.domain import StorageLayout, StorageType, StorageVariable
from app.services.layout_index import LayoutIndex, array_packing
from app.config import Settings
from app.services.decoder import TypeDecoder
from app.services.tracer.tracer import TransactionTracer
from app.services.tracer.slot_resolver import SlotResolver
from app.services.tracer.preimage_resolver import PreimageResolver
from app.utils.slots import compute_mapping_slot, encode_mapping_key


class MappingSlotTests(unittest.TestCase):
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
        match = SlotResolver().try_match_slot_from_preimage(
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

        match = SlotResolver().try_match_slot_from_preimage(
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

        match = SlotResolver().try_match_slot_from_preimage(
            inner_hash,
            lookup[inner_hash],
            layout,
            lookup,
        )

        self.assertEqual(match["path"], f"configs[{outer_key}][{inner_key}]")

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

        match = SlotResolver().try_match_slot_from_preimage(
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
            TransactionTracer._vyper_layout_evidence_conflicts(
                layout,
                raw_changes,
                lookup,
            ),
            [24],
        )
        tracer = TransactionTracer(None, Settings(), TypeDecoder())
        self.assertIsNone(
            tracer._decode_changes(raw_changes, layout, lookup)[0].variable_path
        )

        variable.slot = 24
        self.assertEqual(
            TransactionTracer._vyper_layout_evidence_conflicts(
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

        class CountingResolver(SlotResolver):
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

        resolver = SlotResolver()
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

        tracer = TransactionTracer(object(), Settings(), TypeDecoder())
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
        resolver = SlotResolver()
        index = resolver.build_dynamic_array_index(layout)
        data_start = next(iter(index))

        self.assertIsNotNone(
            resolver.try_match_dynamic_array_slot(data_start + 1, layout, index)
        )
        self.assertIsNone(
            resolver.try_match_dynamic_array_slot(data_start + 2, layout, index)
        )

    def test_dynamic_array_diff_resolves_changed_packed_element(self):
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
        tracer = TransactionTracer(object(), Settings(), TypeDecoder())
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
        self.assertEqual(changes[0].variable_path, "values[1]")
        self.assertEqual(changes[0].array_index, 1)
        self.assertEqual(changes[0].old_decoded.decoded, 0)
        self.assertEqual(changes[0].new_decoded.decoded, 7)


if __name__ == "__main__":
    unittest.main()
