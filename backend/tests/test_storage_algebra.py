import unittest

from eth_abi import encode
from web3 import Web3

from app.models.domain import StorageLayout, StorageType, StorageVariable
from app.services.layout_index import LayoutIndex, array_packing
from app.config import Settings
from app.services.decoder import TypeDecoder
from app.services.tracer.tracer import TransactionTracer
from app.services.tracer.slot_resolver import SlotResolver
from app.utils.slots import compute_mapping_slot, encode_mapping_key


class MappingSlotTests(unittest.TestCase):
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
