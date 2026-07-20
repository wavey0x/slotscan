import time
import unittest

from scripts.benchmark_native_trace import (
    DEFAULT_MANIFEST,
    LEGACY_MODE,
    NATIVE_MODE,
    RpcResponse,
    compare_modes,
    load_cases,
    render_markdown,
    run_legacy,
    run_native,
    summarize_mode,
)


class BenchmarkHelpersTests(unittest.TestCase):
    def test_default_manifest_is_small_and_semantically_distinct(self):
        chain_id, cases = load_cases(DEFAULT_MANIFEST)

        self.assertEqual(chain_id, 1)
        self.assertEqual(
            [case.name for case in cases],
            [
                "erc20_transfer",
                "reverted_writes",
                "proxy_voting",
                "high_fanout_delegation",
            ],
        )
        self.assertEqual(len({case.transaction_hash for case in cases}), 4)
        self.assertTrue(all(case.expected["step_count"] > 0 for case in cases))

    def test_manifest_case_filter_rejects_unknown_names(self):
        _chain_id, cases = load_cases(
            DEFAULT_MANIFEST,
            {"proxy_voting"},
        )
        self.assertEqual([case.name for case in cases], ["proxy_voting"])

        with self.assertRaisesRegex(ValueError, "unknown benchmark case"):
            load_cases(DEFAULT_MANIFEST, {"missing"})

    def test_summary_and_comparison_use_explicit_units(self):
        legacy = summarize_mode(
            [0.2, 0.3, 0.4],
            [1_000, 1_100, 1_200],
        )
        native = summarize_mode(
            [0.1, 0.15, 0.2],
            [400, 500, 600],
        )
        comparison = compare_modes(legacy, native)

        self.assertEqual(legacy["p50_latency_ms"], 300)
        self.assertEqual(legacy["p95_latency_ms"], 400)
        self.assertEqual(native["median_response_bytes"], 500)
        self.assertEqual(comparison["p50_speedup_x"], 2)
        self.assertAlmostEqual(comparison["p50_latency_reduction"], 0.5)
        self.assertAlmostEqual(
            comparison["response_bytes_change"],
            (500 / 1_100) - 1,
        )
        self.assertEqual(comparison["evm_replays"], {"legacy": 2, "native": 1})

    def test_markdown_contains_blog_metrics_and_methodology(self):
        result = {
            LEGACY_MODE: {
                "p50_latency_ms": 200,
                "median_response_bytes": 1_000,
            },
            NATIVE_MODE: {
                "p50_latency_ms": 100,
                "median_response_bytes": 500,
            },
            "comparison": {
                "p50_speedup_x": 2,
                "p50_latency_reduction": 0.5,
                "response_bytes_change": -0.5,
            },
        }
        report = {
            "generated_at": "2026-07-20T00:00:00+00:00",
            "node": {"client_version": "reth/test"},
            "configuration": {"rounds": 8, "warmups": 1},
            "cases": [
                {
                    "name": "example",
                    "results": result,
                }
            ],
        }

        markdown = render_markdown(report)

        self.assertIn("| example | 200.0 ms | 100.0 ms | 2.00x", markdown)
        self.assertIn("two EVM replays", markdown)
        self.assertIn("execution order alternates", markdown)
        self.assertIn("exact parity checks", markdown)


class FakeRpc:
    def __init__(self):
        self.calls = []
        self.prestate_finished = False

    def call(self, method, params):
        tracer = params[1].get("tracer") if method == "debug_traceTransaction" else None
        self.calls.append((method, tracer))
        if method == "eth_getTransactionReceipt":
            time.sleep(0.005)
            result = {"blockHash": "0x" + "11" * 32}
        elif tracer == "prestateTracer":
            time.sleep(0.02)
            self.prestate_finished = True
            result = {"pre": {}, "post": {}}
        elif method == "debug_traceTransaction":
            if not self.prestate_finished:
                raise AssertionError("compact tracer started before prestate completed")
            result = {"fatal": None}
        else:
            result = {"transactionHash": params[0]}
        return RpcResponse(result=result, response_bytes=10)


class BenchmarkSequenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_reproduces_parallel_receipt_then_sequential_compact(self):
        rpc = FakeRpc()

        extraction = await run_legacy(rpc, "0x" + "22" * 32, "{}")

        self.assertEqual(extraction.measurement.response_bytes, 30)
        self.assertEqual(len(rpc.calls), 3)
        self.assertCountEqual(
            rpc.calls[:2],
            [
                ("eth_getTransactionReceipt", None),
                ("debug_traceTransaction", "prestateTracer"),
            ],
        )
        self.assertEqual(
            rpc.calls[2],
            ("debug_traceTransaction", "{}"),
        )

    async def test_native_uses_one_trace_and_one_receipt(self):
        rpc = FakeRpc()

        extraction = await run_native(
            rpc,
            "0x" + "22" * 32,
            {"maxSteps": 1},
        )

        self.assertEqual(extraction.measurement.response_bytes, 20)
        self.assertCountEqual(
            rpc.calls,
            [
                ("eth_getTransactionReceipt", None),
                ("slotscan_traceTransaction", None),
            ],
        )


if __name__ == "__main__":
    unittest.main()
