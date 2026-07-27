import unittest
from unittest.mock import AsyncMock

from eth_abi import encode as abi_encode
from fastapi import HTTPException
from pydantic import ValidationError
from web3 import Web3

from app.api.routes.storage import query_storage
from app.config import Settings
from app.models.api import StorageQueryRequest, StorageQueryResponse
from app.models.domain import (
    ContractMetadata,
    StorageLayout,
    StorageType,
    StorageVariable,
)
from app.services.compiled_layout import compile_layout
from app.services.decoder import TypeDecoder
from app.services.storage_view import (
    StorageContext,
    StorageQueryError,
    StorageViewService,
)
from app.services.web3_provider import BlockRef


ADDRESS = "0x" + "11" * 20
BLOCK_HASH = "0x" + "ab" * 32
SOLIDITY_ADDRESS_SLOT = int(
    "07315875c131dc1dff59b5eecd3feba7c4eb34f9c8bac4a22e69acd1d04d63c5",
    16,
)
VYPER_ADDRESS_SLOT = int(
    "bc2904ac11591170e46e75e1b6082c469d2f48b47235687e687e157e758728a0",
    16,
)


class _Attempt:
    def __init__(self, values):
        self.block_ref = BlockRef(1, 123, BLOCK_HASH)
        self.values = values
        self.calls = []

    async def get_storage_values(
        self,
        chain_id,
        address,
        slots,
        block,
    ):
        self.calls.append(list(slots))
        return {
            slot: "0x" + self.values.get(slot, 0).to_bytes(32, "big").hex()
            for slot in slots
        }


class _FailingDecoder:
    def decode(self, *_args, **_kwargs):
        raise ValueError("unsupported decode")


def _layout(
    variable,
    types,
    *,
    language="Solidity",
    compiler_version="0.8.30",
    storage_scheme="solidity",
):
    return compile_layout(
        StorageLayout(
            contract_name="Query",
            variables=[variable],
            types=types,
            language=language,
            compiler_version=compiler_version,
            storage_scheme=storage_scheme,
        )
    )


def _mapping_layout(*, nested=False, vyper=False):
    value_type = "t_uint256" if not vyper else "uint256"
    key_type = "t_address" if not vyper else "address"
    types = {}
    if nested:
        inner = StorageType(
            "inner",
            "mapping(uint256 => uint256)",
            "mapping",
            "mapping",
            num_bytes=32,
            key_type="t_uint256",
            value_type="t_uint256",
        )
        types[inner.id] = inner
        value_type = inner.id
    outer = StorageType(
        "outer",
        "mapping(address => uint256)",
        "mapping",
        "mapping",
        num_bytes=32,
        key_type=key_type,
        value_type=value_type,
    )
    types[outer.id] = outer
    return _layout(
        StorageVariable("values", 7, 0, 32, outer.id, outer.label),
        types,
        language="Vyper" if vyper else "Solidity",
        compiler_version="0.3.10" if vyper else "0.8.30",
        storage_scheme="vyper_sequential" if vyper else "solidity",
    )


def _array_layout(*, dynamic=False, base_slot=9):
    array = StorageType(
        "array",
        "uint32[]" if dynamic else "uint8[64]",
        "array",
        "dynamic_array" if dynamic else "inplace",
        num_bytes=32 if dynamic else 64,
        element_type="t_uint32" if dynamic else "t_uint8",
        array_length=None if dynamic else 64,
    )
    return _layout(
        StorageVariable("items", base_slot, 0, array.num_bytes, array.id, array.label),
        {array.id: array},
    )


