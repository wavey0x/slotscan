import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

from fastapi import HTTPException
from web3 import Web3

from app.api.routes.layout_comparisons import get_layout_comparison
from app.models.api import LayoutComparisonResponse
from app.models.domain import (
    ContractMetadata,
    StorageLayout,
    StorageScope,
    StorageType,
    StorageVariable,
)
from app.models.errors import NotAContractError
from app.services.compiled_layout import compile_layout
from app.services.layout import LayoutParser
from app.services.layout_compatibility.compare import LayoutComparator
from app.services.layout_compatibility.models import ComparisonVerdict
from app.services.layout_compatibility.normalize import LayoutNormalizer
from app.services.layout_compatibility.service import LayoutComparisonService
from app.services.namespace_storage import (
    NamespaceStorageParser,
    compute_erc7201_root,
)
from app.services.storage_view import StorageContext
from app.services.web3_provider import BlockRef, StorageAttempt


BLOCK_HASH = "0x" + "ab" * 32
FROM = "0x" + "11" * 20
TO = "0x" + "22" * 20
FIXTURES = Path(__file__).parent / "fixtures" / "layout_compatibility"


def scalar(
    type_id: str = "t_uint256",
    label: str = "uint256",
    size: int = 32,
) -> StorageType:
    return StorageType(type_id, label, "value", "inplace", size)


def layout(
    variables: list[StorageVariable],
    types: dict[str, StorageType] | None = None,
    *,
    scopes: list[StorageScope] | None = None,
    language: str = "Solidity",
) -> StorageLayout:
    return StorageLayout(
        contract_name="Fixture",
        variables=variables,
        types=types or {},
        language=language,
        compiler_version="0.8.30",
        storage_scheme="solidity",
        scopes=scopes or [],
    )


def variable(
    name: str,
    slot: int,
    type_id: str = "t_uint256",
    label: str = "uint256",
    *,
    offset: int = 0,
    size: int = 32,
    scope_id: str = "default",
    provenance: str = "compiler_layout",
    confidence: str = "exact",
) -> StorageVariable:
    return StorageVariable(
        name,
        slot,
        offset,
        size,
        type_id,
        label,
        provenance,
        confidence,
        scope_id,
    )


