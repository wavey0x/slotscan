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


def _struct_mapping_layout(*, multi_slot=False):
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
                self.assertEqual(response["value_decoded"], "42")
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
        self.assertEqual(response["value_decoded"], "99")
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
            validated.value_decoded,
            {
                "protocolId": str(protocol_id),
                "deployTime": str(deploy_time),
            },
        )
        self.assertEqual(validated.location.slot, hex(SOLIDITY_ADDRESS_SLOT))
        self.assertEqual(validated.location.byte_offset, 0)
        self.assertEqual(validated.location.byte_size, 32)
        self.assertEqual(attempt.calls, [[SOLIDITY_ADDRESS_SLOT]])

    async def test_mapping_to_multi_slot_struct_is_rejected_without_reading(self):
        layout = _struct_mapping_layout(multi_slot=True)
        service, attempt = _service(layout, {})

        with self.assertRaises(StorageQueryError) as raised:
            await _query(
                service,
                layout,
                [{"kind": "mapping_key", "value": ADDRESS}],
            )

        self.assertEqual(raised.exception.code, "UNSUPPORTED_ACCESS")
        self.assertEqual(attempt.calls, [])

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
        self.assertEqual(validated.value_decoded, "42")
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
        self.assertEqual(response["value_decoded"], "17")
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

        self.assertEqual(validated.value_encoded, "0x" + f"{42:064x}")
        self.assertIsNone(validated.value_decoded)

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
