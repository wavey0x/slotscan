import unittest
from dataclasses import FrozenInstanceError

from app.models.domain import StorageLayout, StorageType, StorageVariable
from app.services.compiled_layout import (
    UnsupportedCompiledLayout,
    compile_layout,
)


def _layout(
    *,
    language: str = "Solidity",
    compiler_version: str = "0.8.30",
    storage_scheme: str = "solidity",
) -> StorageLayout:
    mapping = StorageType(
        id="mapping",
        label="mapping(address => uint256)",
        kind="mapping",
        encoding="mapping",
        num_bytes=32,
        key_type="t_address",
        value_type="t_uint256",
    )
    return StorageLayout(
        contract_name="Fixture",
        variables=[
            StorageVariable(
                "balance",
                2**255,
                0,
                32,
                "t_uint256",
                "uint256",
            ),
            StorageVariable(
                "balances",
                7,
                0,
                32,
                mapping.id,
                mapping.label,
            ),
        ],
        types={mapping.id: mapping},
        language=language,
        compiler_version=compiler_version,
        storage_scheme=storage_scheme,
    )


class CompiledLayoutTests(unittest.TestCase):
    def test_canonical_layout_has_ordinal_ids_and_string_safe_slots(self):
        compiled = compile_layout(_layout())

        wire = compiled.canonical_wire()

        self.assertEqual(
            [variable["declaration_id"] for variable in wire["variables"]],
            ["decl:0", "decl:1"],
        )
        self.assertEqual(wire["variables"][1]["slot"], hex(2**255))
        self.assertTrue(compiled.layout_id.startswith("sha256:"))
        self.assertIn("t_address", wire["types"])
        self.assertIn("t_uint256", wire["types"])

    def test_layout_is_deeply_immutable_and_detached_from_input(self):
        source = _layout()
        compiled = compile_layout(source)
        original_wire = compiled.canonical_wire()

        source.variables[0].name = "changed"
        source.types["mapping"].key_type = None

        self.assertEqual(compiled.canonical_wire(), original_wire)
        with self.assertRaises(TypeError):
            compiled.types["new"] = compiled.types["t_uint256"]
        with self.assertRaises(FrozenInstanceError):
            compiled.variables[0].name = "changed"

    def test_source_order_does_not_change_canonical_identity(self):
        first = _layout()
        second = _layout()
        second.variables.reverse()
        second.types = dict(reversed(list(second.types.items())))

        self.assertEqual(
            compile_layout(first).layout_id,
            compile_layout(second).layout_id,
        )

    def test_normalized_locator_semantics_are_identity_bearing(self):
        solidity = compile_layout(_layout())
        vyper = compile_layout(
            _layout(
                language="Vyper",
                compiler_version="0.3.10",
                storage_scheme="vyper_sequential",
            )
        )
        equivalent_vyper = compile_layout(
            _layout(
                language="Vyper",
                compiler_version="0.3.7",
                storage_scheme="vyper_sequential",
            )
        )

        self.assertNotEqual(solidity.layout_id, vyper.layout_id)
        self.assertEqual(vyper.layout_id, equivalent_vyper.layout_id)

    def test_missing_references_and_invalid_ranges_fail_closed(self):
        missing = _layout()
        missing.variables[0].type_id = "unknown"
        invalid = _layout()
        invalid.variables[0].slot = 2**256

        for layout in (missing, invalid):
            with self.subTest(layout=layout):
                with self.assertRaises(UnsupportedCompiledLayout):
                    compile_layout(layout)

    def test_unknown_rule_evidence_is_an_unsupported_compiled_layout(self):
        unsupported = _layout(
            language="Vyper",
            compiler_version="0.3.9",
            storage_scheme="vyper_sequential",
        )

        with self.assertRaisesRegex(
            UnsupportedCompiledLayout,
            "fixture-backed Vyper rules",
        ):
            compile_layout(unsupported)


if __name__ == "__main__":
    unittest.main()