class ComparatorTests(unittest.TestCase):
    def compare(
        self,
        from_layout: StorageLayout,
        to_layout: StorageLayout,
        *,
        normalizer: LayoutNormalizer | None = None,
    ):
        return LayoutComparator(normalizer=normalizer).compare(
            compile_layout(from_layout),
            compile_layout(to_layout),
        )

    def test_identical_layout_is_deterministic_and_string_safe(self):
        high = 2**255
        source = layout([variable("owner", high)])

        first = self.compare(source, source)
        second = self.compare(source, source)

        self.assertEqual(first.verdict, ComparisonVerdict.NO_CONFLICTS)
        self.assertEqual(first.summary.unchanged, 1)
        self.assertEqual(first.entries, second.entries)
        self.assertEqual(
            first.entries[0].to_wire()["from_region"]["location"]["slot"],
            hex(high),
        )

    def test_tail_addition_is_directional_and_reversal_is_removal(self):
        before = layout([variable("owner", 0)])
        after = layout([variable("owner", 0), variable("paused", 1)])

        forward = self.compare(before, after)
        reverse = self.compare(after, before)

        self.assertEqual(forward.verdict, ComparisonVerdict.NO_CONFLICTS)
        self.assertEqual([entry.kind for entry in forward.entries], [
            "unchanged",
            "addition",
        ])
        self.assertEqual(forward.summary.changes, 1)
        self.assertEqual(reverse.verdict, ComparisonVerdict.CONFLICTS)
        self.assertIn("removed", [entry.kind for entry in reverse.entries])

    def test_move_packing_and_encoding_changes_are_conflicts(self):
        uint = scalar()
        byte = scalar("t_uint8", "uint8", 1)
        cases = (
            (
                layout([variable("owner", 0)]),
                layout([variable("owner", 2)]),
                "moved",
            ),
            (
                layout(
                    [variable("small", 0, byte.id, byte.label, size=1)],
                    {byte.id: byte},
                ),
                layout([variable("small", 0)]),
                "shape_changed",
            ),
            (
                layout(
                    [variable("data", 0, "t_bytes_storage", "bytes")],
                    {
                        "t_bytes_storage": StorageType(
                            "t_bytes_storage",
                            "bytes",
                            "value",
                            "bytes",
                            32,
                        )
                    },
                ),
                layout([variable("data", 0)], {uint.id: uint}),
                "shape_changed",
            ),
        )
        for source, target, kind in cases:
            with self.subTest(kind=kind):
                result = self.compare(source, target)
                self.assertEqual(result.verdict, ComparisonVerdict.CONFLICTS)
                self.assertIn(kind, [entry.kind for entry in result.entries])

    def test_string_bytes_and_recursive_shapes_are_compared_symbolically(self):
        string_type = StorageType(
            "t_string_storage",
            "string",
            "value",
            "bytes",
            32,
        )
        bytes_type = StorageType(
            "t_bytes_storage",
            "bytes",
            "value",
            "bytes",
            32,
        )
        equivalent = self.compare(
            layout(
                [
                    variable(
                        "data",
                        0,
                        string_type.id,
                        string_type.label,
                    )
                ],
                {string_type.id: string_type},
            ),
            layout(
                [
                    variable(
                        "data",
                        0,
                        bytes_type.id,
                        bytes_type.label,
                    )
                ],
                {bytes_type.id: bytes_type},
            ),
        )

        recursive = StorageType(
            "recursive_mapping",
            "mapping(address => Recursive)",
            "mapping",
            "mapping",
            32,
            key_type="t_address",
            value_type="recursive_mapping",
        )
        recursive_layout = layout(
            [
                variable(
                    "links",
                    0,
                    recursive.id,
                    recursive.label,
                )
            ],
            {
                recursive.id: recursive,
                "t_address": scalar("t_address", "address", 20),
            },
        )
        first = self.compare(recursive_layout, recursive_layout)
        second = self.compare(recursive_layout, recursive_layout)

        self.assertEqual(
            equivalent.verdict,
            ComparisonVerdict.INDETERMINATE,
        )
        self.assertEqual(
            equivalent.entries[0].kind,
            "nominal_type_changed",
        )
        self.assertEqual(first.verdict, ComparisonVerdict.NO_CONFLICTS)
        self.assertEqual(first.entries, second.entries)

    def test_names_and_nominal_labels_are_ambiguous_not_conflicts(self):
        alias = scalar("t_alias", "Amount", 32)
        address = scalar("t_address", "address", 20)
        contract = StorageType(
            "t_contract$_Token_$1",
            "contract Token",
            "contract",
            "inplace",
            20,
        )
        renamed = self.compare(
            layout([variable("owner", 0)]),
            layout([variable("admin", 0)]),
        )
        nominal = self.compare(
            layout([variable("amount", 0)]),
            layout(
                [variable("amount", 0, alias.id, alias.label)],
                {alias.id: alias},
            ),
        )
        contract_address = self.compare(
            layout(
                [
                    variable(
                        "token",
                        0,
                        contract.id,
                        contract.label,
                        size=20,
                    )
                ],
                {contract.id: contract},
            ),
            layout(
                [
                    variable(
                        "token",
                        0,
                        address.id,
                        address.label,
                        size=20,
                    )
                ],
                {address.id: address},
            ),
        )

        self.assertEqual(renamed.verdict, ComparisonVerdict.INDETERMINATE)
        self.assertEqual(renamed.entries[0].kind, "name_changed")
        self.assertEqual(nominal.verdict, ComparisonVerdict.INDETERMINATE)
        self.assertEqual(nominal.entries[0].kind, "nominal_type_changed")
        self.assertEqual(
            contract_address.verdict,
            ComparisonVerdict.INDETERMINATE,
        )
        self.assertEqual(
            contract_address.entries[0].kind,
            "nominal_type_changed",
        )

    def test_mapping_key_and_dynamic_array_stride_changes_conflict(self):
        uint = scalar()
        address = scalar("t_address", "address", 20)
        contract = StorageType(
            "t_contract$_Token_$1",
            "contract Token",
            "contract",
            "inplace",
            20,
        )
        bytes20 = scalar("t_bytes20", "bytes20", 20)
        bytes32 = scalar("t_bytes32", "bytes32", 32)
        mapping_from = StorageType(
            "mapping_from",
            "mapping(address => uint256)",
            "mapping",
            "mapping",
            32,
            key_type=address.id,
            value_type=uint.id,
        )
        mapping_to = StorageType(
            "mapping_to",
            "mapping(bytes32 => uint256)",
            "mapping",
            "mapping",
            32,
            key_type=bytes32.id,
            value_type=uint.id,
        )
        map_result = self.compare(
            layout(
                [variable("balances", 0, mapping_from.id, mapping_from.label)],
                {
                    mapping_from.id: mapping_from,
                    address.id: address,
                    uint.id: uint,
                },
            ),
            layout(
                [variable("balances", 0, mapping_to.id, mapping_to.label)],
                {
                    mapping_to.id: mapping_to,
                    bytes32.id: bytes32,
                    uint.id: uint,
                },
            ),
        )
        small = scalar("small", "uint128", 16)
        array_from = StorageType(
            "array_from",
            "uint128[]",
            "array",
            "dynamic_array",
            32,
            element_type=small.id,
        )
        array_to = StorageType(
            "array_to",
            "uint256[]",
            "array",
            "dynamic_array",
            32,
            element_type=uint.id,
        )
        array_result = self.compare(
            layout(
                [variable("items", 0, array_from.id, array_from.label)],
                {array_from.id: array_from, small.id: small},
            ),
            layout(
                [variable("items", 0, array_to.id, array_to.label)],
                {array_to.id: array_to, uint.id: uint},
            ),
        )

        self.assertEqual(map_result.entries[0].kind, "mapping_key_changed")
        self.assertEqual(map_result.verdict, ComparisonVerdict.CONFLICTS)
        self.assertEqual(array_result.entries[0].kind, "array_rule_changed")
        self.assertEqual(array_result.verdict, ComparisonVerdict.CONFLICTS)

        for target_key, expected in (
            (contract, ComparisonVerdict.INDETERMINATE),
            (bytes20, ComparisonVerdict.CONFLICTS),
        ):
            target_mapping = StorageType(
                f"mapping_to_{target_key.id}",
                f"mapping({target_key.label} => uint256)",
                "mapping",
                "mapping",
                32,
                key_type=target_key.id,
                value_type=uint.id,
            )
            result = self.compare(
                layout(
                    [
                        variable(
                            "balances",
                            0,
                            mapping_from.id,
                            mapping_from.label,
                        )
                    ],
                    {
                        mapping_from.id: mapping_from,
                        address.id: address,
                        uint.id: uint,
                    },
                ),
                layout(
                    [
                        variable(
                            "balances",
                            0,
                            target_mapping.id,
                            target_mapping.label,
                        )
                    ],
                    {
                        target_mapping.id: target_mapping,
                        target_key.id: target_key,
                        uint.id: uint,
                    },
                ),
            )
            with self.subTest(target_key=target_key.label):
                self.assertEqual(result.verdict, expected)
                self.assertEqual(
                    result.entries[0].kind,
                    (
                        "nominal_type_changed"
                        if expected is ComparisonVerdict.INDETERMINATE
                        else "mapping_key_changed"
                    ),
                )

    def test_fixed_array_and_struct_extensions_emit_actionable_changes(self):
        uint = scalar()
        array_two = StorageType(
            "array_two",
            "uint256[2]",
            "array",
            "inplace",
            64,
            element_type=uint.id,
            array_length=2,
        )
        array_four = StorageType(
            "array_four",
            "uint256[4]",
            "array",
            "inplace",
            128,
            element_type=uint.id,
            array_length=4,
        )
        array_result = self.compare(
            layout(
                [
                    variable(
                        "values",
                        0,
                        array_two.id,
                        array_two.label,
                        size=64,
                    )
                ],
                {array_two.id: array_two, uint.id: uint},
            ),
            layout(
                [
                    variable(
                        "values",
                        0,
                        array_four.id,
                        array_four.label,
                        size=128,
                    )
                ],
                {array_four.id: array_four, uint.id: uint},
            ),
        )

        struct_one = StorageType(
            "struct_one",
            "struct Config",
            "struct",
            "inplace",
            32,
            members=[variable("owner", 0)],
        )
        struct_two = StorageType(
            "struct_two",
            "struct Config",
            "struct",
            "inplace",
            64,
            members=[variable("owner", 0), variable("limit", 1)],
        )
        struct_result = self.compare(
            layout(
                [variable("config", 0, struct_one.id, struct_one.label)],
                {struct_one.id: struct_one, uint.id: uint},
            ),
            layout(
                [
                    variable(
                        "config",
                        0,
                        struct_two.id,
                        struct_two.label,
                        size=64,
                    )
                ],
                {struct_two.id: struct_two, uint.id: uint},
            ),
        )

        self.assertEqual(array_result.verdict, ComparisonVerdict.NO_CONFLICTS)
        self.assertIn("array_extended", [entry.kind for entry in array_result.entries])
        reduced = self.compare(
            layout(
                [
                    variable(
                        "values",
                        0,
                        array_four.id,
                        array_four.label,
                        size=128,
                    )
                ],
                {array_four.id: array_four, uint.id: uint},
            ),
            layout(
                [
                    variable(
                        "values",
                        0,
                        array_two.id,
                        array_two.label,
                        size=64,
                    )
                ],
                {array_two.id: array_two, uint.id: uint},
            ),
        )
        self.assertEqual(reduced.verdict, ComparisonVerdict.CONFLICTS)
        self.assertIn("array_reduced", [entry.kind for entry in reduced.entries])
        self.assertEqual(struct_result.verdict, ComparisonVerdict.NO_CONFLICTS)
        self.assertEqual(
            [entry.kind for entry in struct_result.entries],
            ["unchanged", "addition"],
        )
        self.assertTrue(
            all(".limit" not in (entry.from_region.path if entry.from_region else "")
                for entry in struct_result.entries)
        )

    def test_recognized_gap_consumption_is_non_conflicting(self):
        uint = scalar()
        gap_three = StorageType(
            "gap_three",
            "uint256[3]",
            "array",
            "inplace",
            96,
            element_type=uint.id,
            array_length=3,
        )
        gap_two = StorageType(
            "gap_two",
            "uint256[2]",
            "array",
            "inplace",
            64,
            element_type=uint.id,
            array_length=2,
        )
        result = self.compare(
            layout(
                [
                    variable("owner", 0),
                    variable(
                        "__gap",
                        1,
                        gap_three.id,
                        gap_three.label,
                        size=96,
                    ),
                ],
                {gap_three.id: gap_three, uint.id: uint},
            ),
            layout(
                [
                    variable("owner", 0),
                    variable("paused", 1),
                    variable(
                        "__gap",
                        2,
                        gap_two.id,
                        gap_two.label,
                        size=64,
                    ),
                ],
                {gap_two.id: gap_two, uint.id: uint},
            ),
        )

        self.assertEqual(result.verdict, ComparisonVerdict.NO_CONFLICTS)
        self.assertIn("gap_consumed", [entry.kind for entry in result.entries])

    def test_exact_erc7201_scopes_compare_by_root_and_identifier(self):
        root = 2**255
        source_scope = StorageScope(
            "erc7201:one",
            "erc7201",
            root,
            "erc7201:one",
        )
        renamed_scope = StorageScope(
            "erc7201:renamed",
            "erc7201",
            root,
            "erc7201:renamed",
        )
        default = StorageScope("default", "default", 0)
        source = layout(
            [variable("owner", root, scope_id=source_scope.id)],
            scopes=[default, source_scope],
        )
        renamed = layout(
            [variable("owner", root, scope_id=renamed_scope.id)],
            scopes=[default, renamed_scope],
        )

        result = self.compare(source, renamed)

        self.assertEqual(result.verdict, ComparisonVerdict.INDETERMINATE)
        self.assertIn("scope_label_changed", [entry.kind for entry in result.entries])

    def test_non_exact_vyper_and_bounded_recursion_fail_closed(self):
        inferred = layout(
            [
                variable(
                    "owner",
                    0,
                    provenance="source_inference",
                    confidence="inferred",
                )
            ]
        )
        non_exact = self.compare(inferred, inferred)
        vyper_from = layout([variable("owner", 0)], language="Vyper")
        vyper_to = layout([variable("owner", 0)], language="Vyper")
        for vyper_layout in (vyper_from, vyper_to):
            vyper_layout.compiler_version = "0.3.10"
            vyper_layout.storage_scheme = "vyper_sequential"
        vyper = self.compare(vyper_from, vyper_to)

        uint = scalar()
        mapping = StorageType(
            "mapping",
            "mapping(address => uint256)",
            "mapping",
            "mapping",
            32,
            key_type="t_address",
            value_type=uint.id,
        )
        bounded_layout = layout(
            [variable("values", 0, mapping.id, mapping.label)],
            {
                mapping.id: mapping,
                "t_address": scalar("t_address", "address", 20),
                uint.id: uint,
            },
        )
        bounded = self.compare(
            bounded_layout,
            bounded_layout,
            normalizer=LayoutNormalizer(max_visited_types=1),
        )

        self.assertEqual(non_exact.limitations, ("non_exact_layout",))
        self.assertEqual(vyper.limitations, ("unsupported_language",))
        self.assertEqual(bounded.verdict, ComparisonVerdict.UNAVAILABLE)
        self.assertEqual(bounded.limitations, ("analysis_limit",))

    def test_overlapping_untrusted_declarations_are_unavailable(self):
        overlapping = layout(
            [
                variable("first", 0, size=20),
                variable("second", 0, offset=10, size=20),
            ]
        )

        result = self.compare(overlapping, overlapping)

        self.assertEqual(result.verdict, ComparisonVerdict.UNAVAILABLE)
        self.assertEqual(result.limitations, ("invalid_layout",))


