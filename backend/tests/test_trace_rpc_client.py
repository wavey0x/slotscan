import copy
import unittest

from app.config import Settings
from app.models.errors import RPCError, TraceNotAvailableError, TransactionNotFoundError
from app.services.tracer.rpc_client import TRACE_METHOD, TraceRPCClient


TX_HASH = "0x" + "ab" * 32
BLOCK_HASH = "0x" + "cd" * 32
ADDRESS = "0x" + "11" * 20
CODE_ADDRESS = "0x" + "22" * 20
SLOT = "0x" + "00" * 31 + "01"
ZERO = "0x" + "00" * 32
ONE = "0x" + "00" * 31 + "01"


def valid_result():
    return {
        "transactionHash": TX_HASH,
        "blockHash": BLOCK_HASH,
        "transactionIndex": 3,
        "rootSucceeded": True,
        "prestateDiff": {
            "pre": {
                ADDRESS: {
                    "balance": "0x1",
                    "nonce": 1,
                    "storage": {SLOT: ZERO},
                }
            },
            "post": {ADDRESS: {"storage": {SLOT: ONE}}},
        },
        "writes": [
            {
                "address": ADDRESS,
                "codeAddress": CODE_ADDRESS,
                "codeAttribution": "exact",
                "codeSource": "direct",
                "codeDesignator": None,
                "pc": 7,
                "slot": SLOT,
                "oldValue": ZERO,
                "value": ONE,
                "opcode": "SSTORE",
                "namespace": "persistent",
                "depth": 2,
                "index": 5,
                "frameId": 1,
                "frameParentId": 0,
                "frameFailed": False,
                "frameReverted": False,
                "rollbackFrameId": None,
                "rollbackParentId": None,
            }
        ],
        "sha3Operations": [
            {
                "address": ADDRESS,
                "preimage": "0x" + "12" * 32,
                "size": 32,
                "depth": 2,
            }
        ],
        "observedStorage": {ADDRESS: {SLOT: ZERO}},
        "observedStorageComplete": True,
        "stepCount": 10,
        "degradedReason": None,
    }


class _Provider:
    def __init__(self, response=None, exception=None, receipt=None):
        self.response = response
        self.exception = exception
        self.receipt = receipt
        self.calls = []

    async def make_request(self, chain_id, method, params):
        self.calls.append((chain_id, method, params))
        if self.exception:
            raise self.exception
        return copy.deepcopy(self.response)

    async def get_transaction_receipt(self, chain_id, tx_hash):
        if self.exception:
            raise self.exception
        return self.receipt


class NativeTraceRPCClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_one_native_method_with_all_limits_and_decodes_evidence(self):
        provider = _Provider(
            {"jsonrpc": "2.0", "id": 7, "result": valid_result()}
        )
        client = TraceRPCClient(
            provider,
            Settings(
                MAX_TRACE_STEPS=20,
                MAX_SSTORE_OPS=4,
                MAX_TRACE_SHA3_OPS=3,
                MAX_TRACE_PREIMAGE_BYTES=1_024,
                MAX_PRESTATE_STORAGE_ENTRIES=8,
            ),
        )

        evidence = await client.execute_slotscan_trace(1, TX_HASH.upper().replace("X", "x"))

        self.assertEqual(
            provider.calls,
            [
                (
                    1,
                    TRACE_METHOD,
                    [
                        TX_HASH,
                        {
                            "maxSteps": 20,
                            "maxWrites": 4,
                            "maxSha3Operations": 3,
                            "maxPreimageBytes": 1_024,
                            "maxObservedStorage": 8,
                        },
                    ],
                )
            ],
        )
        self.assertEqual(evidence.block_hash, BLOCK_HASH)
        self.assertEqual(evidence.writes[0]["old_value"], ZERO)
        self.assertEqual(evidence.writes[0]["code_address"], CODE_ADDRESS)
        self.assertEqual(evidence.sha3_operations[0]["preimage"], "0x" + "12" * 32)
        self.assertEqual(len(evidence.sha3_operations[0]["hash"]), 64)

    async def test_case_folds_addresses_slots_values_and_designators_together(self):
        result = valid_result()
        result["prestateDiff"] = {
            "pre": {
                ADDRESS.upper().replace("X", "x"): {
                    "storage": {
                        SLOT.upper().replace("X", "x"): ZERO.upper().replace("X", "x")
                    }
                }
            },
            "post": {},
        }
        write = result["writes"][0]
        write["address"] = write["address"].upper().replace("X", "x")
        write["codeAddress"] = CODE_ADDRESS.upper().replace("X", "x")
        write["codeSource"] = "eip7702"
        write["codeDesignator"] = (
            "0xef0100" + CODE_ADDRESS[2:]
        ).upper().replace("X", "x")
        write["slot"] = SLOT.upper().replace("X", "x")
        write["oldValue"] = ZERO.upper().replace("X", "x")
        write["value"] = ONE.upper().replace("X", "x")
        result["observedStorage"] = {
            ADDRESS.upper().replace("X", "x"): {
                SLOT.upper().replace("X", "x"): ZERO.upper().replace("X", "x")
            }
        }

        evidence = await TraceRPCClient(
            _Provider({"result": result})
        ).execute_slotscan_trace(1, TX_HASH)

        self.assertEqual(evidence.writes[0]["address"], ADDRESS)
        self.assertEqual(evidence.writes[0]["slot"], SLOT)
        self.assertEqual(evidence.writes[0]["value"], ONE)
        self.assertEqual(evidence.observed_storage, {ADDRESS: {SLOT: ZERO}})

    async def test_degraded_trace_keeps_prestate_but_rejects_partial_details(self):
        degraded = valid_result()
        degraded.update(
            {
                "writes": [],
                "sha3Operations": [],
                "observedStorage": {},
                "observedStorageComplete": False,
                "stepCount": 100,
                "degradedReason": "trace_limit",
            }
        )
        evidence = await TraceRPCClient(
            _Provider({"result": degraded}),
            Settings(MAX_TRACE_STEPS=1),
        ).execute_slotscan_trace(1, TX_HASH)

        self.assertEqual(evidence.prestate_diff["post"][ADDRESS]["storage"][SLOT], ONE)
        self.assertEqual(evidence.evm_step_count, 0)
        self.assertEqual(evidence.degraded_reason, "trace_limit")

        for field, value in (
            ("writes", valid_result()["writes"]),
            ("sha3Operations", valid_result()["sha3Operations"]),
            ("observedStorage", valid_result()["observedStorage"]),
            ("observedStorageComplete", True),
        ):
            malformed = copy.deepcopy(degraded)
            malformed[field] = value
            with self.subTest(field=field), self.assertRaises(RPCError):
                await TraceRPCClient(
                    _Provider({"result": malformed})
                ).execute_slotscan_trace(1, TX_HASH)

    async def test_rejects_malformed_envelope_and_cross_field_contradictions(self):
        cases = {}
        extra = valid_result()
        extra["unexpected"] = True
        cases["extra envelope field"] = extra
        wrong_hash = valid_result()
        wrong_hash["transactionHash"] = "0x" + "ee" * 32
        cases["transaction mismatch"] = wrong_hash
        boolean_index = valid_result()
        boolean_index["transactionIndex"] = True
        cases["boolean index"] = boolean_index
        unordered = valid_result()
        unordered["writes"].append(copy.deepcopy(unordered["writes"][0]))
        cases["unordered writes"] = unordered
        wrong_opcode = valid_result()
        wrong_opcode["writes"][0]["namespace"] = "transient"
        cases["opcode namespace"] = wrong_opcode
        missing_observation = valid_result()
        missing_observation["observedStorage"] = {}
        cases["complete observation omission"] = missing_observation
        bad_rollback = valid_result()
        bad_rollback["writes"][0]["frameReverted"] = True
        cases["rollback contradiction"] = bad_rollback
        short_old_value = valid_result()
        short_old_value["writes"][0]["oldValue"] = "0x0"
        cases["short old value"] = short_old_value
        malformed_prestate = valid_result()
        malformed_prestate["prestateDiff"]["pre"][ADDRESS]["unknown"] = 1
        cases["prestate account field"] = malformed_prestate

        for name, result in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(
                RPCError,
                "invalid trace response",
            ):
                await TraceRPCClient(
                    _Provider({"result": result})
                ).execute_slotscan_trace(1, TX_HASH)

    async def test_observation_and_prestate_limits_are_independently_enforced(self):
        observed = valid_result()
        observed["prestateDiff"] = {"pre": {}, "post": {}}
        observed["observedStorage"][ADDRESS][ZERO] = ZERO
        with self.assertRaisesRegex(TraceNotAvailableError, "observation limit"):
            await TraceRPCClient(
                _Provider({"result": observed}),
                Settings(MAX_PRESTATE_STORAGE_ENTRIES=1),
            ).execute_slotscan_trace(1, TX_HASH)

        prestate = valid_result()
        prestate["prestateDiff"]["pre"][ADDRESS]["storage"][ZERO] = ZERO
        prestate["observedStorage"] = {ADDRESS: {SLOT: ZERO}}
        with self.assertRaisesRegex(TraceNotAvailableError, "storage limit"):
            await TraceRPCClient(
                _Provider({"result": prestate}),
                Settings(MAX_PRESTATE_STORAGE_ENTRIES=2),
            ).execute_slotscan_trace(1, TX_HASH)

        accounts = valid_result()
        accounts["prestateDiff"] = {"pre": {}, "post": {}}
        accounts["observedStorage"]["0x" + "33" * 20] = {ZERO: ZERO}
        with self.assertRaisesRegex(TraceNotAvailableError, "observed-account"):
            await TraceRPCClient(
                _Provider({"result": accounts}),
                Settings(MAX_PRESTATE_ACCOUNTS=1),
            ).execute_slotscan_trace(1, TX_HASH)

    async def test_rpc_errors_never_expose_private_upstream_text(self):
        secret = "https://user:password@private-rpc.invalid/key?token=secret"
        for provider in (
            _Provider(exception=RuntimeError(secret)),
            _Provider({"error": {"code": -32603, "message": secret}}),
        ):
            with self.subTest(provider=provider), self.assertRaises(RPCError) as raised:
                await TraceRPCClient(provider).execute_slotscan_trace(1, TX_HASH)
            self.assertNotIn("password", str(raised.exception))
            self.assertNotIn("token", str(raised.exception))
            self.assertEqual(raised.exception.error, "upstream request failed")

        with self.assertRaises(RPCError) as raised:
            await TraceRPCClient(
                _Provider(exception=RuntimeError(secret))
            ).get_receipt(1, TX_HASH)
        self.assertNotIn("secret", str(raised.exception))

    async def test_unavailable_and_not_found_errors_have_stable_domain_types(self):
        with self.assertRaises(TraceNotAvailableError):
            await TraceRPCClient(
                _Provider({"error": {"code": -32601, "message": "private detail"}})
            ).execute_slotscan_trace(1, TX_HASH)

        with self.assertRaises(TransactionNotFoundError):
            await TraceRPCClient(
                _Provider({"error": {"code": -32000, "message": "transaction not found"}})
            ).execute_slotscan_trace(1, TX_HASH)


if __name__ == "__main__":
    unittest.main()
