import unittest

from app.models.errors import RPCError
from app.models.domain import StorageLayout, StorageType, StorageVariable
from app.services.compiled_layout import compile_layout
from app.services.storage import StorageReader, plan_compiled_scalar_reads


class _FailingBatchProvider:
    async def batch_get_storage_at(self, *args, **kwargs):
        raise RuntimeError("boom")


class RPCFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_failure_is_not_retried_or_replaced_with_zero(self):
        reader = StorageReader(_FailingBatchProvider())

        with self.assertRaisesRegex(RPCError, "boom"):
            await reader.read_slots_batch(
                1,
                "0x" + "11" * 20,
                [1, 2],
                100,
            )


class StorageBudgetTests(unittest.TestCase):
    def test_slot_budget_is_enforced_before_rpc_work(self):
        element = StorageType("t_uint256", "uint256", "value", "inplace", 32)
        layout = compile_layout(
            StorageLayout(
                "Large",
                [
                    StorageVariable(
                        f"value_{slot}",
                        slot,
                        0,
                        32,
                        element.id,
                        element.label,
                    )
                    for slot in range(4)
                ],
                {element.id: element},
                language="Solidity",
                compiler_version="0.8.30",
                storage_scheme="solidity",
            )
        )
        plan = plan_compiled_scalar_reads(layout, max_words=3)

        self.assertEqual(plan.words, (0, 1, 2))
        self.assertEqual(plan.projections[-1].status, "deferred_budget")


if __name__ == "__main__":
    unittest.main()
