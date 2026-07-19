import unittest

from app.config import Settings
from app.services.web3_provider import BlockRef, StorageAttempt, Web3Provider


BLOCK_HASH = "0x" + "ab" * 32
ADDRESS = "0x" + "11" * 20


class _FakeProvider:
    def __init__(self):
        self.calls = []
        self.response_override = None

    async def make_request(self, method, params):
        self.calls.append((method, params))
        if self.response_override is not None:
            return self.response_override
        address, slot_words = next(iter(params[0].items()))
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                address.lower(): [
                    f"0x{int(slot, 16):064x}" for slot in slot_words
                ]
            },
        }


class _FakeEth:
    def __init__(self):
        self.identifiers = []
        self.block = {"number": 123, "hash": bytes.fromhex(BLOCK_HASH[2:])}

    async def get_block(self, selector):
        return self.block

    async def get_code(self, address, block_identifier):
        self.identifiers.append(("code", block_identifier))
        return b"\x60\x00"

    async def call(self, transaction, block_identifier):
        self.identifiers.append(("call", block_identifier))
        return bytes(32)


class _FakeWeb3:
    def __init__(self):
        self.eth = _FakeEth()
        self.provider = _FakeProvider()


class StorageAttemptTests(unittest.IsolatedAsyncioTestCase):
    def make_attempt(self, web3=None):
        return StorageAttempt(
            web3=web3 or _FakeWeb3(),
            block_ref=BlockRef(1, 123, BLOCK_HASH),
            timeout_seconds=2,
        )

    async def test_native_read_deduplicates_and_preserves_slot_order(self):
        attempt = self.make_attempt()

        values = await attempt.get_storage_values(
            1,
            ADDRESS,
            [2, 1, 2],
            123,
        )

        self.assertEqual(values, {2: f"0x{2:064x}", 1: f"0x{1:064x}"})
        method, params = attempt.web3.provider.calls[0]
        self.assertEqual(method, "eth_getStorageValues")
        self.assertEqual(
            list(next(iter(params[0].values()))),
            [f"0x{2:064x}", f"0x{1:064x}"],
        )
        self.assertEqual(
            params[1],
            {"blockHash": BLOCK_HASH, "requireCanonical": True},
        )

    async def test_empty_read_performs_no_rpc(self):
        web3 = _FakeWeb3()

        values = await self.make_attempt(web3).get_storage_values(
            1,
            ADDRESS,
            [],
            123,
        )

        self.assertEqual(values, {})
        self.assertEqual(web3.provider.calls, [])

    async def test_native_read_chunks_at_reth_limit_with_same_block(self):
        web3 = _FakeWeb3()
        slots = list(range(1025))

        values = await self.make_attempt(web3).get_storage_values(
            1,
            ADDRESS,
            slots,
            123,
        )

        self.assertEqual(len(values), 1025)
        self.assertEqual(
            [len(next(iter(params[0].values()))) for _, params in web3.provider.calls],
            [1024, 1],
        )
        self.assertEqual(
            {str(params[1]) for _, params in web3.provider.calls},
            {str({"blockHash": BLOCK_HASH, "requireCanonical": True})},
        )

    async def test_general_provider_encodes_integer_block_as_hex(self):
        provider = Web3Provider(Settings())
        web3 = _FakeWeb3()
        provider._instances[1] = web3

        values = await provider.get_storage_values(1, ADDRESS, [0], 123)

        self.assertEqual(values, {0: "0x" + "00" * 32})
        self.assertEqual(web3.provider.calls[0][1][1], "0x7b")

    async def test_general_provider_preserves_eip1898_object(self):
        provider = Web3Provider(Settings())
        web3 = _FakeWeb3()
        provider._instances[1] = web3
        block = {"blockNumber": "0x7b"}

        await provider.get_storage_values(1, ADDRESS, [0], block)

        self.assertIs(web3.provider.calls[0][1][1], block)

    async def test_general_provider_forwards_allowed_tags_unchanged(self):
        provider = Web3Provider(Settings())
        web3 = _FakeWeb3()
        provider._instances[1] = web3

        for tag in ("earliest", "finalized", "latest", "pending", "safe"):
            await provider.get_storage_values(1, ADDRESS, [0], tag)

        self.assertEqual(
            [params[1] for _, params in web3.provider.calls],
            ["earliest", "finalized", "latest", "pending", "safe"],
        )

    async def test_general_provider_rejects_stringified_numbers_and_tags(self):
        provider = Web3Provider(Settings())
        for block in ("123", "0x7b", "LATEST"):
            with self.subTest(block=block):
                web3 = _FakeWeb3()
                provider._instances[1] = web3
                with self.assertRaises(RuntimeError):
                    await provider.get_storage_values(1, ADDRESS, [0], block)
                self.assertEqual(web3.provider.calls, [])

    async def test_every_other_state_call_uses_exact_eip1898_identifier(self):
        web3 = _FakeWeb3()
        attempt = self.make_attempt(web3)

        await attempt.get_code(1, ADDRESS, 123)
        await attempt.eth_call(1, {"to": ADDRESS}, 123)

        expected = {"blockHash": BLOCK_HASH, "requireCanonical": True}
        self.assertEqual(
            web3.eth.identifiers,
            [("code", expected), ("call", expected)],
        )

    async def test_rejects_invalid_slots_before_rpc(self):
        for slot in (-1, 2**256, True, "1"):
            with self.subTest(slot=slot):
                web3 = _FakeWeb3()
                with self.assertRaises(ValueError):
                    await self.make_attempt(web3).get_storage_values(
                        1,
                        ADDRESS,
                        [slot],
                        123,
                    )
                self.assertEqual(web3.provider.calls, [])

    async def test_rejects_rpc_errors_and_malformed_results(self):
        cases = (
            {"error": {"code": -32602, "message": "private endpoint detail"}},
            {"result": []},
            {"result": {}},
            {"result": {ADDRESS: [], "0x" + "22" * 20: []}},
            {"result": {ADDRESS: []}},
            {"result": {ADDRESS: ["0x01"]}},
            {"result": {ADDRESS: ["0x" + "gg" * 32]}},
        )
        for response in cases:
            with self.subTest(response=response):
                web3 = _FakeWeb3()
                web3.provider.response_override = response
                with self.assertRaises(RuntimeError):
                    await self.make_attempt(web3).get_storage_values(
                        1,
                        ADDRESS,
                        [0],
                        123,
                    )

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
        attempt = self.make_attempt()

        with self.assertRaises(ValueError):
            await attempt.get_code(2, ADDRESS, 123)
        with self.assertRaises(ValueError):
            await attempt.get_code(1, ADDRESS, 124)


if __name__ == "__main__":
    unittest.main()
