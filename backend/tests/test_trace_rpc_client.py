import copy
import unittest

from app.config import Settings
from app.models.errors import TraceNotAvailableError
from app.services.tracer.rpc_client import TraceRPCClient


ADDRESS = "0x" + "11" * 20
CALL_TARGET = "0x" + "aa" * 20
EIP_TARGET = "0x" + "bb" * 20
ZERO_WORD = "0x" + "00" * 32
ONE_WORD = "0x" + "00" * 31 + "01"


def frame(
    frame_id,
    parent_id,
    frame_type,
    depth,
    storage,
    requested,
    *,
    outcome="succeeded",
    faulted=False,
    exit_error=None,
    completion_word=ONE_WORD,
    code_address=None,
    code_attribution="exact",
    code_source="direct",
    code_designator=None,
):
    if code_address is None and code_attribution == "exact":
        code_address = requested
    return {
        "id": frame_id,
        "parent_id": parent_id,
        "type": frame_type,
        "depth": depth,
        "storage_address": storage,
        "requested_code_address": requested,
        "code_address": code_address,
        "code_attribution": code_attribution,
        "code_source": code_source,
        "code_designator": code_designator,
        "target_confirmed": True,
        "faulted": faulted,
        "exit_error": exit_error,
        "outcome": outcome,
        "completion_validated": True,
        "completion_word": completion_word,
    }


def valid_result():
    return {
        "fatal": None,
        "executable": True,
        "stepCount": 10,
        "hookEnters": 1,
        "hookExits": 1,
        "frameStack": [0],
        "writes": [
            {
                "pc": 7,
                "slot": "0x1",
                "value": "0x2",
                "old_value": None,
                "opcode": "SSTORE",
                "namespace": "persistent",
                "depth": 2,
                "index": 5,
                "frame_id": 1,
            }
        ],
        "sha3s": [],
        "frames": [
            frame(
                0,
                None,
                "ROOT",
                1,
                ADDRESS,
                ADDRESS,
                completion_word=None,
            ),
            frame(
                1,
                0,
                "DELEGATECALL",
                2,
                ADDRESS,
                CALL_TARGET,
            ),
        ],
        "lastOp": "STOP",
        "lastDepth": 1,
    }


class _ResultProvider:
    def __init__(self, result):
        self.result = result

    async def make_request(self, chain_id, method, params):
        return {"result": copy.deepcopy(self.result)}


