import unittest

from app.models.domain import StorageLayout, StorageType, StorageVariable
from app.services.decoder import TypeDecoder
from app.services.storage_rules import (
    UnsupportedStorageRules,
    compute_mapping_slot,
    compute_solidity_mapping_slot,
    compute_vyper_mapping_slot,
    encode_mapping_key,
    storage_rules_for_layout,
)


ADDRESS_KEY = "0x1111111111111111111111111111111111111111"
SOLIDITY_ADDRESS_SLOT = (
    "07315875c131dc1dff59b5eecd3feba7c4eb34f9c8bac4a22e69acd1d04d63c5"
)
VYPER_ADDRESS_SLOT = (
    "bc2904ac11591170e46e75e1b6082c469d2f48b47235687e687e157e758728a0"
)


def _layout(
    *,
    language: str | None,
    compiler_version: str | None,
    storage_scheme: str | None,
) -> StorageLayout:
    return StorageLayout(
        contract_name="Fixture",
        variables=[],
        types={},
        language=language,
        compiler_version=compiler_version,
        storage_scheme=storage_scheme,
    )


class MappingRuleTests(unittest.TestCase):
    def test_literal_solidity_mapping_vector(self):
        encoded = encode_mapping_key("address", ADDRESS_KEY)

        actual = compute_solidity_mapping_slot(7, encoded)

        self.assertEqual(f"{actual:064x}", SOLIDITY_ADDRESS_SLOT)

    def test_literal_vyper_mapping_vectors(self):
        encoded = encode_mapping_key("address", ADDRESS_KEY)
        for compiler_version, storage_scheme in (
            ("0.2.4", "vyper_legacy_hashed"),
            ("0.3.7", "vyper_sequential"),
            ("0.3.10", "vyper_sequential"),
        ):
            with self.subTest(compiler_version=compiler_version):
                layout = _layout(
                    language="Vyper",
                    compiler_version=compiler_version,
                    storage_scheme=storage_scheme,
                )

                actual = compute_mapping_slot(layout, 7, "address", ADDRESS_KEY)

                self.assertEqual(f"{actual:064x}", VYPER_ADDRESS_SLOT)
                self.assertEqual(
                    actual,
                    compute_vyper_mapping_slot(7, encoded),
                )

    def test_rule_evidence_and_key_types_fail_closed(self):
        unsupported = (
            _layout(
                language=None,
                compiler_version="0.8.30",
                storage_scheme="solidity",
            ),
            _layout(
                language="Vyper",
                compiler_version="0.3.9",
                storage_scheme="vyper_sequential",
            ),
            _layout(
                language="Solidity",
                compiler_version=None,
                storage_scheme="solidity",
            ),
        )
        for layout in unsupported:
            with self.subTest(layout=layout):
                with self.assertRaises(UnsupportedStorageRules):
                    storage_rules_for_layout(layout)

        with self.assertRaises(ValueError):
            encode_mapping_key("", ADDRESS_KEY)
        with self.assertRaises(ValueError):
            encode_mapping_key("unknown", ADDRESS_KEY)


class PureTypeLookupTests(unittest.TestCase):
    def test_layout_lookup_and_decoder_do_not_mutate_input_types(self):
        member = StorageVariable(
            "owner",
            0,
            0,
            20,
            "t_address",
            "address",
        )
        struct = StorageType(
            "owner_struct",
            "Owner",
            "struct",
            "inplace",
            num_bytes=32,
            members=[member],
        )
        layout = StorageLayout(
            contract_name="Types",
            variables=[],
            types={"owner_struct": struct},
        )
        before = layout.to_dict()

        synthesized = layout.get_type("t_uint256")
        decoded = TypeDecoder(layout.types).decode(
            bytes.fromhex("00" * 12 + "11" * 20),
            struct,
        )

        self.assertEqual(synthesized.label, "uint256")
        self.assertEqual(
            decoded.decoded["owner"].lower(),
            "0x1111111111111111111111111111111111111111",
        )
        self.assertEqual(layout.to_dict(), before)
        self.assertNotIn("t_uint256", layout.types)
        self.assertNotIn("t_address", layout.types)


if __name__ == "__main__":
    unittest.main()