def _struct_mapping_layout(*, multi_slot=False, legacy_vyper=False):
    members = [
        StorageVariable("protocolId", 0, 0, 5, "t_uint40", "uint40"),
        StorageVariable(
            "deployTime",
            1 if multi_slot else 0,
            0 if multi_slot else 5,
            5,
            "t_uint40",
            "uint40",
        ),
    ]
    struct = StorageType(
        "deploy_info",
        "struct DeployInfo",
        "struct",
        "inplace",
        num_bytes=64 if multi_slot else 32,
        members=members,
    )
    mapping = StorageType(
        "deploy_info_mapping",
        "mapping(address => struct DeployInfo)",
        "mapping",
        "mapping",
        num_bytes=32,
        key_type="t_address",
        value_type=struct.id,
    )
    return _layout(
        StorageVariable("deployInfo", 7, 0, 32, mapping.id, mapping.label),
        {mapping.id: mapping, struct.id: struct},
        language="Vyper" if legacy_vyper else "Solidity",
        compiler_version="0.2.4" if legacy_vyper else "0.8.30",
        storage_scheme="vyper_legacy_hashed" if legacy_vyper else "solidity",
    )


def _dynamic_word(payload: bytes) -> int:
    if len(payload) > 31:
        raise ValueError("inline payload is too large")
    return int.from_bytes(
        payload.ljust(31, b"\x00") + bytes([len(payload) * 2]),
        "big",
    )


def _data_words(payload: bytes) -> list[int]:
    return [
        int.from_bytes(payload[offset : offset + 32].ljust(32, b"\x00"), "big")
        for offset in range(0, len(payload), 32)
    ]


def _proposal_data_layout():
    results = StorageType(
        "results",
        "struct Voter.Vote",
        "struct",
        "inplace",
        num_bytes=32,
        members=[
            StorageVariable("weightYes", 0, 0, 5, "t_uint40", "uint40"),
            StorageVariable("weightNo", 0, 5, 5, "t_uint40", "uint40"),
        ],
    )
    proposal = StorageType(
        "proposal",
        "struct Voter.Proposal",
        "struct",
        "inplace",
        num_bytes=64,
        members=[
            StorageVariable("epoch", 0, 0, 2, "t_uint16", "uint16"),
            StorageVariable("createdAt", 0, 2, 4, "t_uint32", "uint32"),
            StorageVariable(
                "quorumWeight",
                0,
                6,
                5,
                "t_uint40",
                "uint40",
            ),
            StorageVariable("processed", 0, 11, 1, "t_bool", "bool"),
            StorageVariable("results", 1, 0, 32, results.id, results.label),
        ],
    )
    array = StorageType(
        "proposal_array",
        "struct Voter.Proposal[]",
        "array",
        "dynamic_array",
        num_bytes=32,
        element_type=proposal.id,
    )
    return _layout(
        StorageVariable("proposalData", 1, 0, 32, array.id, array.label),
        {array.id: array, proposal.id: proposal, results.id: results},
    )


def _description_layout():
    string = StorageType(
        "string",
        "string",
        "value",
        "bytes",
        num_bytes=32,
    )
    mapping = StorageType(
        "description_mapping",
        "mapping(uint256 => string)",
        "mapping",
        "mapping",
        num_bytes=32,
        key_type="t_uint256",
        value_type=string.id,
    )
    return _layout(
        StorageVariable(
            "proposalDescription",
            3,
            0,
            32,
            mapping.id,
            mapping.label,
        ),
        {mapping.id: mapping, string.id: string},
    )


def _payload_layout():
    dynamic_bytes = StorageType(
        "bytes",
        "bytes",
        "value",
        "bytes",
        num_bytes=32,
    )
    action = StorageType(
        "action",
        "struct Voter.Action",
        "struct",
        "inplace",
        num_bytes=64,
        members=[
            StorageVariable("target", 0, 0, 20, "t_address", "address"),
            StorageVariable("data", 1, 0, 32, dynamic_bytes.id, "bytes"),
        ],
    )
    actions = StorageType(
        "actions",
        "struct Voter.Action[]",
        "array",
        "dynamic_array",
        num_bytes=32,
        element_type=action.id,
    )
    mapping = StorageType(
        "payload_mapping",
        "mapping(uint256 => struct Voter.Action[])",
        "mapping",
        "mapping",
        num_bytes=32,
        key_type="t_uint256",
        value_type=actions.id,
    )
    return _layout(
        StorageVariable(
            "proposalPayload",
            2,
            0,
            32,
            mapping.id,
            mapping.label,
        ),
        {
            mapping.id: mapping,
            actions.id: actions,
            action.id: action,
            dynamic_bytes.id: dynamic_bytes,
        },
    )