class CompactTraceValidatorTests(unittest.TestCase):
    def setUp(self):
        self.client = TraceRPCClient(object(), Settings())

    def decode(self, result=None):
        return self.client._decode_compact_trace_result(
            copy.deepcopy(result or valid_result())
        )

    def test_valid_delegate_frame_is_flattened_without_reconstructing_it(self):
        writes, sha3s, step_count = self.decode()

        self.assertEqual(step_count, 10)
        self.assertEqual(sha3s, [])
        self.assertEqual(writes[0]["address"], ADDRESS)
        self.assertEqual(writes[0]["code_address"], CALL_TARGET)
        self.assertEqual(writes[0]["slot"], "0x" + "0" * 63 + "1")
        self.assertEqual(writes[0]["value"], "0x" + "0" * 63 + "2")
        self.assertFalse(writes[0]["frame_reverted"])

    def test_caught_child_failure_reverts_only_the_child_write(self):
        result = valid_result()
        result["frames"][1].update(
            {
                "outcome": "failed",
                "faulted": True,
                "exit_error": "execution reverted",
                "completion_word": ZERO_WORD,
            }
        )

        writes, _, _ = self.decode(result)

        self.assertTrue(writes[0]["frame_failed"])
        self.assertTrue(writes[0]["frame_reverted"])
        self.assertEqual(writes[0]["rollback_frame_id"], 1)
        self.assertIsNone(writes[0]["rollback_parent_id"])

    def test_failed_root_reverts_successful_descendant_write(self):
        result = valid_result()
        result["frames"][0].update(
            {
                "outcome": "failed",
                "faulted": True,
                "exit_error": "execution reverted",
            }
        )

        writes, _, _ = self.decode(result)

        self.assertFalse(writes[0]["frame_failed"])
        self.assertTrue(writes[0]["frame_reverted"])
        self.assertEqual(writes[0]["rollback_frame_id"], 0)

    def test_valid_one_hop_eip7702_resolution_is_accepted(self):
        result = valid_result()
        result["frames"][1].update(
            {
                "code_address": EIP_TARGET,
                "code_source": "eip7702",
                "code_designator": "0xef0100" + EIP_TARGET[2:],
            }
        )

        writes, _, _ = self.decode(result)

        self.assertEqual(writes[0]["code_address"], EIP_TARGET)
        self.assertEqual(writes[0]["code_attribution"], "exact")

    def test_unknown_code_attribution_retains_the_raw_write(self):
        result = valid_result()
        result["frames"][1].update(
            {
                "code_address": None,
                "code_attribution": "unknown",
                "code_source": "unknown",
                "code_designator": None,
            }
        )

        writes, _, _ = self.decode(result)

        self.assertIsNone(writes[0]["code_address"])
        self.assertEqual(writes[0]["code_attribution"], "unknown")

    def test_sha3_preimage_is_strictly_validated_and_hashed(self):
        result = valid_result()
        result["sha3s"] = [
            {
                "address": ADDRESS,
                "preimage": "0x" + "12" * 32,
                "size": 32,
                "depth": 2,
            }
        ]

        _, sha3s, _ = self.decode(result)

        self.assertEqual(sha3s[0]["preimage"], "0x" + "12" * 32)
        self.assertEqual(len(sha3s[0]["hash"]), 64)

    def test_legitimate_noop_trace_is_not_marked_executable(self):
        result = {
            "fatal": None,
            "executable": False,
            "stepCount": 0,
            "hookEnters": 0,
            "hookExits": 0,
            "frameStack": [],
            "writes": [],
            "sha3s": [],
            "frames": [],
        }

        self.assertEqual(self.decode(result), ([], [], 0))

    def test_malformed_evidence_is_rejected_before_normalization(self):
        cases = {}

        boolean_id = valid_result()
        boolean_id["frames"][1]["id"] = True
        cases["boolean frame id"] = boolean_id

        long_address = valid_result()
        long_address["frames"][1]["storage_address"] = "0x" + "11" * 21
        cases["overlong address"] = long_address

        long_word = valid_result()
        long_word["writes"][0]["slot"] = "0x1" + "00" * 32
        cases["overlong word"] = long_word

        missing_parent = valid_result()
        missing_parent["frames"][1]["parent_id"] = 9
        cases["missing parent"] = missing_parent

        bad_completion = valid_result()
        bad_completion["frames"][1]["completion_word"] = ZERO_WORD
        cases["completion contradiction"] = bad_completion

        bad_designator = valid_result()
        bad_designator["frames"][1].update(
            {
                "code_address": EIP_TARGET,
                "code_source": "eip7702",
                "code_designator": "0xef0100" + "bb" * 19,
            }
        )
        cases["invalid EIP-7702 designator"] = bad_designator

        malformed_preimage = valid_result()
        malformed_preimage["sha3s"] = [
            {
                "address": ADDRESS,
                "preimage": "0x12",
                "size": 32,
                "depth": 2,
            }
        ]
        cases["truncated preimage"] = malformed_preimage

        unbalanced_hooks = valid_result()
        unbalanced_hooks["hookExits"] = 0
        cases["unbalanced hooks"] = unbalanced_hooks

        root_contradiction = valid_result()
        root_contradiction["frames"][0]["outcome"] = "failed"
        cases["root outcome contradiction"] = root_contradiction

        malformed_last_op = valid_result()
        malformed_last_op["lastOp"] = ["STOP"]
        cases["malformed final opcode"] = malformed_last_op

        for name, result in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.decode(result)

    def test_frames_not_referenced_by_writes_are_rejected(self):
        result = valid_result()
        result["hookEnters"] = 2
        result["hookExits"] = 2
        result["frames"].append(
            frame(
                2,
                0,
                "CALL",
                2,
                EIP_TARGET,
                EIP_TARGET,
            )
        )

        with self.assertRaisesRegex(ValueError, "not reduced"):
            self.decode(result)

    def test_each_limit_marker_uses_the_trace_limit_path(self):
        for marker in (
            "limit:steps",
            "limit:writes",
            "limit:sha3",
            "limit:preimage_bytes",
        ):
            with self.subTest(marker=marker), self.assertRaises(
                TraceNotAvailableError
            ):
                self.decode({"fatal": marker})

    def test_callback_fatal_is_rejected_as_malformed_evidence(self):
        with self.assertRaisesRegex(ValueError, "callback failed"):
            self.decode({"fatal": "tracer:exception"})


class CompactTraceRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_failure_degrades_without_caching_evidence(self):
        client = TraceRPCClient(_ResultProvider({"fatal": "tracer:exception"}))

        result = await client.execute_structlogs_trace(1, "0x" + "ab" * 32)

        self.assertEqual(result, ([], [], 0, "tracer_unavailable"))

    async def test_limit_failure_uses_the_stable_trace_limit_reason(self):
        client = TraceRPCClient(_ResultProvider({"fatal": "limit:steps"}))

        result = await client.execute_structlogs_trace(1, "0x" + "ab" * 32)

        self.assertEqual(result, ([], [], 0, "trace_limit"))


if __name__ == "__main__":
    unittest.main()
