import os
import unittest

from app.config import Settings
from app.services.transaction_receipt import ReceiptIdentity
from app.services.tracer.extractor import TransactionTraceExtractor
from app.services.tracer.journal import StorageJournalBuilder
from app.services.tracer.rpc_client import TraceRPCClient
from app.services.web3_provider import Web3Provider
from tests.reth_js_oracle import TraceRPCClient as JsOracleTraceRPCClient


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


def delegatecall_bytecode(target):
    return "600060006000600073" + target[2:] + "5af4"


def callcode_bytecode(target):
    return "6000600060006000600073" + target[2:] + "5af2"


def normalized_word(value):
    return "0x" + value.removeprefix("0x").lower().zfill(64)


def normalized_prestate_storage(prestate):
    return {
        address.lower(): {
            normalized_word(slot): normalized_word(value)
            for slot, value in state.get("storage", {}).items()
        }
        for address, state in prestate.items()
        if state.get("storage")
    }


@unittest.skipUnless(
    RUN_CONFORMANCE,
    "set RUN_RETH_TRACER_CONFORMANCE=1 for deployment-provider checks",
)
class RethTracerConformanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = Settings()
        self.provider = Web3Provider(self.settings)
        self.client = JsOracleTraceRPCClient(self.provider, self.settings)
        self.native_client = TraceRPCClient(self.provider, self.settings)

    async def asyncTearDown(self):
        await self.provider.close()

    async def trace_call(
        self,
        code,
        *,
        overrides=None,
        tracer_source=None,
    ):
        return await self._trace_call(
            code,
            overrides=overrides,
            tracer=(
                tracer_source
                or self.client._compact_storage_tracer_source()
            ),
        )

    async def _trace_call(
        self,
        code,
        *,
        overrides=None,
        tracer,
        tracer_config=None,
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
        trace_config = {
            "tracer": tracer,
            "stateOverrides": state_overrides,
        }
        if tracer_config is not None:
            trace_config["tracerConfig"] = tracer_config
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
                trace_config,
            ],
        )
        self.assertNotIn("error", response)
        return response["result"]

    async def trace_call_differential(
        self,
        code,
        *,
        overrides=None,
        client=None,
        tracer_source=None,
    ):
        compact_client = client or self.client
        compact_raw = await self.trace_call(
            code,
            overrides=overrides,
            tracer_source=(
                tracer_source
                or compact_client._compact_storage_tracer_source()
            ),
        )
        compact = compact_client._decode_compact_trace_result(compact_raw)
        full_prestate = await self._trace_call(
            code,
            overrides=overrides,
            tracer="prestateTracer",
            tracer_config={"diffMode": False},
        )
        expected_storage = normalized_prestate_storage(full_prestate)
        has_persistent_writes = any(
            write["namespace"] == "persistent"
            for write in compact.writes
        )
        if compact.observed_storage_complete:
            if has_persistent_writes:
                self.assertEqual(
                    compact.observed_storage,
                    expected_storage,
                )
            else:
                self.assertEqual(compact.observed_storage, {})
        return compact_raw, compact, expected_storage

    async def test_provider_contract_and_voting_delegate_attribution(self):
        version = await self.provider.make_request(1, "web3_clientVersion", [])
        self.assertRegex(version["result"], r"^reth/v\d+\.\d+\.\d+")

        oracle = await self.client._execute_compact_storage_trace(1, VOTING_TX)
        native = await self.native_client.execute_slotscan_trace(1, VOTING_TX)
        receipt = await self.native_client.get_receipt(1, VOTING_TX)
        receipt_identity = ReceiptIdentity.from_receipt(receipt)

        self.assertIsNotNone(oracle)
        target = [
            write for write in native.writes if write["slot"] == VOTING_SLOT
        ]
        self.assertEqual(native.evm_step_count, 167759)
        self.assertEqual(len(native.writes), 99)
        self.assertEqual(len(native.sha3_operations), 275)
        self.assertEqual(len(target), 1)
        self.assertEqual(target[0]["address"], VOTING_PROXY)
        self.assertEqual(
            target[0]["code_address"],
            VOTING_IMPLEMENTATION,
        )
        self.assertTrue(native.observed_storage_complete)
        self.assertIsNotNone(target[0]["old_value"])
        self.assertEqual(receipt_identity.block_hash, native.block_hash)
        self.assertEqual(
            receipt_identity.transaction_index,
            native.transaction_index,
        )
        self.assertEqual(receipt_identity.root_succeeded, native.root_succeeded)

        identity_fields = (
            "address",
            "code_address",
            "code_attribution",
            "pc",
            "slot",
            "value",
            "opcode",
            "namespace",
            "depth",
            "index",
            "frame_id",
            "frame_parent_id",
            "frame_failed",
            "frame_reverted",
            "rollback_frame_id",
            "rollback_parent_id",
        )
        self.assertEqual(
            [
                tuple(write[field] for field in identity_fields)
                for write in native.writes
            ],
            [
                tuple(write[field] for field in identity_fields)
                for write in oracle.writes
            ],
        )
        self.assertEqual(native.sha3_operations, oracle.sha3_operations)
        self.assertEqual(native.observed_storage, oracle.observed_storage)
        self.assertEqual(
            native.observed_storage_complete,
            oracle.observed_storage_complete,
        )

        diff_response = await self.provider.make_request(
            1,
            "debug_traceTransaction",
            [
                VOTING_TX,
                {
                    "tracer": "prestateTracer",
                    "tracerConfig": {"diffMode": True},
                },
            ],
        )
        self.assertNotIn("error", diff_response)
        oracle_diff = diff_response["result"]
        TransactionTraceExtractor._normalize_diff(oracle_diff)
        self.assertEqual(native.prestate_diff, oracle_diff)

        journal = StorageJournalBuilder().build(
            native.writes,
            native.prestate_diff,
            root_succeeded=native.root_succeeded,
            evm_step_count=native.evm_step_count,
        )
        self.assertTrue(journal.capabilities.state_reconciliation)

    async def test_calls_and_caught_or_uncaught_reverts(self):
        target_success = "0x600160005500"
        target_revert = "0x600160005560006000fd"
        harness = call_bytecode(TARGET) + "60015500"

        _success_raw, success, _success_prestate = (
            await self.trace_call_differential(
                harness,
                overrides={TARGET: {"code": target_success}},
            )
        )
        success_writes = success.writes
        child_success = next(
            write for write in success_writes if write["address"] == TARGET
        )
        self.assertFalse(child_success["frame_reverted"])

        _caught_raw, caught, _caught_prestate = (
            await self.trace_call_differential(
                harness,
                overrides={TARGET: {"code": target_revert}},
            )
        )
        caught_writes = caught.writes
        child_failure = next(
            write for write in caught_writes if write["address"] == TARGET
        )
        root_after_catch = next(
            write for write in caught_writes if write["address"] == ROOT
        )
        self.assertTrue(child_failure["frame_reverted"])
        self.assertFalse(root_after_catch["frame_reverted"])
        self.assertEqual(root_after_catch["value"], "0x" + "0" * 64)

        _uncaught_raw, uncaught, _uncaught_prestate = (
            await self.trace_call_differential(target_revert[2:])
        )
        self.assertTrue(uncaught.writes[0]["frame_reverted"])
        self.assertEqual(uncaught.writes[0]["rollback_frame_id"], 0)

    async def test_delegatecall_and_callcode_storage_ownership(self):
        target_code = "0x600160005500"
        cases = (
            ("DELEGATECALL", delegatecall_bytecode(TARGET) + "5000"),
            ("CALLCODE", callcode_bytecode(TARGET) + "5000"),
        )

        for expected_type, harness in cases:
            with self.subTest(expected_type=expected_type):
                raw, evidence, _prestate = (
                    await self.trace_call_differential(
                        harness,
                        overrides={TARGET: {"code": target_code}},
                    )
                )
                self.assertEqual(len(evidence.writes), 1)
                self.assertEqual(evidence.writes[0]["address"], ROOT)
                self.assertEqual(
                    evidence.writes[0]["code_address"],
                    TARGET,
                )
                child = next(
                    frame
                    for frame in raw["frames"]
                    if frame["type"] == expected_type
                )
                self.assertEqual(child["storage_address"], ROOT)
                self.assertEqual(child["code_address"], TARGET)

    async def test_creation_failure_and_eip7702_resolution(self):
        successful_creation = (
            "600a6012600039600a60006000f060015500"
            "600160005560006000f3"
        )
        success_raw, success, _success_prestate = (
            await self.trace_call_differential(successful_creation)
        )
        created_write = next(
            write
            for write in success.writes
            if write["address"] != ROOT
        )
        self.assertFalse(created_write["frame_reverted"])
        success_frame = next(
            frame
            for frame in success_raw["frames"]
            if frame["type"] == "CREATE"
        )
        self.assertEqual(success_frame["outcome"], "succeeded")

        creation_failure = (
            "600a6012600039600a60006000f060015500"
            "600160005560006000fd"
        )
        creation_raw, creation, _creation_prestate = (
            await self.trace_call_differential(creation_failure)
        )
        creation_writes = creation.writes
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
        eip_raw, eip, _eip_prestate = (
            await self.trace_call_differential(
                authority_harness,
                overrides={
                    AUTHORITY: {"code": "0xef0100" + DELEGATE[2:]},
                    DELEGATE: {"code": "0x600160005500"},
                },
            )
        )
        eip_writes = eip.writes
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
        empty_raw, _empty, _empty_prestate = (
            await self.trace_call_differential(empty_and_precompile)
        )
        self.assertEqual(empty_raw["hookEnters"], 2)
        self.assertEqual(empty_raw["hookExits"], 2)
        self.assertEqual([frame["id"] for frame in empty_raw["frames"]], [0])

        selfdestruct_harness = call_bytecode(TARGET) + "60015500"
        selfdestruct_raw, _selfdestruct, _selfdestruct_prestate = (
            await self.trace_call_differential(
                selfdestruct_harness,
                overrides={
                    TARGET: {
                        "balance": "0x1",
                        "code": "0x73" + BENEFICIARY[2:] + "ff",
                    }
                },
            )
        )
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
                source = JsOracleTraceRPCClient(
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

    async def test_observation_overflow_and_lazy_materialization(self):
        bounded_client = JsOracleTraceRPCClient(
            self.provider,
            Settings(MAX_PRESTATE_STORAGE_ENTRIES=1),
        )
        _bounded_raw, bounded, _bounded_prestate = (
            await self.trace_call_differential(
                "6001600055600260015500",
                client=bounded_client,
            )
        )
        self.assertEqual(len(bounded.writes), 2)
        self.assertFalse(bounded.observed_storage_complete)
        self.assertEqual(
            set(bounded.observed_storage[ROOT]),
            {"0x" + "0" * 64},
        )

        source = self.client._compact_storage_tracer_source()
        failing_source = source.replace("db.getState(", "db.getStateFailure(")
        self.assertNotEqual(source, failing_source)
        _failed_raw, failed, full_prestate = (
            await self.trace_call_differential(
                "60005400",
                tracer_source=failing_source,
            )
        )
        self.assertEqual(failed.writes, [])
        self.assertTrue(failed.observed_storage_complete)
        self.assertEqual(failed.observed_storage, {})
        self.assertIn(ROOT, full_prestate)

    async def test_transient_and_read_only_execution_skip_observations(self):
        _transient_raw, transient, _transient_prestate = (
            await self.trace_call_differential("600160005d00")
        )
        self.assertEqual(len(transient.writes), 1)
        self.assertEqual(transient.writes[0]["namespace"], "transient")
        self.assertEqual(transient.observed_storage, {})

        _read_raw, read_only, full_prestate = (
            await self.trace_call_differential("60005400")
        )
        self.assertEqual(read_only.writes, [])
        self.assertEqual(read_only.observed_storage, {})
        self.assertIn(ROOT, full_prestate)

    async def test_sloads_and_repeated_writes_replay_immediate_before_values(self):
        _cycle_raw, cycle, _cycle_prestate = (
            await self.trace_call_differential(
                "60006000556001600055600060005500"
            )
        )
        self.assertEqual(len(cycle.writes), 3)
        self.assertEqual(
            [write["value"] for write in cycle.writes],
            [
                "0x" + "0" * 64,
                "0x" + "0" * 63 + "1",
                "0x" + "0" * 64,
            ],
        )

        _raw, evidence, _prestate = await self.trace_call_differential(
            "600154506001600055600260005500"
        )
        slot_zero = "0x" + "0" * 64
        slot_one = "0x" + "0" * 63 + "1"

        self.assertEqual(
            set(evidence.observed_storage[ROOT]),
            {slot_zero, slot_one},
        )
        self.assertEqual(
            [write["slot"] for write in evidence.writes],
            [slot_zero, slot_zero],
        )
        self.assertTrue(all(write["old_value"] is None for write in evidence.writes))

        diff = {
            "pre": {},
            "post": {
                ROOT: {
                    "storage": {slot_zero: "0x" + "0" * 63 + "2"}
                }
            },
        }
        TransactionTraceExtractor._normalize_diff(diff)
        TransactionTraceExtractor._merge_observed_prestate(
            diff,
            evidence.observed_storage,
        )
        journal = StorageJournalBuilder().build(
            evidence.writes,
            diff,
            root_succeeded=True,
            evm_step_count=evidence.evm_step_count,
        )
        repeated = next(
            history
            for history in journal.histories
            if history.slot == slot_zero
        )
        self.assertEqual(
            [event.value_before for event in repeated.writes],
            ["0x" + "0" * 64, "0x" + "0" * 63 + "1"],
        )


if __name__ == "__main__":
    unittest.main()
