import os
import unittest

from app.config import Settings
from app.services.tracer.rpc_client import TraceRPCClient
from app.services.web3_provider import Web3Provider


RUN_CONFORMANCE = os.environ.get("RUN_RETH_TRACER_CONFORMANCE") == "1"
FROM = "0x1000000000000000000000000000000000000001"
ROOT = "0x2000000000000000000000000000000000000002"
TARGET = "0x3000000000000000000000000000000000000003"
AUTHORITY = "0x4000000000000000000000000000000000000004"
DELEGATE = "0x5000000000000000000000000000000000000005"
BENEFICIARY = "0x6000000000000000000000000000000000000006"
PRECOMPILE = "0x0000000000000000000000000000000000000001"
VOTING_TX = (
    "0xa1fc48efe579dde86c1b46ced4d5a2cb"
    "589c95609be976539eb4d5b3513e2f56"
)
VOTING_SLOT = (
    "0x0251ce03e055d3e1e4d121004047584d"
    "fce20cb4c02d76b24d1e17f2b0181cdf"
)
VOTING_PROXY = "0xe478de485ad2fe566d49342cbd03e49ed7db3356"
VOTING_IMPLEMENTATION = "0xa4d1a2693589840babb7f3a44d14fdf41b3bf1fe"


def call_bytecode(target):
    return "6000600060006000600073" + target[2:] + "5af1"


