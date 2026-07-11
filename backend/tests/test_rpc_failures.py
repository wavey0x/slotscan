import unittest

from app.config import Settings
from app.models.errors import RPCError
from app.services.decoder import TypeDecoder
from app.services.storage import StorageReader
from app.models.domain import StorageLayout, StorageType, StorageVariable


class _UnusedProvider:
    pass


class RPCFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_individual_failure_is_not_replaced_with_zero(self):
        reader = StorageReader(_UnusedProvider(), Settings(), TypeDecoder())

        async def read_slot(chain_id, address, slot, block):
            if slot == 2:
                raise RPCError("eth_getStorageAt", "boom")
            return "0x" + "00" * 32

        reader.read_slot = read_slot
        with self.assertRaisesRegex(RPCError, "slot 2"):
            await reader._read_slots_individual(1, "0x" + "11" * 20, [1, 2], 100)


class _BatchProvider:
    def __init__(self):
        self.slots = []

    async def batch_get_storage_at(self, chain_id, address, slots, block):
        self.slots.extend(slots)
        return {slot: "0x" + "00" * 32 for slot in slots}


class StorageBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_slot_budget_is_enforced_before_rpc_work(self):
        provider = _BatchProvider()
        settings = Settings(MAX_SLOTS_PER_CONTRACT=3)
        reader = StorageReader(provider, settings, TypeDecoder())
        element = StorageType("t_uint256", "uint256", "value", "inplace", 32)
        array = StorageType(
            "t_array",
            "uint256[10]",
            "array",
            "inplace",
            320,
            element_type=element.id,
            array_length=10,
        )
        layout = StorageLayout(
            "Large",
            [StorageVariable("values", 0, 0, 320, array.id, array.label)],
            {element.id: element, array.id: array},
        )
        snapshot = await reader.read_at_block(
            1,
            "0x" + "11" * 20,
            100,
            layout,
        )
        self.assertEqual(provider.slots, [0, 1, 2])
        self.assertFalse(snapshot.is_complete)


if __name__ == "__main__":
    unittest.main()
