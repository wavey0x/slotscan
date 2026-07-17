import unittest

from app.models.domain import StorageLayout, StorageType, StorageVariable
from app.models.errors import RPCError
from app.services.compiled_layout import compile_layout
from app.services.namespace_storage import NamespaceStorageParser
from app.services.storage import StorageReader, plan_compiled_scalar_reads


ZERO_WORD = "0x" + "00" * 32


def uint_word(value: int) -> str:
    return f"0x{value:064x}"


def _compiled(variables, types):
    return compile_layout(
        StorageLayout(
            contract_name="Reader",
            variables=variables,
            types=types,
            language="Solidity",
            compiler_version="0.8.30",
            storage_scheme="solidity",
        )
    )


class _StorageProvider:
    def __init__(self, values: dict[int, str] | None = None):
        self.values = values or {}
        self.requested_slots: list[int] = []

    async def batch_get_storage_at(
        self,
        chain_id: int,
        address: str,
        slots: list[int],
        block: int,
        batch_size: int = 100,
    ) -> dict[int, str]:
        self.requested_slots = slots
        return {slot: self.values.get(slot, ZERO_WORD) for slot in slots}


class ScalarReadPlanningTests(unittest.TestCase):
    def test_packed_consumers_share_one_first_seen_word(self):
        layout = _compiled(
            [
                StorageVariable("enabled", 7, 0, 1, "t_bool", "bool"),
                StorageVariable("owner", 7, 1, 20, "t_address", "address"),
                StorageVariable("count", 3, 0, 32, "t_uint256", "uint256"),
            ],
            {},
        )

        plan = plan_compiled_scalar_reads(layout)

        self.assertEqual(plan.words, (3, 7))
        self.assertEqual(
            [projection.path for projection in plan.projections],
            ["count", "enabled", "owner"],
        )

    def test_aggregate_paths_are_explicit_and_not_scheduled(self):
        layout = _compiled(
            [
                StorageVariable("balances", 0, 0, 32, "mapping", "mapping"),
                StorageVariable("items", 1, 0, 64, "array", "uint256[2]"),
                StorageVariable("name", 3, 0, 32, "string", "string"),
            ],
            {
                "mapping": StorageType(
                    "mapping",
                    "mapping(address => uint256)",
                    "mapping",
                    "mapping",
                    key_type="t_address",
                    value_type="t_uint256",
                ),
                "array": StorageType(
                    "array",
                    "uint256[2]",
                    "array",
                    "inplace",
                    num_bytes=64,
                    element_type="t_uint256",
                    array_length=2,
                ),
                "string": StorageType(
                    "string",
                    "string",
                    "value",
                    "bytes",
                    num_bytes=32,
                ),
            },
        )

        plan = plan_compiled_scalar_reads(layout)

        self.assertEqual(plan.words, ())
        self.assertEqual(
            [(projection.path, projection.status) for projection in plan.projections],
            [
                ("balances", "on_demand"),
                ("items", "on_demand"),
                ("name", "unsupported"),
            ],
        )

    def test_aggregate_queries_include_packed_struct_mappings_only(self):
        packed_struct = StorageType(
            "config",
            "struct Config",
            "struct",
            "inplace",
            num_bytes=32,
            members=[
                StorageVariable("limit", 0, 0, 32, "t_uint256", "uint256")
            ],
        )
        packed_mapping = StorageType(
            "configs",
            "mapping(address => struct Config)",
            "mapping",
            "mapping",
            num_bytes=32,
            key_type="t_address",
            value_type=packed_struct.id,
        )
        wide_struct = StorageType(
            "wide_config",
            "struct WideConfig",
            "struct",
            "inplace",
            num_bytes=64,
            members=[
                StorageVariable("first", 0, 0, 32, "t_uint256", "uint256"),
                StorageVariable("second", 1, 0, 32, "t_uint256", "uint256"),
            ],
        )
        wide_mapping = StorageType(
            "wide_configs",
            "mapping(address => struct WideConfig)",
            "mapping",
            "mapping",
            num_bytes=32,
            key_type="t_address",
            value_type=wide_struct.id,
        )
        array = StorageType(
            "config_array",
            "struct Config[]",
            "array",
            "dynamic_array",
            num_bytes=32,
            element_type=packed_struct.id,
        )
        layout = _compiled(
            [
                StorageVariable(
                    "configs",
                    0,
                    0,
                    32,
                    packed_mapping.id,
                    packed_mapping.label,
                ),
                StorageVariable(
                    "configList",
                    1,
                    0,
                    32,
                    array.id,
                    array.label,
                ),
                StorageVariable(
                    "wideConfigs",
                    2,
                    0,
                    32,
                    wide_mapping.id,
                    wide_mapping.label,
                ),
            ],
            {
                packed_struct.id: packed_struct,
                packed_mapping.id: packed_mapping,
                wide_struct.id: wide_struct,
                wide_mapping.id: wide_mapping,
                array.id: array,
            },
        )

        plan = plan_compiled_scalar_reads(layout)

        self.assertEqual(
            [(projection.path, projection.status) for projection in plan.projections],
            [
                ("configs", "on_demand"),
                ("configList", "unsupported"),
                ("wideConfigs", "unsupported"),
            ],
        )

    def test_budget_defers_new_words_but_keeps_shared_consumers(self):
        layout = _compiled(
            [
                StorageVariable("a", 5, 0, 1, "t_bool", "bool"),
                StorageVariable("b", 6, 0, 32, "t_uint256", "uint256"),
                StorageVariable("c", 5, 1, 1, "t_bool", "bool"),
            ],
            {},
        )

        plan = plan_compiled_scalar_reads(layout, max_words=1)

        self.assertEqual(plan.words, (5,))
        self.assertEqual(
            [(projection.path, projection.status) for projection in plan.projections],
            [("a", "pending"), ("c", "pending"), ("b", "deferred_budget")],
        )

    def test_vyper_bounded_strings_are_not_read_initially(self):
        for version in ("0.2.4", "0.3.10"):
            with self.subTest(version=version):
                source = NamespaceStorageParser().parse_vyper_storage(
                    {
                        "Token.vy": (
                            f"# @version {version}\n"
                            "name: public(String[64])\n"
                        )
                    },
                    "Token",
                    version,
                )
                layout = compile_layout(source)

                plan = plan_compiled_scalar_reads(layout)

                self.assertEqual(plan.words, ())
                self.assertTrue(
                    all(projection.status == "unsupported" for projection in plan.projections)
                )


class ScalarStorageReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_deduplicates_in_first_seen_order(self):
        provider = _StorageProvider({1: uint_word(1), 2: uint_word(2)})
        reader = StorageReader(provider)

        values = await reader.read_slots_batch(
            1,
            "0x" + "44" * 20,
            [2, 1, 2, 1],
            123,
        )

        self.assertEqual(provider.requested_slots, [2, 1])
        self.assertEqual(list(values), [2, 1])

    async def test_incomplete_or_malformed_batch_returns_no_values(self):
        class _IncompleteProvider(_StorageProvider):
            async def batch_get_storage_at(self, *args, **kwargs):
                return {1: ZERO_WORD}

        class _MalformedProvider(_StorageProvider):
            async def batch_get_storage_at(self, *args, **kwargs):
                return {1: "0x01"}

        for provider in (_IncompleteProvider(), _MalformedProvider()):
            with self.subTest(provider=type(provider).__name__):
                reader = StorageReader(provider)
                with self.assertRaises(RPCError):
                    await reader.read_slots_batch(
                        1,
                        "0x" + "55" * 20,
                        [1, 2] if isinstance(provider, _IncompleteProvider) else [1],
                        123,
                    )


if __name__ == "__main__":
    unittest.main()
