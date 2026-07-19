import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from web3 import Web3

from app.config import Settings
from app.services.web3_provider import Web3Provider


RUN_CONFORMANCE = os.environ.get("RUN_RETH_STORAGE_CONFORMANCE") == "1"
VOTING_TX = (
    "0xa1fc48efe579dde86c1b46ced4d5a2cb"
    "589c95609be976539eb4d5b3513e2f56"
)
VOTING_PROXY = "0xe478de485ad2fe566d49342cbd03e49ed7db3356"


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

    async def test_exact_native_vector_matches_256_standard_reads(self):
        version = await self.provider.make_request(1, "web3_clientVersion", [])
        self.assertTrue(version["result"].startswith("reth/v2.3.0"))
        receipt = await self.provider.get_transaction_receipt(1, VOTING_TX)
        block_number = int(receipt["blockNumber"])
        web3 = self.provider.get_web3(1)
        block = await web3.eth.get_block(block_number)
        block_hash = block["hash"].hex()
        if not block_hash.startswith("0x"):
            block_hash = "0x" + block_hash
        attempt = await self.provider.create_exact_storage_attempt(
            1,
            block_number,
            block_hash,
        )
        slots = list(range(256))
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

        native_calls = [
            call
            for call in make_request.await_args_list
            if call.args[0] == "eth_getStorageValues"
        ]
        self.assertEqual(len(native_calls), 1)
        self.assertEqual(
            native_calls[0].args[1][1],
            {"blockHash": block_hash.lower(), "requireCanonical": True},
        )

        standard_words = await asyncio.gather(
            *(
                web3.eth.get_storage_at(
                    Web3.to_checksum_address(VOTING_PROXY),
                    slot,
                    block_identifier={
                        "blockHash": block_hash,
                        "requireCanonical": True,
                    },
                )
                for slot in slots
            )
        )
        standard = {
            slot: "0x" + value.hex()
            for slot, value in zip(slots, standard_words, strict=True)
        }
        self.assertEqual(native, standard)

    async def test_latest_tag_is_forwarded_unchanged(self):
        web3 = self.provider.get_web3(1)
        original_make_request = web3.provider.make_request

        with patch.object(
            web3.provider,
            "make_request",
            AsyncMock(wraps=original_make_request),
        ) as make_request:
            values = await self.provider.get_storage_values(
                1,
                VOTING_PROXY,
                [0],
                "latest",
            )

        self.assertEqual(len(values[0]), 66)
        native_call = next(
            call
            for call in make_request.await_args_list
            if call.args[0] == "eth_getStorageValues"
        )
        self.assertEqual(native_call.args[1][1], "latest")


if __name__ == "__main__":
    unittest.main()
