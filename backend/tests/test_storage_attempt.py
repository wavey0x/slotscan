import json
import unittest
from unittest.mock import AsyncMock

from web3 import AsyncHTTPProvider, AsyncWeb3

from app.config import Settings
from app.services.web3_provider import BlockRef, StorageAttempt, Web3Provider


BLOCK_HASH = "0x" + "ab" * 32


class _FakeBatch:
    def __init__(self):
        self.requests = []

    def add(self, request):
        self.requests.append(request)

    async def async_execute(self):
        return [await request for request in self.requests]


class _FakeEth:
    def __init__(self):
        self.identifiers = []
        self.block = {"number": 123, "hash": bytes.fromhex(BLOCK_HASH[2:])}

    async def get_block(self, selector):
        return self.block

    async def get_code(self, address, block_identifier):
        self.identifiers.append(("code", block_identifier))
        return b"\x60\x00"

    async def get_storage_at(self, address, slot, block_identifier):
        self.identifiers.append(("storage", block_identifier))
        return int(slot).to_bytes(32, "big")

    async def call(self, transaction, block_identifier):
        self.identifiers.append(("call", block_identifier))
        return bytes(32)


class _FakeWeb3:
    def __init__(self):
        self.eth = _FakeEth()

    def batch_requests(self):
        return _FakeBatch()


class StorageAttemptTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_provider_restores_reordered_batch_responses_by_id(self):
        provider = AsyncHTTPProvider("http://rpc.invalid")

        async def reversed_transport(uri, request_data, **kwargs):
            requests = json.loads(request_data)
            responses = [
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": f"0x{int(request['params'][1], 16):064x}",
                }
                for request in reversed(requests)
            ]
            return json.dumps(responses).encode()

        provider._request_session_manager.async_make_post_request = AsyncMock(
            side_effect=reversed_transport
        )
        web3 = AsyncWeb3(provider)
        web3.middleware_onion.remove("ens_name_to_address")
        attempt = StorageAttempt(
            web3=web3,
            block_ref=BlockRef(1, 123, BLOCK_HASH),
            timeout_seconds=2,
        )

        values = await attempt.batch_get_storage_at(
            1,
            "0x" + "11" * 20,
            [2, 1],
            123,
        )

        self.assertEqual(values, {2: f"0x{2:064x}", 1: f"0x{1:064x}"})

    async def test_every_state_call_uses_the_exact_eip1898_identifier(self):
        web3 = _FakeWeb3()
        attempt = StorageAttempt(
            web3=web3,
            block_ref=BlockRef(1, 123, BLOCK_HASH),
            timeout_seconds=2,
        )

        await attempt.get_code(1, "0x" + "11" * 20, 123)
        await attempt.get_storage_at(1, "0x" + "11" * 20, 0, 123)
        await attempt.eth_call(1, {"to": "0x" + "11" * 20}, 123)
        values = await attempt.batch_get_storage_at(
            1,
            "0x" + "11" * 20,
            [2, 1],
            123,
        )

        expected = {
            "blockHash": BLOCK_HASH,
            "requireCanonical": True,
        }
        self.assertTrue(web3.eth.identifiers)
        self.assertTrue(
            all(identifier == expected for _, identifier in web3.eth.identifiers)
        )
        self.assertEqual(list(values), [2, 1])

    async def test_exact_number_hash_pair_is_validated(self):
        provider = Web3Provider(Settings())
        web3 = _FakeWeb3()
        provider._instances[1] = web3

        attempt = await provider.create_exact_storage_attempt(1, 123, BLOCK_HASH)

        self.assertIs(attempt.web3, web3)
        with self.assertRaisesRegex(ValueError, "same block"):
            await provider.create_exact_storage_attempt(
                1,
                123,
                "0x" + "cd" * 32,
            )

    async def test_attempt_rejects_a_different_block_or_chain(self):
        attempt = StorageAttempt(
            web3=_FakeWeb3(),
            block_ref=BlockRef(1, 123, BLOCK_HASH),
            timeout_seconds=2,
        )

        with self.assertRaises(ValueError):
            await attempt.get_code(2, "0x" + "11" * 20, 123)
        with self.assertRaises(ValueError):
            await attempt.get_code(1, "0x" + "11" * 20, 124)


if __name__ == "__main__":
    unittest.main()
