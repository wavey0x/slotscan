import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from web3 import Web3

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
from app.services.layout import LayoutParser
from app.services.storage_view import StorageContext, StorageViewService
from app.services.web3_provider import BlockRef, StorageAttempt


BLOCK_HASH = "0x" + "ab" * 32
ADDRESS = "0x" + "11" * 20


class _Eth:
    pass


class _Provider:
    def __init__(self, fail=False, values=None):
        self.fail = fail
        self.values = values or {2**255: 42}
        self.storage_calls = []

    async def make_request(self, method, params):
        if self.fail:
            raise RuntimeError("storage unavailable")
        address, slots = next(iter(params[0].items()))
        self.storage_calls.extend((int(slot, 16), params[1]) for slot in slots)
        return {
            "result": {
                address: [
                    f"0x{self.values.get(int(slot, 16), 0):064x}"
                    for slot in slots
                ]
            }
        }


class _Web3:
    def __init__(self, fail=False, values=None):
        self.eth = _Eth()
        self.provider = _Provider(fail, values)


class _MemoryArtifactRepository:
    def __init__(self):
        self.rows = {}
        self.save_count = 0

    async def get(self, fingerprint):
        return self.rows.get(fingerprint)

    async def save(self, artifact):
        self.rows[artifact.fingerprint] = artifact
        self.save_count += 1


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


def _dynamic_word(payload: bytes) -> int:
    if len(payload) > 31:
        raise ValueError("Short dynamic values cannot exceed 31 bytes")
    return int.from_bytes(
        payload + bytes(31 - len(payload)) + bytes([len(payload) * 2]),
        "big",
    )


def _data_word(payload: bytes) -> int:
    if len(payload) > 32:
        raise ValueError("Storage data words cannot exceed 32 bytes")
    return int.from_bytes(payload.ljust(32, b"\x00"), "big")


