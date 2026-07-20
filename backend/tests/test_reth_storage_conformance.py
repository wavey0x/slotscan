import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from web3 import Web3

from app.config import Settings
from app.services.resolver import (
    EIP1822_SLOT,
    EIP1967_BEACON_SLOT,
    EIP1967_IMPL_SLOT,
    ZEPPELINOS_IMPL_SLOT,
    ContractResolver,
)
from app.services.web3_provider import Web3Provider


RUN_CONFORMANCE = os.environ.get("RUN_RETH_STORAGE_CONFORMANCE") == "1"
VOTING_TX = (
    "0xa1fc48efe579dde86c1b46ced4d5a2cb"
    "589c95609be976539eb4d5b3513e2f56"
)
VOTING_PROXY = "0xe478de485ad2fe566d49342cbd03e49ed7db3356"
VOTING_IMPLEMENTATION = "0xa4d1a2693589840babb7f3a44d14fdf41b3bf1fe"
VOTING_BLOCK_HASH = (
    "0x27de3826a6f6585327fde1caa3827dbf"
    "7b54c6c90448aaa6d58e5c3b65b76546"
)
ABSENT_HIGH_SLOT = 2**256 - 1
ZERO_WORD = "0x" + "0" * 64


@unittest.skipUnless(
    RUN_CONFORMANCE,
    "set RUN_RETH_STORAGE_CONFORMANCE=1 for deployment-provider checks",
)
class RethStorageConformanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = Settings()
        self.provider = Web3Provider(self.settings)

    async def asyncTearDown(self):
        await self.provider.close()

    async def _voting_attempt(self):
        version = await self.provider.make_request(1, "web3_clientVersion", [])
        self.assertRegex(version["result"], r"^reth/v\d+\.\d+\.\d+")
        receipt = await self.provider.get_transaction_receipt(1, VOTING_TX)
        block_number = int(receipt["blockNumber"])
        web3 = self.provider.get_web3(1)
        block = await web3.eth.get_block(block_number)
        block_hash = block["hash"].hex()
        if not block_hash.startswith("0x"):
            block_hash = "0x" + block_hash
        self.assertEqual(block_hash.lower(), VOTING_BLOCK_HASH)
        attempt = await self.provider.create_exact_storage_attempt(
            1,
            block_number,
            block_hash,
        )
        return attempt, block_number, block_hash.lower()

    async def test_exact_native_vector_chunks_at_reth_limit(self):
        attempt, block_number, block_hash = await self._voting_attempt()
        web3 = self.provider.get_web3(1)
        slots = [*range(1024), ABSENT_HIGH_SLOT]
        original_make_request = web3.provider.make_request

        with patch.object(
            web3.provider,
            "make_request",
            AsyncMock(wraps=original_make_request),
        ) as make_request:
            native = await attempt.get_storage_values(
                1,
                VOTING_PROXY,
                slots,
                block_number,
            )

        self.assertEqual(len(native), 1025)
        native_calls = [
            call
            for call in make_request.await_args_list
            if call.args[0] == "eth_getStorageValues"
        ]
        self.assertEqual(len(native_calls), 2)
        block_identifier = {
            "blockHash": block_hash,
            "requireCanonical": True,
        }
        self.assertEqual(
            [call.args[1][1] for call in native_calls],
            [block_identifier, block_identifier],
        )
        checksum_proxy = Web3.to_checksum_address(VOTING_PROXY)
        chunks = [
            call.args[1][0][checksum_proxy]
            for call in native_calls
        ]
        self.assertEqual([len(chunk) for chunk in chunks], [1024, 1])
        self.assertEqual(
            chunks[0][-1],
            "0x" + (1023).to_bytes(32, "big").hex(),
        )
        self.assertEqual(
            chunks[1],
            ["0x" + ABSENT_HIGH_SLOT.to_bytes(32, "big").hex()],
        )

        selected_slots = [0, 1023, ABSENT_HIGH_SLOT]
        standard_words = await asyncio.gather(
            *(
                web3.eth.get_storage_at(
                    checksum_proxy,
                    slot,
                    block_identifier=block_identifier,
                )
                for slot in selected_slots
            )
        )
        standard = {
            slot: "0x" + value.hex()
            for slot, value in zip(selected_slots, standard_words, strict=True)
        }
        self.assertEqual(
            {slot: native[slot] for slot in selected_slots},
            standard,
        )
        self.assertEqual(native[ABSENT_HIGH_SLOT], ZERO_WORD)

    async def test_exact_voting_proxy_resolution_uses_integer_slots(self):
        attempt, block_number, _block_hash = await self._voting_attempt()
        checksum_proxy = Web3.to_checksum_address(VOTING_PROXY)
        bytecode = await attempt.get_code(1, checksum_proxy, block_number)
        test = self

        class StrictAttempt:
            def __init__(self):
                self.storage_calls = []

            def __getattr__(self, name):
                return getattr(attempt, name)

            async def get_storage_values(
                self,
                chain_id,
                address,
                slots,
                block,
            ):
                test.assertTrue(all(type(slot) is int for slot in slots))
                self.storage_calls.append(list(slots))
                return await attempt.get_storage_values(
                    chain_id,
                    address,
                    slots,
                    block,
                )

        strict_attempt = StrictAttempt()
        resolver = ContractResolver(
            strict_attempt,
            self.settings,
            verification_service=object(),
            source_cache_repo=object(),
        )

        proxy = await resolver.detect_proxy(
            1,
            checksum_proxy,
            block=block_number,
            bytecode=bytes(bytecode),
        )

        self.assertIsNotNone(proxy)
        self.assertEqual(proxy.proxy_type, "erc897")
        self.assertEqual(
            proxy.implementation_address.lower(),
            VOTING_IMPLEMENTATION,
        )
        self.assertEqual(
            strict_attempt.storage_calls,
            [[
                EIP1967_IMPL_SLOT,
                EIP1822_SLOT,
                ZEPPELINOS_IMPL_SLOT,
                EIP1967_BEACON_SLOT,
            ]],
        )


if __name__ == "__main__":
    unittest.main()
