import unittest

from web3 import Web3

from app.config import Settings
from app.services.decoder import TypeDecoder
from app.services.namespace_storage import NamespaceStorageParser
from app.services.storage import StorageReader
from app.utils.vyper import LEGACY_HASHED_STORAGE, SEQUENTIAL_STORAGE


ZERO_WORD = "0x" + "00" * 32


def uint_word(value: int) -> str:
    return f"0x{value:064x}"


def text_word(value: str) -> str:
    return "0x" + value.encode().hex().ljust(64, "0")


class _StorageProvider:
    def __init__(self, values: dict[int, str]):
        self.values = values
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


class VyperStringStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_vyper_024_strings_read_hashed_length_and_payload_slots(self):
        layout = NamespaceStorageParser().parse_vyper_storage(
            {
                "VotingEscrow.vy": """
# @version 0.2.4
struct Point:
    bias: int128
    slope: int128
    ts: uint256
    blk: uint256
struct LockedBalance:
    amount: int128
    end: uint256
token: public(address)
supply: public(uint256)
locked: public(HashMap[address, LockedBalance])
epoch: public(uint256)
point_history: public(Point[100000000000000000000000000000])
user_point_history: public(HashMap[address, Point[1000000000]])
user_point_epoch: public(HashMap[address, uint256])
slope_changes: public(HashMap[uint256, int128])
controller: public(address)
transfersEnabled: public(bool)
name: public(String[64])
symbol: public(String[32])
version: public(String[32])
"""
            },
            "VotingEscrow",
            "0.2.4+commit.7949850",
        )
        self.assertEqual(layout.storage_scheme, LEGACY_HASHED_STORAGE)

        expected = {
            "name": "Vote-escrowed CRV",
            "symbol": "veCRV",
            "version": "veCRV_1.0.0",
        }
        values: dict[int, str] = {}
        roots: dict[str, int] = {}
        for variable in layout.variables:
            if variable.name not in expected:
                continue
            value = expected[variable.name]
            root = int.from_bytes(
                Web3.keccak(variable.slot.to_bytes(32, "big")),
                "big",
            )
            roots[variable.name] = root
            values[root] = uint_word(len(value.encode()))
            values[root + 1] = text_word(value)

        provider = _StorageProvider(values)
        reader = StorageReader(
            provider,
            Settings(MAX_SLOTS_PER_CONTRACT=32),
            TypeDecoder(),
        )
        snapshot = await reader.read_at_block(
            1,
            "0x" + "11" * 20,
            123,
            layout,
        )

        by_name = {
            slot.variable.name: slot
            for slot in snapshot.slots
            if slot.variable.name in expected
        }
        self.assertTrue(snapshot.is_complete)
        self.assertEqual(
            {name: slot.decoded_value.decoded for name, slot in by_name.items()},
            expected,
        )
        self.assertEqual(
            {name: slot.slot for name, slot in by_name.items()},
            {"name": "0xa", "symbol": "0xb", "version": "0xc"},
        )
        self.assertNotIn(4, provider.requested_slots)
        for name, root in roots.items():
            self.assertIn(root, provider.requested_slots, name)
            self.assertIn(root + 1, provider.requested_slots, name)

    async def test_modern_vyper_strings_remain_sequential(self):
        layout = NamespaceStorageParser().parse_vyper_storage(
            {"Token.vy": "# @version 0.3.10\nname: public(String[32])\n"},
            "Token",
            "0.3.10",
        )
        self.assertEqual(layout.storage_scheme, SEQUENTIAL_STORAGE)

        provider = _StorageProvider({0: uint_word(4), 1: text_word("Test")})
        reader = StorageReader(provider, Settings(), TypeDecoder())
        snapshot = await reader.read_at_block(
            1,
            "0x" + "22" * 20,
            123,
            layout,
        )

        self.assertEqual(snapshot.slots[0].decoded_value.decoded, "Test")
        self.assertIn(0, provider.requested_slots)
        self.assertIn(1, provider.requested_slots)


if __name__ == "__main__":
    unittest.main()