@unittest.skipUnless(
    RUN_CONFORMANCE,
    "set RUN_RETH_TRACER_CONFORMANCE=1 for deployment-provider checks",
)
class RethTracerConformanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = Settings()
        self.provider = Web3Provider(self.settings)
        self.client = TraceRPCClient(self.provider, self.settings)

    async def asyncTearDown(self):
        await self.provider.close()

    async def trace_call(
        self,
        code,
        *,
        overrides=None,
        tracer_source=None,
    ):
        state_overrides = {
            FROM: {"balance": "0x1000000000000000000"},
            ROOT: {
                "balance": "0x1000000000000000000",
                "code": "0x" + code,
                "nonce": "0x0",
            },
        }
        state_overrides.update(overrides or {})
        response = await self.provider.make_request(
            1,
            "debug_traceCall",
            [
                {
                    "from": FROM,
                    "to": ROOT,
                    "gas": "0x989680",
                },
                "latest",
                {
                    "tracer": (
                        tracer_source
                        or self.client._compact_storage_tracer_source()
                    ),
                    "stateOverrides": state_overrides,
                },
            ],
        )
        self.assertNotIn("error", response)
        return response["result"]

    async def test_provider_contract_and_voting_delegate_attribution(self):
        version = await self.provider.make_request(1, "web3_clientVersion", [])
        self.assertTrue(version["result"].startswith("reth/v2.3.0"))

        result = await self.client._execute_compact_storage_trace(1, VOTING_TX)

        self.assertIsNotNone(result)
        writes, sha3s, step_count = result
        target = [write for write in writes if write["slot"] == VOTING_SLOT]
        self.assertEqual(step_count, 167759)
        self.assertEqual(len(writes), 99)
        self.assertEqual(len(sha3s), 275)
        self.assertEqual(len(target), 1)
        self.assertEqual(target[0]["address"], VOTING_PROXY)
        self.assertEqual(
            target[0]["code_address"],
            VOTING_IMPLEMENTATION,
        )

    async def test_calls_and_caught_or_uncaught_reverts(self):
        target_success = "0x600160005500"
        target_revert = "0x600160005560006000fd"
        harness = call_bytecode(TARGET) + "60015500"

        success_raw = await self.trace_call(
            harness,
            overrides={TARGET: {"code": target_success}},
        )
        success_writes, _, _ = self.client._decode_compact_trace_result(
            success_raw
        )
        child_success = next(
            write for write in success_writes if write["address"] == TARGET
        )
        self.assertFalse(child_success["frame_reverted"])

        caught_raw = await self.trace_call(
            harness,
            overrides={TARGET: {"code": target_revert}},
        )
        caught_writes, _, _ = self.client._decode_compact_trace_result(
            caught_raw
        )
        child_failure = next(
            write for write in caught_writes if write["address"] == TARGET
        )
        root_after_catch = next(
            write for write in caught_writes if write["address"] == ROOT
        )
        self.assertTrue(child_failure["frame_reverted"])
        self.assertFalse(root_after_catch["frame_reverted"])
        self.assertEqual(root_after_catch["value"], "0x" + "0" * 64)

        uncaught_raw = await self.trace_call(target_revert[2:])
        uncaught_writes, _, _ = self.client._decode_compact_trace_result(
            uncaught_raw
        )
        self.assertTrue(uncaught_writes[0]["frame_reverted"])
        self.assertEqual(uncaught_writes[0]["rollback_frame_id"], 0)

    async def test_creation_failure_and_eip7702_resolution(self):
        creation_failure = (
            "600a6012600039600a60006000f060015500"
            "600160005560006000fd"
        )
        creation_raw = await self.trace_call(creation_failure)
        creation_writes, _, _ = self.client._decode_compact_trace_result(
            creation_raw
        )
        constructor_write = next(
            write
            for write in creation_writes
            if write["address"] != ROOT
        )
        self.assertTrue(constructor_write["frame_reverted"])
        create_frame = next(
            frame
            for frame in creation_raw["frames"]
            if frame["type"] == "CREATE"
        )
        self.assertEqual(create_frame["outcome"], "failed")
        self.assertEqual(create_frame["completion_word"], "0x" + "0" * 64)

        authority_harness = call_bytecode(AUTHORITY) + "60015500"
        eip_raw = await self.trace_call(
            authority_harness,
            overrides={
                AUTHORITY: {"code": "0xef0100" + DELEGATE[2:]},
                DELEGATE: {"code": "0x600160005500"},
            },
        )
        eip_writes, _, _ = self.client._decode_compact_trace_result(eip_raw)
        delegated_write = next(
            write
            for write in eip_writes
            if write["address"] == AUTHORITY
        )
        self.assertEqual(delegated_write["code_address"], DELEGATE)
        eip_frame = next(
            frame
            for frame in eip_raw["frames"]
            if frame["storage_address"] == AUTHORITY
        )
        self.assertEqual(eip_frame["code_source"], "eip7702")
        self.assertEqual(
            eip_frame["code_designator"],
            "0xef0100" + DELEGATE[2:],
        )

    async def test_empty_precompile_and_selfdestruct_hooks_balance(self):
        empty_and_precompile = (
            call_bytecode(TARGET)
            + "50"
            + call_bytecode(PRECOMPILE)
            + "50600160005500"
        )
        empty_raw = await self.trace_call(empty_and_precompile)
        self.client._decode_compact_trace_result(empty_raw)
        self.assertEqual(empty_raw["hookEnters"], 2)
        self.assertEqual(empty_raw["hookExits"], 2)
        self.assertEqual([frame["id"] for frame in empty_raw["frames"]], [0])

        selfdestruct_harness = call_bytecode(TARGET) + "60015500"
        selfdestruct_raw = await self.trace_call(
            selfdestruct_harness,
            overrides={
                TARGET: {
                    "balance": "0x1",
                    "code": "0x73" + BENEFICIARY[2:] + "ff",
                }
            },
        )
        self.client._decode_compact_trace_result(selfdestruct_raw)
        self.assertEqual(selfdestruct_raw["hookEnters"], 2)
        self.assertEqual(selfdestruct_raw["hookExits"], 2)
        self.assertEqual(
            [frame["id"] for frame in selfdestruct_raw["frames"]],
            [0],
        )

    async def test_every_limit_and_callback_exception_fail_closed(self):
        sha3_program = "600160005260206000205000"
        cases = (
            (
                "limit:steps",
                Settings(MAX_TRACE_STEPS=1),
                "600160005500",
            ),
            (
                "limit:writes",
                Settings(MAX_SSTORE_OPS=0),
                "600160005500",
            ),
            (
                "limit:sha3",
                Settings(MAX_TRACE_SHA3_OPS=0),
                sha3_program,
            ),
            (
                "limit:preimage_bytes",
                Settings(MAX_TRACE_PREIMAGE_BYTES=31),
                sha3_program,
            ),
        )
        for marker, settings, program in cases:
            with self.subTest(marker=marker):
                source = TraceRPCClient(
                    self.provider,
                    settings,
                )._compact_storage_tracer_source()
                result = await self.trace_call(
                    program,
                    tracer_source=source,
                )
                self.assertEqual(result["fatal"], marker)

        source = self.client._compact_storage_tracer_source()
        injected = source.replace(
            "this.ensureRoot(log, db);",
            "throw new Error('conformance callback failure');",
            1,
        )
        self.assertNotEqual(source, injected)
        callback_result = await self.trace_call(
            "600160005500",
            tracer_source=injected,
        )
        self.assertEqual(callback_result["fatal"], "tracer:exception")


if __name__ == "__main__":
    unittest.main()
