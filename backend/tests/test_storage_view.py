import unittest
from unittest.mock import AsyncMock

from app.config import Settings
from app.models.domain import (
    ContractMetadata,
    StorageLayout,
    StorageType,
    StorageVariable,
)
from app.models.api import StorageViewResponse
from app.services.compiled_layout import compile_layout
from app.services.decoder import TypeDecoder
from app.services.storage_view import StorageContext, StorageViewService
from app.services.web3_provider import BlockRef, StorageAttempt


BLOCK_HASH = "0x" + "ab" * 32
ADDRESS = "0x" + "11" * 20


class _Batch:
    def __init__(self, fail=False):
        self.requests = []
        self.fail = fail

    def add(self, request):
        self.requests.append(request)

    async def async_execute(self):
        if self.fail:
            for request in self.requests:
                request.close()
            raise RuntimeError("storage unavailable")
        return [await request for request in self.requests]


class _Eth:
    def __init__(self, values=None):
        self.storage_calls = []
        self.values = values or {2**255: 42}

    async def get_storage_at(self, address, slot, block_identifier):
        self.storage_calls.append((slot, block_identifier))
        return self.values.get(slot, 0).to_bytes(32, "big")


class _Web3:
    def __init__(self, fail=False, values=None):
        self.eth = _Eth(values)
        self.fail = fail

    def batch_requests(self):
        return _Batch(self.fail)


def _compiled_layout():
    mapping = StorageType(
        "mapping",
        "mapping(address => uint256)",
        "mapping",
        "mapping",
        num_bytes=32,
        key_type="t_address",
        value_type="t_uint256",
    )
    return compile_layout(
        StorageLayout(
            contract_name="View",
            variables=[
                StorageVariable(
                    "counter",
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
            language="Solidity",
            compiler_version="0.8.30",
            storage_scheme="solidity",
        )
    )


def _service(context):
    service = StorageViewService(
        web3_provider=object(),
        resolver=object(),
        layout_parser=object(),
        settings=Settings(),
        decoder=TypeDecoder(),
    )
    service.prepare = AsyncMock(return_value=context)
    return service


class _FailingDecoder:
    def decode(self, *_args, **_kwargs):
        raise ValueError("unsupported decode")


class StorageViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_packed_consumer_of_one_word_is_decoded(self):
        layout = compile_layout(
            StorageLayout(
                contract_name="Packed",
                variables=[
                    StorageVariable("enabled", 7, 0, 1, "t_bool", "bool"),
                    StorageVariable("small", 7, 1, 1, "t_uint8", "uint8"),
                ],
                types={},
                language="Solidity",
                compiler_version="0.8.30",
                storage_scheme="solidity",
            )
        )
        web3 = _Web3(values={7: 0x2A01})
        context = StorageContext(
            attempt=StorageAttempt(
                web3,
                BlockRef(1, 123, BLOCK_HASH),
                2,
            ),
            metadata=ContractMetadata(
                chain_id=1,
                address=ADDRESS,
                is_verified=True,
            ),
            layout=layout,
            layout_status="ok",
        )

        response = await _service(context).get_view(1, ADDRESS, "latest")

        by_path = {item["path"]: item for item in response["values"]["items"]}
        self.assertIs(by_path["enabled"]["value_decoded"], True)
        self.assertEqual(by_path["small"]["value_decoded"], "42")
        self.assertEqual([slot for slot, _ in web3.eth.storage_calls], [7])

    async def test_coherent_view_uses_string_safe_values_and_on_demand_status(self):
        web3 = _Web3()
        attempt = StorageAttempt(
            web3,
            BlockRef(1, 123, BLOCK_HASH),
            2,
        )
        context = StorageContext(
            attempt=attempt,
            metadata=ContractMetadata(
                chain_id=1,
                address=ADDRESS,
                name="View",
                is_verified=True,
            ),
            layout=_compiled_layout(),
            layout_status="ok",
        )

        response = await _service(context).get_view(1, ADDRESS, "latest")
        validated = StorageViewResponse.model_validate(response)

        self.assertEqual(response["block_ref"], {"number": "0x7b", "hash": BLOCK_HASH})
        self.assertEqual(validated.layout_id, response["layout_id"])
        self.assertEqual(response["values"]["status"], "ok")
        by_path = {item["path"]: item for item in response["values"]["items"]}
        self.assertEqual(by_path["counter"]["value_decoded"], "42")
        self.assertEqual(by_path["counter"]["slot"], hex(2**255))
        self.assertEqual(by_path["balances"]["status"], "on_demand")
        self.assertEqual([slot for slot, _ in web3.eth.storage_calls], [2**255])

    async def test_value_failure_keeps_the_valid_layout_without_partial_items(self):
        attempt = StorageAttempt(
            _Web3(fail=True),
            BlockRef(1, 123, BLOCK_HASH),
            2,
        )
        context = StorageContext(
            attempt=attempt,
            metadata=ContractMetadata(
                chain_id=1,
                address=ADDRESS,
                is_verified=True,
            ),
            layout=_compiled_layout(),
            layout_status="ok",
        )

        response = await _service(context).get_view(1, ADDRESS, "latest")

        self.assertEqual(response["layout"]["status"], "ok")
        self.assertIsNotNone(response["layout_id"])
        self.assertEqual(
            response["values"],
            {
                "status": "error",
                "items": [],
                "error_code": "STORAGE_READ_FAILED",
            },
        )

    async def test_decode_failure_keeps_the_raw_value(self):
        context = StorageContext(
            attempt=StorageAttempt(
                _Web3(),
                BlockRef(1, 123, BLOCK_HASH),
                2,
            ),
            metadata=ContractMetadata(
                chain_id=1,
                address=ADDRESS,
                is_verified=True,
            ),
            layout=_compiled_layout(),
            layout_status="ok",
        )
        service = _service(context)
        service.decoder = _FailingDecoder()

        response = await service.get_view(1, ADDRESS, "latest")
        validated = StorageViewResponse.model_validate(response)
        by_path = {item.path: item for item in validated.values.items}

        self.assertEqual(validated.values.status, "ok")
        self.assertEqual(by_path["counter"].status, "ok")
        self.assertEqual(by_path["counter"].value_encoded, "0x" + f"{42:064x}")
        self.assertIsNone(by_path["counter"].value_decoded)

    async def test_unverified_view_has_no_value_storage_reads(self):
        web3 = _Web3()
        context = StorageContext(
            attempt=StorageAttempt(
                web3,
                BlockRef(1, 123, BLOCK_HASH),
                2,
            ),
            metadata=ContractMetadata(
                chain_id=1,
                address=ADDRESS,
                is_verified=False,
            ),
            layout=None,
            layout_status="unverified",
        )

        response = await _service(context).get_view(1, ADDRESS, "latest")

        self.assertEqual(response["layout"]["status"], "unverified")
        self.assertEqual(response["values"]["status"], "unavailable")
        self.assertEqual(web3.eth.storage_calls, [])


if __name__ == "__main__":
    unittest.main()