def _dynamic_layout():
    string_type = StorageType(
        "t_string_storage",
        "string",
        "value",
        "bytes",
        num_bytes=32,
    )
    bytes_type = StorageType(
        "t_bytes_storage",
        "bytes",
        "value",
        "bytes",
        num_bytes=32,
    )
    return compile_layout(
        StorageLayout(
            contract_name="DynamicValues",
            variables=[
                StorageVariable(
                    "name",
                    3,
                    0,
                    32,
                    string_type.id,
                    string_type.label,
                ),
                StorageVariable(
                    "description",
                    4,
                    0,
                    32,
                    string_type.id,
                    string_type.label,
                ),
                StorageVariable(
                    "payload",
                    5,
                    0,
                    32,
                    bytes_type.id,
                    bytes_type.label,
                ),
            ],
            types={
                string_type.id: string_type,
                bytes_type.id: bytes_type,
            },
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
    async def test_missing_source_layout_reuses_compiler_artifact_cache(self):
        sources = {"C.sol": "contract C { uint256 value; }"}
        parser = LayoutParser()
        compiler_input = parser.build_solidity_standard_input(sources, None, None)
        compiler_output = {
            "contracts": {
                "C.sol": {
                    "C": {
                        "storageLayout": {
                            "storage": [
                                {
                                    "label": "value",
                                    "slot": "0",
                                    "offset": 0,
                                    "type": "t_uint256",
                                }
                            ],
                            "types": {
                                "t_uint256": {
                                    "encoding": "inplace",
                                    "label": "uint256",
                                    "numberOfBytes": "32",
                                }
                            },
                        }
                    }
                }
            }
        }
        parser._compile_with_layout = AsyncMock(
            return_value=(compiler_output, compiler_input)
        )
        artifacts = _MemoryArtifactRepository()
        service = StorageViewService(
            web3_provider=object(),
            resolver=SimpleNamespace(compiler_artifact_repo=artifacts),
            layout_parser=parser,
            settings=Settings(),
            decoder=TypeDecoder(),
        )
        metadata = ContractMetadata(
            chain_id=1,
            address=ADDRESS,
            is_verified=True,
            name="C",
            compiler_version="0.8.30",
            compilation_target={"C.sol": "C"},
            sources=sources,
        )

        first = await service._resolve_source_layout(metadata)
        second = await service._resolve_source_layout(metadata)

        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.variables[0].name, "value")
        self.assertEqual(parser._compile_with_layout.await_count, 1)
        self.assertEqual(artifacts.save_count, 1)

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
        self.assertEqual([slot for slot, _ in web3.provider.storage_calls], [7])

    async def test_short_and_long_solidity_dynamic_values_are_fully_decoded(self):
        short_name = b"Pendle Market"
        long_description = b"dynamic storage data " * 4
        short_payload = bytes.fromhex("00ff10")
        description_root = int.from_bytes(
            Web3.keccak((4).to_bytes(32, "big")),
            "big",
        )
        values = {
            3: _dynamic_word(short_name),
            4: len(long_description) * 2 + 1,
            5: _dynamic_word(short_payload),
            description_root: _data_word(long_description[:32]),
            description_root + 1: _data_word(long_description[32:64]),
            description_root + 2: _data_word(long_description[64:]),
        }
        web3 = _Web3(values=values)
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
            layout=_dynamic_layout(),
            layout_status="ok",
        )

        response = await _service(context).get_view(1, ADDRESS, "latest")
        validated = StorageViewResponse.model_validate(response)
        by_path = {item.path: item for item in validated.values.items}

        self.assertEqual(by_path["name"].status, "ok")
        self.assertEqual(by_path["name"].value_decoded, "Pendle Market")
        self.assertEqual(
            by_path["name"].value_encoded,
            "0x" + f"{values[3]:064x}",
        )
        self.assertEqual(
            by_path["name"].storage.model_dump(),
            {
                "base_slot": "0x3",
                "base_role": "inline",
                "computed_role": None,
                "computed_slot": None,
                "computed_slot_count": None,
            },
        )
        self.assertEqual(
            by_path["description"].value_decoded,
            long_description.decode(),
        )
        self.assertEqual(
            by_path["description"].storage.model_dump(),
            {
                "base_slot": "0x4",
                "base_role": "length",
                "computed_role": "data",
                "computed_slot": hex(description_root),
                "computed_slot_count": "3",
            },
        )
        self.assertEqual(by_path["payload"].value_decoded, "0x00ff10")
        self.assertEqual(by_path["payload"].storage.base_role, "inline")
        self.assertEqual(
            [slot for slot, _ in web3.provider.storage_calls],
            [3, 4, 5, description_root, description_root + 1, description_root + 2],
        )

    async def test_unbounded_dynamic_length_is_deferred_before_slot_expansion(self):
        web3 = _Web3(values={4: 2**256 - 1})
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
            layout=_dynamic_layout(),
            layout_status="ok",
        )
        service = _service(context)
        service.settings = Settings(MAX_SLOTS_PER_CONTRACT=2)

        response = await service.get_view(1, ADDRESS, "latest")
        validated = StorageViewResponse.model_validate(response)
        by_path = {item.path: item for item in validated.values.items}

        self.assertEqual(by_path["description"].status, "deferred_budget")
        self.assertIsNone(by_path["description"].value_encoded)
        self.assertIsNone(by_path["description"].value_decoded)
        self.assertEqual(by_path["description"].storage.base_role, "length")
        self.assertEqual(by_path["description"].storage.computed_role, "data")
        self.assertEqual(
            by_path["description"].storage.computed_slot,
            hex(int.from_bytes(Web3.keccak((4).to_bytes(32, "big")), "big")),
        )
        self.assertEqual(
            by_path["description"].storage.computed_slot_count,
            str(2**250),
        )
        self.assertEqual(
            [slot for slot, _ in web3.provider.storage_calls],
            [3, 4],
        )

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
        self.assertEqual(
            by_path["balances"]["storage"],
            {
                "base_slot": "0x7",
                "base_role": "anchor",
                "computed_role": None,
                "computed_slot": None,
                "computed_slot_count": None,
            },
        )
        self.assertEqual(
            [slot for slot, _ in web3.provider.storage_calls],
            [2**255],
        )

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
        self.assertEqual(web3.provider.storage_calls, [])


if __name__ == "__main__":
    unittest.main()