class ExactNamespaceTests(unittest.TestCase):
    def test_checked_in_mainnet_case_matrix_is_exact_and_complete(self):
        matrix = json.loads(
            (FIXTURES / "mainnet_comparison_cases.json").read_text()
        )
        cases = {item["id"]: item for item in matrix["cases"]}

        self.assertEqual(
            set(cases),
            {
                "usdc-implementation-pair",
                "usdc-proxy-and-implementation",
                "metamask-eip7702-authority-and-delegate",
                "usds-exact-erc7201",
            },
        )
        for case in cases.values():
            self.assertTrue(Web3.is_checksum_address(case["from_address"]))
            self.assertTrue(Web3.is_checksum_address(case["to_address"]))
            self.assertGreater(case["block_ref"]["number"], 0)
            self.assertRegex(
                case["block_ref"]["hash"],
                r"^0x[0-9a-f]{64}$",
            )
        usds = json.loads(
            (FIXTURES / "usds_erc7201.json").read_text()
        )
        self.assertEqual(
            cases["usds-exact-erc7201"]["to_address"],
            usds["provenance"]["implementation_address"],
        )

    def test_checked_in_mainnet_compiler_graph_promotes_usds_namespace(self):
        fixture = json.loads(
            (FIXTURES / "usds_erc7201.json").read_text()
        )
        layout_parser = LayoutParser()
        parsed = layout_parser.parse_from_raw_layout(
            contract_name="Usds",
            raw_layout=fixture["storage_layout"],
        )
        parsed.compiler_version = fixture["provenance"]["compiler_version"]
        parsed.types.update(
            layout_parser._parse_types(
                fixture["namespace_storage_layout"]["types"]
            )
        )
        namespace_parser = NamespaceStorageParser()

        self.assertEqual(
            namespace_parser.build_exact_erc7201_harness(
                fixture["compiler_output"]
            ),
            fixture["namespace_harness"],
        )
        promoted = namespace_parser.promote_exact_erc7201(
            parsed,
            compiler_output=fixture["compiler_output"],
            sources=fixture["annotated_sources"],
            compiler_version=fixture["provenance"]["compiler_version"],
        )

        root = compute_erc7201_root(
            "openzeppelin.storage.Initializable"
        )
        namespace = next(
            scope for scope in promoted.scopes if scope.kind == "erc7201"
        )
        self.assertEqual(namespace.root_slot, root)
        self.assertEqual(
            [
                (item.name, item.slot, item.offset, item.size)
                for item in promoted.variables
                if item.scope_id == namespace.id
            ],
            [
                ("_initialized", root, 0, 8),
                ("_initializing", root, 8, 1),
            ],
        )
        normalized = LayoutNormalizer().normalize(
            compile_layout(promoted)
        )
        self.assertEqual(
            [scope.report.id for scope in normalized.scopes],
            ["default", namespace.id],
        )

    def test_ast_root_pointer_and_compiler_members_promote_erc7201_exactly(self):
        identifier = "slotscan.example"
        root = compute_erc7201_root(identifier)
        uint = scalar()
        struct = StorageType(
            "t_struct(Layout)1_storage",
            "struct Example.Layout",
            "struct",
            "inplace",
            64,
            members=[
                variable("owner", 0),
                variable("limit", 1),
            ],
        )
        source = f"""
            /// @custom:storage-location erc7201:{identifier}
            struct Layout {{
                uint256 owner;
                uint256 limit;
            }}
            library Example {{
                bytes32 private constant SLOT = 0x{root:064x};
                function load() internal pure returns (Example.Layout storage $) {{
                    assembly {{ $.slot := SLOT }}
                }}
            }}
        """
        compiler_output = {
            "sources": {
                "Example.sol": {
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
        promoted = NamespaceStorageParser().promote_exact_erc7201(
            layout(
                [],
                {
                    struct.id: struct,
                    uint.id: uint,
                },
            ),
            compiler_output=compiler_output,
            sources={"Example.sol": source},
            compiler_version="0.8.30",
        )

        namespace = next(
            scope for scope in promoted.scopes if scope.kind == "erc7201"
        )
        self.assertEqual(namespace.id, f"erc7201:{identifier}")
        self.assertEqual(namespace.root_slot, root)
        self.assertEqual(
            [(item.name, item.slot, item.scope_id) for item in promoted.variables],
            [
                ("owner", root, namespace.id),
                ("limit", root + 1, namespace.id),
            ],
        )
        self.assertTrue(
            all(item.confidence == "exact" for item in promoted.variables)
        )

    def test_missing_pointer_proof_does_not_promote_annotation(self):
        identifier = "slotscan.missing-pointer"
        result = NamespaceStorageParser().promote_exact_erc7201(
            layout([]),
            compiler_output={
                "sources": {
                    "Example.sol": {
                        "ast": {
                            "nodeType": "StructDefinition",
                            "name": "Layout",
                            "documentation": {
                                "text": (
                                    "@custom:storage-location "
                                    f"erc7201:{identifier}"
                                )
                            },
                        }
                    }
                }
            },
            sources={"Example.sol": "struct Layout { uint256 owner; }"},
            compiler_version="0.8.30",
        )

        self.assertEqual(
            [scope.kind for scope in result.scopes],
            ["default"],
        )


class _AttemptProvider:
    def __init__(self):
        self.selector_calls = []
        self.exact_calls = []

    async def create_storage_attempt(self, chain_id, selector):
        self.selector_calls.append((chain_id, selector))
        number = 123 if selector == "latest" else selector
        return StorageAttempt(
            object(),
            BlockRef(chain_id, number, BLOCK_HASH),
            2,
        )

    async def create_exact_storage_attempt(self, chain_id, number, block_hash):
        self.exact_calls.append((chain_id, number, block_hash))
        return StorageAttempt(
            object(),
            BlockRef(chain_id, number, block_hash),
            2,
        )


class ComparisonServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = _AttemptProvider()
        compiled = compile_layout(layout([variable("owner", 0)]))
        self.storage_view = AsyncMock()

        async def prepare(attempt, address):
            return StorageContext(
                attempt=attempt,
                metadata=ContractMetadata(
                    chain_id=1,
                    address=address,
                    name="Fixture",
                    is_verified=True,
                ),
                layout=compiled,
                layout_status="ok",
            )

        self.storage_view.prepare_on_attempt.side_effect = prepare
        normalizer = LayoutNormalizer()
        self.service = LayoutComparisonService(
            web3_provider=self.provider,
            storage_view_service=self.storage_view,
            normalizer=normalizer,
            comparator=LayoutComparator(normalizer=normalizer),
        )

    async def test_latest_and_identical_explicit_refs_share_attempts(self):
        latest = await self.service.compare(
            chain_id=1,
            from_address=FROM,
            to_address=TO,
        )
        exact = await self.service.compare(
            chain_id=1,
            from_address=FROM,
            to_address=TO,
            from_block=123,
            from_block_hash=BLOCK_HASH,
            to_block=123,
            to_block_hash=BLOCK_HASH.upper().replace("0X", "0x"),
        )

        self.assertEqual(self.provider.selector_calls, [(1, "latest")])
        self.assertEqual(len(self.provider.exact_calls), 1)
        self.assertEqual(latest.verdict, ComparisonVerdict.NO_CONFLICTS)
        self.assertEqual(exact.verdict, ComparisonVerdict.NO_CONFLICTS)
        LayoutComparisonResponse.model_validate(latest.to_wire())
        self.assertEqual(
            [call.args[1] for call in self.storage_view.prepare_on_attempt.await_args_list],
            [FROM, TO, FROM, TO],
        )
        self.storage_view.get_view.assert_not_awaited()

    async def test_hash_without_number_is_rejected_before_rpc(self):
        with self.assertRaisesRegex(ValueError, "requires from_block"):
            await self.service.compare(
                chain_id=1,
                from_address=FROM,
                to_address=TO,
                from_block_hash=BLOCK_HASH,
            )
        self.assertEqual(self.provider.selector_calls, [])

        with self.assertRaisesRegex(ValueError, "32-byte hex value"):
            await self.service.compare(
                chain_id=1,
                from_address=FROM,
                to_address=TO,
                from_block=123,
                from_block_hash="0x1234",
            )
        self.assertEqual(self.provider.selector_calls, [])

    async def test_unavailable_side_preserves_the_other_subject(self):
        self.storage_view.prepare_on_attempt.side_effect = [
            StorageContext(
                attempt=await self.provider.create_storage_attempt(1, "latest"),
                metadata=ContractMetadata(
                    chain_id=1,
                    address=FROM,
                    is_verified=False,
                ),
                layout=None,
                layout_status="unverified",
            ),
            StorageContext(
                attempt=await self.provider.create_storage_attempt(1, "latest"),
                metadata=ContractMetadata(
                    chain_id=1,
                    address=TO,
                    is_verified=True,
                ),
                layout=compile_layout(layout([variable("owner", 0)])),
                layout_status="ok",
            ),
        ]

        report = await self.service.compare(
            chain_id=1,
            from_address=FROM,
            to_address=TO,
        )

        self.assertEqual(report.verdict, ComparisonVerdict.UNAVAILABLE)
        self.assertEqual(report.limitations, ("from_unverified",))
        self.assertIsNotNone(report.from_subject)
        self.assertIsNotNone(report.to_subject)
        self.assertEqual(report.entries, ())
        self.assertIsNone(report.summary)

    async def test_no_code_and_delegate_failures_keep_subject_identities(self):
        compiled = compile_layout(layout([variable("owner", 0)]))
        attempt = await self.provider.create_storage_attempt(1, "latest")
        self.storage_view.prepare_on_attempt.side_effect = [
            NotAContractError(FROM),
            StorageContext(
                attempt=attempt,
                metadata=ContractMetadata(
                    chain_id=1,
                    address=TO,
                    is_delegated=True,
                    delegate_address=DELEGATE,
                    delegation_status="nested",
                ),
                layout=compiled,
                layout_status="ok",
            ),
        ]

        report = await self.service.compare(
            chain_id=1,
            from_address=FROM,
            to_address=TO,
        )

        self.assertEqual(report.verdict, ComparisonVerdict.UNAVAILABLE)
        self.assertEqual(
            report.limitations,
            ("from_not_contract", "to_unsupported"),
        )
        self.assertEqual(report.from_subject.storage_address, FROM)
        self.assertEqual(report.from_subject.layout_status, "not_contract")
        self.assertEqual(report.to_subject.kind, "eip7702")
        self.assertEqual(report.to_subject.code_address, DELEGATE)
        self.assertEqual(report.to_subject.layout_status, "unsupported")

        self.storage_view.prepare_on_attempt.side_effect = [
            StorageContext(
                attempt=attempt,
                metadata=ContractMetadata(
                    chain_id=1,
                    address=FROM,
                    is_delegated=True,
                    delegate_address=DELEGATE,
                    delegation_status="empty",
                ),
                layout=None,
                layout_status="unverified",
            ),
            StorageContext(
                attempt=attempt,
                metadata=ContractMetadata(
                    chain_id=1,
                    address=TO,
                    is_verified=True,
                ),
                layout=compiled,
                layout_status="ok",
            ),
        ]
        empty = await self.service.compare(
            chain_id=1,
            from_address=FROM,
            to_address=TO,
        )
        self.assertEqual(empty.limitations, ("from_not_contract",))
        self.assertEqual(empty.from_subject.code_address, DELEGATE)

    async def test_provider_and_exact_reference_failures_propagate(self):
        self.provider.create_storage_attempt = AsyncMock(
            side_effect=RuntimeError("provider unavailable")
        )
        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            await self.service.compare(
                chain_id=1,
                from_address=FROM,
                to_address=TO,
            )
        self.storage_view.prepare_on_attempt.assert_not_awaited()

        self.provider.create_storage_attempt = AsyncMock(
            wraps=_AttemptProvider().create_storage_attempt
        )
        self.provider.create_exact_storage_attempt = AsyncMock(
            side_effect=ValueError(
                "Block number and hash do not describe the same block"
            )
        )
        with self.assertRaisesRegex(ValueError, "same block"):
            await self.service.compare(
                chain_id=1,
                from_address=FROM,
                to_address=TO,
                from_block=123,
                from_block_hash=BLOCK_HASH,
            )

    async def test_proxy_and_eip7702_subject_identities_remain_explicit(self):
        compiled = compile_layout(layout([variable("owner", 0)]))
        attempt = await self.provider.create_storage_attempt(1, "latest")
        self.storage_view.prepare_on_attempt.side_effect = [
            StorageContext(
                attempt=attempt,
                metadata=ContractMetadata(
                    chain_id=1,
                    address=FROM,
                    is_proxy=True,
                    implementation_address=IMPLEMENTATION,
                    is_verified=True,
                ),
                layout=compiled,
                layout_status="ok",
            ),
            StorageContext(
                attempt=attempt,
                metadata=ContractMetadata(
                    chain_id=1,
                    address=TO,
                    is_delegated=True,
                    delegate_address=DELEGATE,
                    delegation_status="ok",
                    is_verified=True,
                ),
                layout=compiled,
                layout_status="ok",
            ),
        ]

        report = await self.service.compare(
            chain_id=1,
            from_address=FROM,
            to_address=TO,
        )

        self.assertEqual(report.from_subject.kind, "proxy")
        self.assertEqual(report.from_subject.storage_address, FROM)
        self.assertEqual(report.from_subject.code_address, IMPLEMENTATION)
        self.assertEqual(report.to_subject.kind, "eip7702")
        self.assertEqual(report.to_subject.storage_address, TO)
        self.assertEqual(report.to_subject.code_address, DELEGATE)


IMPLEMENTATION = "0x" + "44" * 20
DELEGATE = "0x" + "55" * 20


class ComparisonRouteValidationTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, **overrides):
        arguments = {
            "chain_id": "1",
            "from_address": FROM,
            "to_address": TO,
            "from_block": None,
            "from_block_hash": None,
            "to_block": None,
            "to_block_hash": None,
            "service": AsyncMock(),
        }
        arguments.update(overrides)
        return await get_layout_comparison(**arguments)

    async def test_invalid_chain_address_and_block_are_http_400(self):
        cases = (
            {"chain_id": "ethereum"},
            {"from_address": "not-an-address"},
            {"from_block": "latest"},
            {"from_block_hash": BLOCK_HASH},
            {"from_block": "123", "from_block_hash": "0x1234"},
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                with self.assertRaises(HTTPException) as caught:
                    await self.call(**arguments)
                self.assertEqual(caught.exception.status_code, 400)

    async def test_upstream_failure_is_http_502(self):
        service = AsyncMock()
        service.compare.side_effect = RuntimeError("provider unavailable")

        with self.assertRaises(HTTPException) as caught:
            await self.call(service=service)

        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(
            caught.exception.detail,
            {
                "error": "Upstream service unavailable",
                "code": "UPSTREAM_FAILURE",
            },
        )
        self.assertNotIn(
            "provider unavailable",
            str(caught.exception.detail),
        )


if __name__ == "__main__":
    unittest.main()