def _two_strings_layout():
    string = StorageType(
        "string",
        "string",
        "value",
        "bytes",
        num_bytes=32,
    )
    pair = StorageType(
        "pair",
        "struct Pair",
        "struct",
        "inplace",
        num_bytes=64,
        members=[
            StorageVariable("first", 0, 0, 32, string.id, "string"),
            StorageVariable("second", 1, 0, 32, string.id, "string"),
        ],
    )
    mapping = StorageType(
        "pair_mapping",
        "mapping(uint256 => struct Pair)",
        "mapping",
        "mapping",
        num_bytes=32,
        key_type="t_uint256",
        value_type=pair.id,
    )
    return _layout(
        StorageVariable("pairs", 5, 0, 32, mapping.id, mapping.label),
        {mapping.id: mapping, pair.id: pair, string.id: string},
    )


def _nested_struct_layout(*, unsupported_member=False):
    if unsupported_member:
        child = StorageType(
            "child_mapping",
            "mapping(uint256 => uint256)",
            "mapping",
            "mapping",
            num_bytes=32,
            key_type="t_uint256",
            value_type="t_uint256",
        )
        child_member = StorageVariable(
            "values",
            1,
            0,
            32,
            child.id,
            child.label,
        )
    else:
        child = StorageType(
            "inner",
            "struct Inner",
            "struct",
            "inplace",
            num_bytes=32,
            members=[
                StorageVariable("flag", 0, 0, 1, "t_bool", "bool"),
                StorageVariable("owner", 0, 1, 20, "t_address", "address"),
            ],
        )
        child_member = StorageVariable(
            "inner",
            1,
            0,
            32,
            child.id,
            child.label,
        )
    outer = StorageType(
        "outer_struct",
        "struct Outer",
        "struct",
        "inplace",
        num_bytes=64,
        members=[
            StorageVariable("count", 0, 0, 32, "t_uint256", "uint256"),
            child_member,
        ],
    )
    mapping = StorageType(
        "outer_mapping",
        "mapping(uint256 => struct Outer)",
        "mapping",
        "mapping",
        num_bytes=32,
        key_type="t_uint256",
        value_type=outer.id,
    )
    return _layout(
        StorageVariable("records", 8, 0, 32, mapping.id, mapping.label),
        {mapping.id: mapping, outer.id: outer, child.id: child},
    )


def _service(layout, values):
    attempt = _Attempt(values)
    context = StorageContext(
        attempt=attempt,
        metadata=ContractMetadata(
            chain_id=1,
            address=ADDRESS,
            is_verified=True,
        ),
        layout=layout,
        layout_status="ok",
    )
    service = StorageViewService(
        web3_provider=object(),
        resolver=object(),
        layout_parser=object(),
        settings=Settings(),
        decoder=TypeDecoder(),
    )
    service.prepare_exact = AsyncMock(return_value=context)
    return service, attempt


async def _query(service, layout, steps):
    return await service.query(
        chain_id=1,
        address=ADDRESS,
        block_number=123,
        block_hash=BLOCK_HASH,
        layout_id=layout.layout_id,
        declaration_id="decl:0",
        steps=steps,
    )


class StorageQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_proposal_data_index_materializes_a_multi_slot_struct(self):
        layout = _proposal_data_layout()
        data_start = _hashed_slot = int.from_bytes(
            Web3.keccak((1).to_bytes(32, "big")),
            "big",
        )
        first_word = (
            15
            | (1_751_169_587 << 16)
            | (1_486_201 << 48)
            | (1 << 88)
        )
        second_word = 3_555_667
        service, attempt = _service(
            layout,
            {
                1: 26,
                data_start: first_word,
                data_start + 1: second_word,
            },
        )

        response = await _query(
            service,
            layout,
            [{"kind": "array_index", "value": "0"}],
        )

        self.assertEqual(response["array_length"], "26")
        self.assertEqual(response["location"]["slot"], hex(_hashed_slot))
        self.assertEqual(
            [
                (item["relative_path"], item["value_decoded"])
                for item in response["items"]
            ],
            [
                ("epoch", "15"),
                ("createdAt", "1751169587"),
                ("quorumWeight", "1486201"),
                ("processed", True),
                ("results.weightYes", "3555667"),
                ("results.weightNo", "0"),
            ],
        )
        self.assertEqual(
            response["storage"]["regions"],
            [
                {"role": "length", "slot": "0x1", "slot_count": "1"},
                {
                    "role": "entry",
                    "slot": hex(data_start),
                    "slot_count": "2",
                },
            ],
        )
        self.assertEqual(
            attempt.calls,
            [[1], [data_start, data_start + 1]],
        )

    async def test_mapping_string_materializes_short_long_and_malformed_values(self):
        layout = _description_layout()
        entry = int.from_bytes(
            Web3.keccak(
                abi_encode(["uint256"], [0])
                + abi_encode(["uint256"], [3])
            ),
            "big",
        )
        short = b"Pay bad debt through governance"
        service, attempt = _service(layout, {entry: _dynamic_word(short)})
        response = await _query(
            service,
            layout,
            [{"kind": "mapping_key", "value": "0"}],
        )
        self.assertEqual(response["items"][0]["value_decoded"], short.decode())
        self.assertEqual(
            [region["role"] for region in response["storage"]["regions"]],
            ["anchor", "inline"],
        )
        self.assertEqual(attempt.calls, [[entry]])

        long = b"Governance proposal description that exceeds one word."
        data_start = int.from_bytes(
            Web3.keccak(entry.to_bytes(32, "big")),
            "big",
        )
        service, attempt = _service(
            layout,
            {
                entry: len(long) * 2 + 1,
                **{
                    data_start + offset: value
                    for offset, value in enumerate(_data_words(long))
                },
            },
        )
        response = await _query(
            service,
            layout,
            [{"kind": "mapping_key", "value": "0"}],
        )
        self.assertEqual(response["items"][0]["value_decoded"], long.decode())
        self.assertEqual(
            response["storage"]["regions"],
            [
                {"role": "anchor", "slot": "0x3", "slot_count": "1"},
                {"role": "length", "slot": hex(entry), "slot_count": "1"},
                {
                    "role": "data",
                    "slot": hex(data_start),
                    "slot_count": "2",
                },
            ],
        )
        self.assertEqual(
            attempt.calls,
            [[entry], [data_start, data_start + 1]],
        )

        service, attempt = _service(layout, {entry: 3})
        with self.assertRaises(StorageQueryError) as raised:
            await _query(
                service,
                layout,
                [{"kind": "mapping_key", "value": "0"}],
            )
        self.assertEqual(raised.exception.code, "MALFORMED_STORAGE")
        self.assertEqual(attempt.calls, [[entry]])

    async def test_mapping_then_array_materializes_action_and_long_bytes(self):
        layout = _payload_layout()
        mapping_entry = int.from_bytes(
            Web3.keccak(
                abi_encode(["uint256"], [0])
                + abi_encode(["uint256"], [2])
            ),
            "big",
        )
        action_slot = int.from_bytes(
            Web3.keccak(mapping_entry.to_bytes(32, "big")),
            "big",
        )
        data_header = action_slot + 1
        payload = bytes.fromhex(
            "12345678"
            + "00" * 32
        )
        payload_root = int.from_bytes(
            Web3.keccak(data_header.to_bytes(32, "big")),
            "big",
        )
        target = "0x10101010E0C3171D894B71B3400668aF311e7D94"
        service, attempt = _service(
            layout,
            {
                mapping_entry: 9,
                action_slot: int(target, 16),
                data_header: len(payload) * 2 + 1,
                **{
                    payload_root + offset: value
                    for offset, value in enumerate(_data_words(payload))
                },
            },
        )

        response = await _query(
            service,
            layout,
            [
                {"kind": "mapping_key", "value": "0"},
                {"kind": "array_index", "value": "0"},
            ],
        )

        self.assertEqual(response["array_length"], "9")
        self.assertEqual(
            [
                (item["relative_path"], item["value_decoded"])
                for item in response["items"]
            ],
            [
                ("target", target),
                ("data", "0x" + payload.hex()),
            ],
        )
        self.assertEqual(
            [region["role"] for region in response["storage"]["regions"]],
            ["anchor", "length", "entry"],
        )
        self.assertEqual(
            response["items"][1]["storage"]["regions"],
            [
                {
                    "role": "length",
                    "slot": hex(data_header),
                    "slot_count": "1",
                },
                {
                    "role": "data",
                    "slot": hex(payload_root),
                    "slot_count": "2",
                },
            ],
        )
        self.assertEqual(
            attempt.calls,
            [
                [mapping_entry],
                [action_slot, data_header],
                [payload_root, payload_root + 1],
            ],
        )

    async def test_access_shape_errors_are_rejected_before_storage_reads(self):
        layout = _payload_layout()
        for steps in (
            [{"kind": "array_index", "value": "0"}],
            [{"kind": "mapping_key", "value": "0"}],
            [
                {"kind": "mapping_key", "value": "0"},
                {"kind": "array_index", "value": "0"},
                {"kind": "array_index", "value": "0"},
            ],
        ):
            with self.subTest(steps=steps):
                service, attempt = _service(layout, {})
                with self.assertRaises(StorageQueryError) as raised:
                    await _query(service, layout, steps)
                self.assertEqual(raised.exception.code, "UNSUPPORTED_ACCESS")
                self.assertEqual(attempt.calls, [])

    async def test_dynamic_materialization_budget_is_atomic_across_all_leaves(self):
        layout = _two_strings_layout()
        entry = int.from_bytes(
            Web3.keccak(
                abi_encode(["uint256"], [0])
                + abi_encode(["uint256"], [5])
            ),
            "big",
        )
        service, attempt = _service(
            layout,
            {
                entry: 4064 * 2 + 1,
                entry + 1: 4096 * 2 + 1,
            },
        )

        with self.assertRaises(StorageQueryError) as raised:
            await _query(
                service,
                layout,
                [{"kind": "mapping_key", "value": "0"}],
            )

        self.assertEqual(raised.exception.code, "QUERY_TOO_LARGE")
        self.assertEqual(attempt.calls, [[entry, entry + 1]])

    async def test_nested_finite_structs_are_flattened_recursively(self):
        layout = _nested_struct_layout()
        entry = int.from_bytes(
            Web3.keccak(
                abi_encode(["uint256"], [4])
                + abi_encode(["uint256"], [8])
            ),
            "big",
        )
        owner = "0x2222222222222222222222222222222222222222"
        packed_inner = 1 | (int(owner, 16) << 8)
        service, attempt = _service(
            layout,
            {entry: 17, entry + 1: packed_inner},
        )

        response = await _query(
            service,
            layout,
            [{"kind": "mapping_key", "value": "4"}],
        )

        self.assertEqual(
            [
                (
                    item["relative_path"],
                    item["location"]["slot"],
                    item["location"]["byte_offset"],
                    item["value_decoded"],
                )
                for item in response["items"]
            ],
            [
                ("count", hex(entry), 0, "17"),
                ("inner.flag", hex(entry + 1), 0, True),
                ("inner.owner", hex(entry + 1), 1, owner),
            ],
        )
        self.assertEqual(attempt.calls, [[entry, entry + 1]])

    async def test_structs_with_mapping_members_are_unsupported_without_reads(self):
        layout = _nested_struct_layout(unsupported_member=True)
        service, attempt = _service(layout, {})

        with self.assertRaises(StorageQueryError) as raised:
            await _query(
                service,
                layout,
                [{"kind": "mapping_key", "value": "4"}],
            )

        self.assertEqual(raised.exception.code, "UNSUPPORTED_ACCESS")
        self.assertEqual(attempt.calls, [])

    async def test_legacy_vyper_does_not_gain_multi_word_materialization(self):
        layout = _struct_mapping_layout(
            multi_slot=True,
            legacy_vyper=True,
        )
        service, attempt = _service(layout, {})

        with self.assertRaises(StorageQueryError) as raised:
            await _query(
                service,
                layout,
                [{"kind": "mapping_key", "value": ADDRESS}],
            )

        self.assertEqual(raised.exception.code, "UNSUPPORTED_ACCESS")
        self.assertEqual(attempt.calls, [])

    async def test_solidity_and_vyper_mapping_locations_use_literal_vectors(self):
        for layout, expected in (
            (_mapping_layout(), SOLIDITY_ADDRESS_SLOT),
            (_mapping_layout(vyper=True), VYPER_ADDRESS_SLOT),
        ):
            with self.subTest(order=layout.storage_rules.mapping_preimage_order):
                service, attempt = _service(layout, {expected: 42})
                response = await _query(
                    service,
                    layout,
                    [{"kind": "mapping_key", "value": ADDRESS}],
                )

                self.assertEqual(response["location"]["slot"], hex(expected))
                self.assertEqual(response["items"][0]["value_decoded"], "42")
                self.assertEqual(attempt.calls, [[expected]])

    async def test_nested_mapping_ends_in_one_scalar_read(self):
        layout = _mapping_layout(nested=True)
        outer = int.from_bytes(
            Web3.keccak(
                abi_encode(["address"], [ADDRESS])
                + abi_encode(["uint256"], [7])
            ),
            "big",
        )
        expected = int.from_bytes(
            Web3.keccak(
                abi_encode(["uint256"], [5])
                + abi_encode(["uint256"], [outer])
            ),
            "big",
        )
        service, attempt = _service(layout, {expected: 99})

        response = await _query(
            service,
            layout,
            [
                {"kind": "mapping_key", "value": ADDRESS},
                {"kind": "mapping_key", "value": "5"},
            ],
        )

        self.assertEqual(response["location"]["slot"], hex(expected))
        self.assertEqual(response["items"][0]["value_decoded"], "99")
        self.assertEqual(
            response["storage"]["regions"],
            [
                {"role": "anchor", "slot": "0x7", "slot_count": "1"},
                {"role": "anchor", "slot": hex(outer), "slot_count": "1"},
                {"role": "entry", "slot": hex(expected), "slot_count": "1"},
            ],
        )
        self.assertEqual(attempt.calls, [[expected]])

    async def test_mapping_to_packed_struct_reads_and_decodes_one_word(self):
        layout = _struct_mapping_layout()
        protocol_id = 7
        deploy_time = 1_725_000_000
        packed = protocol_id | (deploy_time << 40)
        service, attempt = _service(layout, {SOLIDITY_ADDRESS_SLOT: packed})

        response = await _query(
            service,
            layout,
            [{"kind": "mapping_key", "value": ADDRESS}],
        )
        validated = StorageQueryResponse.model_validate(response)

        self.assertEqual(
            [
                (item.relative_path, item.value_decoded)
                for item in validated.items
            ],
            [
                ("protocolId", str(protocol_id)),
                ("deployTime", str(deploy_time)),
            ],
        )
        self.assertEqual(validated.location.slot, hex(SOLIDITY_ADDRESS_SLOT))
        self.assertEqual(validated.location.byte_offset, 0)
        self.assertEqual(validated.location.byte_size, 32)
        self.assertEqual(
            validated.storage.model_dump(),
            {
                "regions": [
                    {
                        "role": "anchor",
                        "slot": "0x7",
                        "slot_count": "1",
                    },
                    {
                        "role": "entry",
                        "slot": hex(SOLIDITY_ADDRESS_SLOT),
                        "slot_count": "1",
                    },
                ]
            },
        )
        self.assertEqual(attempt.calls, [[SOLIDITY_ADDRESS_SLOT]])

    async def test_mapping_to_multi_slot_struct_returns_backend_authored_leaves(self):
        layout = _struct_mapping_layout(multi_slot=True)
        service, attempt = _service(
            layout,
            {
                SOLIDITY_ADDRESS_SLOT: 7,
                SOLIDITY_ADDRESS_SLOT + 1: 1_725_000_000,
            },
        )

        response = await _query(
            service,
            layout,
            [{"kind": "mapping_key", "value": ADDRESS}],
        )

        self.assertEqual(
            [
                (
                    item["relative_path"],
                    item["location"]["slot"],
                    item["value_decoded"],
                )
                for item in response["items"]
            ],
            [
                ("protocolId", hex(SOLIDITY_ADDRESS_SLOT), "7"),
                (
                    "deployTime",
                    hex(SOLIDITY_ADDRESS_SLOT + 1),
                    "1725000000",
                ),
            ],
        )
        self.assertEqual(
            response["storage"]["regions"][-1],
            {
                "role": "entry",
                "slot": hex(SOLIDITY_ADDRESS_SLOT),
                "slot_count": "2",
            },
        )
        self.assertEqual(
            attempt.calls,
            [[SOLIDITY_ADDRESS_SLOT, SOLIDITY_ADDRESS_SLOT + 1]],
        )

    async def test_invalid_mapping_key_and_layout_mismatch_read_no_value_words(self):
        layout = _mapping_layout()
        for layout_id, key, code in (
            (layout.layout_id, "not-an-address", "INVALID_MAPPING_KEY"),
            ("sha256:" + "0" * 64, ADDRESS, "LAYOUT_MISMATCH"),
        ):
            with self.subTest(code=code):
                service, attempt = _service(layout, {})
                with self.assertRaises(StorageQueryError) as raised:
                    await service.query(
                        chain_id=1,
                        address=ADDRESS,
                        block_number=123,
                        block_hash=BLOCK_HASH,
                        layout_id=layout_id,
                        declaration_id="decl:0",
                        steps=[{"kind": "mapping_key", "value": key}],
                    )
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(attempt.calls, [])

    async def test_packed_fixed_array_uses_backend_derived_byte_range(self):
        layout = _array_layout()
        service, attempt = _service(layout, {10: 42 << 8})

        response = await _query(
            service,
            layout,
            [{"kind": "array_index", "value": "33"}],
        )

        validated = StorageQueryResponse.model_validate(response)
        self.assertEqual(validated.location.slot, "0xa")
        self.assertEqual(validated.location.byte_offset, 1)
        self.assertEqual(validated.items[0].value_decoded, "42")
        self.assertEqual(attempt.calls, [[10]])

    async def test_static_bounds_failure_reads_no_words_and_high_slots_stay_strings(self):
        layout = _array_layout(base_slot=2**255)
        service, attempt = _service(layout, {})
        with self.assertRaises(StorageQueryError) as raised:
            await _query(
                service,
                layout,
                [{"kind": "array_index", "value": "64"}],
            )
        self.assertEqual(raised.exception.code, "ARRAY_BOUNDS")
        self.assertEqual(attempt.calls, [])

        service, attempt = _service(layout, {2**255: 7})
        response = await _query(
            service,
            layout,
            [{"kind": "array_index", "value": "0"}],
        )
        self.assertEqual(response["location"]["slot"], hex(2**255))
        self.assertIsInstance(response["location"]["slot"], str)

    async def test_dynamic_bounds_reads_only_length_and_success_reads_one_more_word(self):
        layout = _array_layout(dynamic=True)
        data_start = int.from_bytes(Web3.keccak((9).to_bytes(32, "big")), "big")

        service, attempt = _service(layout, {9: 2})
        with self.assertRaises(StorageQueryError) as raised:
            await _query(
                service,
                layout,
                [{"kind": "array_index", "value": "2"}],
            )
        self.assertEqual(raised.exception.code, "ARRAY_BOUNDS")
        self.assertEqual(attempt.calls, [[9]])

        service, attempt = _service(layout, {9: 2, data_start: 17 << 4 * 8})
        response = await _query(
            service,
            layout,
            [{"kind": "array_index", "value": "1"}],
        )
        self.assertEqual(response["array_length"], "2")
        self.assertEqual(response["location"]["slot"], hex(data_start))
        self.assertEqual(response["location"]["byte_offset"], 4)
        self.assertEqual(response["items"][0]["value_decoded"], "17")
        self.assertEqual(
            response["storage"],
            {
                "regions": [
                    {
                        "role": "length",
                        "slot": "0x9",
                        "slot_count": "1",
                    },
                    {
                        "role": "entry",
                        "slot": hex(data_start),
                        "slot_count": "1",
                    },
                ]
            },
        )
        self.assertEqual(attempt.calls, [[9], [data_start]])

    async def test_decode_failure_keeps_the_raw_query_value(self):
        layout = _mapping_layout()
        service, _ = _service(layout, {SOLIDITY_ADDRESS_SLOT: 42})
        service.decoder = _FailingDecoder()

        response = await _query(
            service,
            layout,
            [{"kind": "mapping_key", "value": ADDRESS}],
        )
        validated = StorageQueryResponse.model_validate(response)

        self.assertEqual(
            validated.items[0].value_encoded,
            "0x" + f"{42:064x}",
        )
        self.assertIsNone(validated.items[0].value_decoded)

    async def test_mismatched_exact_block_is_a_client_error(self):
        provider = type("Provider", (), {})()
        provider.create_exact_storage_attempt = AsyncMock(
            side_effect=ValueError(
                "Block number and hash do not describe the same block"
            )
        )
        service = StorageViewService(
            web3_provider=provider,
            resolver=object(),
            layout_parser=object(),
            settings=Settings(),
            decoder=TypeDecoder(),
        )
        request = StorageQueryRequest.model_validate(
            {
                "chain_id": "1",
                "address": ADDRESS,
                "block_ref": {"number": "0x7b", "hash": BLOCK_HASH},
                "layout_id": "sha256:" + "1" * 64,
                "access": {
                    "declaration_id": "decl:0",
                    "steps": [{"kind": "array_index", "value": "0"}],
                },
            }
        )

        with self.assertRaises(HTTPException) as raised:
            await query_storage(request, service)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail["code"], "INVALID_BLOCK_REF")

    def test_request_shape_rejects_browser_computed_locations(self):
        request = {
            "chain_id": "1",
            "address": ADDRESS,
            "block_ref": {"number": "0x7b", "hash": BLOCK_HASH},
            "layout_id": "sha256:" + "1" * 64,
            "access": {
                "declaration_id": "decl:0",
                "steps": [
                    {
                        "kind": "mapping_key",
                        "value": ADDRESS,
                        "slot": "0x7",
                    }
                ],
            },
        }

        with self.assertRaises(ValidationError):
            StorageQueryRequest.model_validate(request)


if __name__ == "__main__":
    unittest.main()
