#!/usr/bin/env python3
"""Compare SlotScan's legacy two-replay tracer with its native single replay.

The benchmark reproduces the transaction-evidence RPC stage used by each
backend implementation:

* Legacy: receipt + prestate diff in parallel, then the JavaScript tracer.
* Native: receipt + ``slotscan_traceTransaction`` in parallel.

The RPC URL is read only from ``SLOTSCAN_BENCH_RPC_URL`` and is never printed.
Correctness is checked before any timed samples are accepted.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import itertools
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Any
from urllib.request import Request, urlopen


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings  # noqa: E402
from app.services.tracer.extractor import TransactionTraceExtractor  # noqa: E402
from app.services.tracer.rpc_client import (  # noqa: E402
    TraceRPCClient as NativeTraceRPCClient,
)
from tests.reth_js_oracle import (  # noqa: E402
    TraceRPCClient as LegacyTraceRPCClient,
)


DEFAULT_MANIFEST = BACKEND_ROOT / "benchmarks" / "reth_trace_cases.json"
HASH_PATTERN = re.compile(r"^0x[0-9a-f]{64}$")
WRITE_IDENTITY_FIELDS = (
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
LEGACY_MODE = "legacy_two_replay"
NATIVE_MODE = "native_single_replay"


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    transaction_hash: str
    description: str
    semantic_tags: tuple[str, ...]
    expected: dict[str, Any]


@dataclass(frozen=True)
class RpcResponse:
    result: Any
    response_bytes: int


@dataclass(frozen=True)
class Measurement:
    latency_seconds: float
    response_bytes: int


@dataclass(frozen=True)
class Extraction:
    measurement: Measurement
    receipt: dict[str, Any]
    prestate_diff: dict[str, Any] | None = None
    compact_trace: Any = None
    native_trace: Any = None


class Rpc:
    def __init__(self, url: str):
        self.url = url
        self.request_ids = itertools.count(1)

    def call(self, method: str, params: list[Any]) -> RpcResponse:
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": next(self.request_ids),
                "method": method,
                "params": params,
            },
            separators=(",", ":"),
        ).encode()
        request = Request(
            self.url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=300) as response:
            raw = response.read()
        envelope = json.loads(raw)
        if "error" in envelope:
            error = envelope["error"]
            code = error.get("code") if isinstance(error, dict) else None
            raise RuntimeError(f"{method} returned JSON-RPC error code {code}")
        if "result" not in envelope:
            raise RuntimeError(f"{method} returned no JSON-RPC result")
        return RpcResponse(envelope["result"], len(raw))


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


def load_cases(
    manifest_path: Path,
    selected_names: set[str] | None = None,
) -> tuple[int, list[BenchmarkCase]]:
    manifest = json.loads(manifest_path.read_text())
    chain_id = manifest.get("chain_id")
    raw_cases = manifest.get("cases")
    if not isinstance(chain_id, int) or chain_id < 1:
        raise ValueError("benchmark manifest has an invalid chain_id")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("benchmark manifest must contain cases")

    cases = []
    seen_names = set()
    seen_hashes = set()
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError("benchmark cases must be objects")
        name = raw.get("name")
        transaction_hash = raw.get("transaction_hash")
        description = raw.get("description")
        semantic_tags = raw.get("semantic_tags")
        expected = raw.get("expected")
        if not isinstance(name, str) or not name:
            raise ValueError("benchmark case name is required")
        if name in seen_names:
            raise ValueError(f"duplicate benchmark case name: {name}")
        if (
            not isinstance(transaction_hash, str)
            or not HASH_PATTERN.fullmatch(transaction_hash)
        ):
            raise ValueError(f"{name} has an invalid transaction hash")
        if transaction_hash in seen_hashes:
            raise ValueError(f"duplicate benchmark transaction: {transaction_hash}")
        if not isinstance(description, str) or not description:
            raise ValueError(f"{name} has no description")
        if (
            not isinstance(semantic_tags, list)
            or not semantic_tags
            or not all(isinstance(tag, str) and tag for tag in semantic_tags)
        ):
            raise ValueError(f"{name} has invalid semantic_tags")
        if not isinstance(expected, dict):
            raise ValueError(f"{name} has invalid expected facts")
        seen_names.add(name)
        seen_hashes.add(transaction_hash)
        if selected_names is None or name in selected_names:
            cases.append(
                BenchmarkCase(
                    name=name,
                    transaction_hash=transaction_hash,
                    description=description,
                    semantic_tags=tuple(semantic_tags),
                    expected=expected,
                )
            )

    if selected_names:
        unknown = selected_names - seen_names
        if unknown:
            raise ValueError(
                "unknown benchmark case(s): " + ", ".join(sorted(unknown))
            )
    if not cases:
        raise ValueError("no benchmark cases selected")
    return chain_id, cases


async def rpc_call(rpc: Rpc, method: str, params: list[Any]) -> RpcResponse:
    return await asyncio.to_thread(rpc.call, method, params)


async def run_legacy(
    rpc: Rpc,
    transaction_hash: str,
    tracer_source: str,
) -> Extraction:
    """Reproduce the pre-cutover backend's exact RPC ordering."""
    started = time.perf_counter()
    receipt, prestate = await asyncio.gather(
        rpc_call(rpc, "eth_getTransactionReceipt", [transaction_hash]),
        rpc_call(
            rpc,
            "debug_traceTransaction",
            [
                transaction_hash,
                {
                    "tracer": "prestateTracer",
                    "tracerConfig": {"diffMode": True},
                },
            ],
        ),
    )
    compact = await rpc_call(
        rpc,
        "debug_traceTransaction",
        [transaction_hash, {"tracer": tracer_source}],
    )
    elapsed = time.perf_counter() - started
    if not isinstance(receipt.result, dict):
        raise RuntimeError(f"receipt not found for {transaction_hash}")
    return Extraction(
        measurement=Measurement(
            latency_seconds=elapsed,
            response_bytes=(
                receipt.response_bytes
                + prestate.response_bytes
                + compact.response_bytes
            ),
        ),
        receipt=receipt.result,
        prestate_diff=prestate.result,
        compact_trace=compact.result,
    )


async def run_native(
    rpc: Rpc,
    transaction_hash: str,
    limits: dict[str, int],
) -> Extraction:
    """Reproduce the native backend's exact RPC ordering."""
    started = time.perf_counter()
    receipt, native = await asyncio.gather(
        rpc_call(rpc, "eth_getTransactionReceipt", [transaction_hash]),
        rpc_call(
            rpc,
            "slotscan_traceTransaction",
            [transaction_hash, limits],
        ),
    )
    elapsed = time.perf_counter() - started
    if not isinstance(receipt.result, dict):
        raise RuntimeError(f"receipt not found for {transaction_hash}")
    return Extraction(
        measurement=Measurement(
            latency_seconds=elapsed,
            response_bytes=receipt.response_bytes + native.response_bytes,
        ),
        receipt=receipt.result,
        native_trace=native.result,
    )


def write_identity(writes: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        tuple(write[field] for field in WRITE_IDENTITY_FIELDS)
        for write in writes
    ]


def quantity(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not a quantity")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 16)
    raise ValueError("invalid quantity")


def validate_expected(
    case: BenchmarkCase,
    native: Any,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    persistent = [
        write for write in native.writes if write["namespace"] == "persistent"
    ]
    reverted = [write for write in persistent if write["frame_reverted"]]
    old_values = [write for write in persistent if write["old_value"] is not None]
    facts = {
        "block_hash": native.block_hash,
        "block_number": quantity(receipt["blockNumber"]),
        "gas_used": quantity(receipt["gasUsed"]),
        "step_count": native.evm_step_count,
        "writes": len(native.writes),
        "persistent_writes": len(persistent),
        "reverted_writes": len(reverted),
        "sha3_operations": len(native.sha3_operations),
        "persistent_old_values_present": len(old_values),
    }
    for key, expected in case.expected.items():
        if facts.get(key) != expected:
            raise RuntimeError(
                f"{case.name} expected {key}={expected!r}, "
                f"received {facts.get(key)!r}"
            )
    return facts


def validate_parity(
    case: BenchmarkCase,
    legacy_extraction: Extraction,
    native_extraction: Extraction,
    legacy_client: LegacyTraceRPCClient,
    native_client: NativeTraceRPCClient,
) -> dict[str, Any]:
    if legacy_extraction.receipt != native_extraction.receipt:
        raise RuntimeError(f"{case.name} receipt changed between tracer modes")
    if legacy_extraction.prestate_diff is None:
        raise RuntimeError(f"{case.name} legacy prestate is missing")

    legacy = legacy_client._decode_compact_trace_result(
        legacy_extraction.compact_trace
    )
    native = native_client._decode_slotscan_trace_result(
        native_extraction.native_trace,
        case.transaction_hash,
    )
    prestate = deepcopy(legacy_extraction.prestate_diff)
    TransactionTraceExtractor._normalize_diff(prestate)

    comparisons = {
        "prestate_diff": native.prestate_diff == prestate,
        "write_identity": write_identity(native.writes)
        == write_identity(legacy.writes),
        "sha3_operations": native.sha3_operations == legacy.sha3_operations,
        "observed_storage": native.observed_storage == legacy.observed_storage,
        "observation_completeness": (
            native.observed_storage_complete
            == legacy.observed_storage_complete
        ),
        "step_count": native.evm_step_count == legacy.evm_step_count,
        "degradation": native.degraded_reason == legacy.degraded_reason,
    }
    failed = [name for name, matches in comparisons.items() if not matches]
    if failed:
        raise RuntimeError(
            f"{case.name} semantic parity failed: {', '.join(failed)}"
        )

    receipt = native_extraction.receipt
    if native.block_hash != str(receipt["blockHash"]).lower():
        raise RuntimeError(f"{case.name} native block identity is incorrect")
    if native.transaction_index != quantity(receipt["transactionIndex"]):
        raise RuntimeError(f"{case.name} native transaction index is incorrect")
    if native.root_succeeded != (quantity(receipt["status"]) == 1):
        raise RuntimeError(f"{case.name} native status is incorrect")

    return {
        "semantic_parity": True,
        "compared_fields": sorted(comparisons),
        "facts": validate_expected(case, native, receipt),
    }


def summarize_mode(
    latencies: list[float],
    sizes: list[int],
) -> dict[str, Any]:
    return {
        "samples": len(latencies),
        "p50_latency_ms": statistics.median(latencies) * 1_000,
        "p95_latency_ms": percentile(latencies, 0.95) * 1_000,
        "median_response_bytes": statistics.median(sizes),
        "raw": {
            "latency_ms": [value * 1_000 for value in latencies],
            "response_bytes": sizes,
        },
    }


def reduction(before: float, after: float) -> float:
    return 1 - (after / before)


def compare_modes(
    legacy: dict[str, Any],
    native: dict[str, Any],
) -> dict[str, Any]:
    return {
        "p50_speedup_x": (
            legacy["p50_latency_ms"] / native["p50_latency_ms"]
        ),
        "p50_latency_reduction": reduction(
            legacy["p50_latency_ms"],
            native["p50_latency_ms"],
        ),
        "response_bytes_change": (
            native["median_response_bytes"]
            / legacy["median_response_bytes"]
        ) - 1,
        "backend_rpc_calls": {"legacy": 3, "native": 2},
        "evm_replays": {"legacy": 2, "native": 1},
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# SlotScan native tracer benchmark",
        "",
        f"Generated: {report['generated_at']}",
        "",
        (
            "Scope: uncached transaction-evidence extraction. Legacy performs "
            "two EVM replays; native performs one. Both paths also fetch the "
            "same receipt."
        ),
        "",
        "| Case | Legacy p50 | Native p50 | Speedup | Latency reduction | "
        "Response size change |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for case in report["cases"]:
        result = case["results"]
        legacy = result[LEGACY_MODE]
        native = result[NATIVE_MODE]
        comparison = result["comparison"]
        lines.append(
            "| {name} | {legacy:.1f} ms | {native:.1f} ms | {speedup:.2f}x "
            "| {latency:.1%} | {response:+.1%} |".format(
                name=case["name"],
                legacy=legacy["p50_latency_ms"],
                native=native["p50_latency_ms"],
                speedup=comparison["p50_speedup_x"],
                latency=comparison["p50_latency_reduction"],
                response=comparison["response_bytes_change"],
            )
        )
    lines.extend(
        [
            "",
            "Every case passed exact parity checks for prestate diff, write "
            "identity and ordering, SHA3 evidence, observed storage, step count, "
            "and transaction identity.",
            "",
            (
                f"Node: `{report['node']['client_version']}`; rounds: "
                f"{report['configuration']['rounds']}; warmups: "
                f"{report['configuration']['warmups']}."
            ),
            "",
        ]
    )
    return "\n".join(lines)


async def benchmark(args: argparse.Namespace) -> dict[str, Any]:
    rpc_url = os.environ.get("SLOTSCAN_BENCH_RPC_URL")
    if not rpc_url:
        raise ValueError("SLOTSCAN_BENCH_RPC_URL is required")

    selected_names = set(args.case) if args.case else None
    chain_id, cases = load_cases(args.manifest, selected_names)
    settings = Settings(_env_file=None)
    legacy_client = LegacyTraceRPCClient(object(), settings)
    native_client = NativeTraceRPCClient(object(), settings)
    tracer_source = legacy_client._compact_storage_tracer_source()
    limits = {
        "maxSteps": settings.max_trace_steps,
        "maxWrites": settings.max_sstore_ops,
        "maxSha3Operations": settings.max_trace_sha3_ops,
        "maxPreimageBytes": settings.max_trace_preimage_bytes,
        "maxObservedStorage": settings.max_prestate_storage_entries,
    }
    rpc = Rpc(rpc_url)
    client_version = (await rpc_call(rpc, "web3_clientVersion", [])).result
    actual_chain_id = quantity((await rpc_call(rpc, "eth_chainId", [])).result)
    if actual_chain_id != chain_id:
        raise RuntimeError(
            f"benchmark manifest expects chain {chain_id}, node is chain "
            f"{actual_chain_id}"
        )

    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "uncached_transaction_evidence_rpc_stage",
        "node": {
            "client_version": client_version,
            "chain_id": actual_chain_id,
        },
        "configuration": {
            "manifest": args.manifest.name,
            "rounds": args.rounds,
            "warmups": args.warmups,
            "interleaved": True,
            "limits": limits,
        },
        "methodology": {
            LEGACY_MODE: {
                "backend_rpc_calls": 3,
                "evm_replays": 2,
                "sequence": [
                    "eth_getTransactionReceipt || prestateTracer(diffMode)",
                    "legacy JavaScript compact tracer",
                ],
            },
            NATIVE_MODE: {
                "backend_rpc_calls": 2,
                "evm_replays": 1,
                "sequence": [
                    "eth_getTransactionReceipt || slotscan_traceTransaction",
                ],
            },
        },
        "cases": [],
    }

    operations = {
        LEGACY_MODE: lambda case: run_legacy(
            rpc,
            case.transaction_hash,
            tracer_source,
        ),
        NATIVE_MODE: lambda case: run_native(
            rpc,
            case.transaction_hash,
            limits,
        ),
    }
    modes = (LEGACY_MODE, NATIVE_MODE)

    for case_index, case in enumerate(cases):
        legacy_preflight = await operations[LEGACY_MODE](case)
        native_preflight = await operations[NATIVE_MODE](case)
        correctness = validate_parity(
            case,
            legacy_preflight,
            native_preflight,
            legacy_client,
            native_client,
        )

        for warmup_index in range(args.warmups):
            warmup_order = (
                modes
                if (case_index + warmup_index) % 2 == 0
                else tuple(reversed(modes))
            )
            for mode in warmup_order:
                await operations[mode](case)

        case_report = {
            "name": case.name,
            "transaction_hash": case.transaction_hash,
            "description": case.description,
            "semantic_tags": list(case.semantic_tags),
            "correctness": correctness,
            "results": None,
        }
        measurements = {
            mode: {"latencies": [], "sizes": []}
            for mode in modes
        }
        for round_index in range(args.rounds):
            ordered_modes = (
                modes
                if (case_index + round_index) % 2 == 0
                else tuple(reversed(modes))
            )
            for mode in ordered_modes:
                extraction = await operations[mode](case)
                measurements[mode]["latencies"].append(
                    extraction.measurement.latency_seconds
                )
                measurements[mode]["sizes"].append(
                    extraction.measurement.response_bytes
                )

        summarized = {
            mode: summarize_mode(values["latencies"], values["sizes"])
            for mode, values in measurements.items()
        }
        summarized["comparison"] = compare_modes(
            summarized[LEGACY_MODE],
            summarized[NATIVE_MODE],
        )
        case_report["results"] = summarized
        report["cases"].append(case_report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark legacy two-replay tracing against native single-replay "
            "SlotScan tracing."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="pinned transaction corpus (default: backend/benchmarks/reth_trace_cases.json)",
    )
    parser.add_argument(
        "--case",
        action="append",
        help="run one named manifest case; repeat to select more than one",
    )
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument(
        "--output",
        type=Path,
        help="write the complete JSON report, including raw samples",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        help="write a blog-ready Markdown summary table",
    )
    args = parser.parse_args()
    if args.rounds < 2:
        parser.error("--rounds must be at least 2")
    if args.warmups < 0:
        parser.error("--warmups must not be negative")
    return args


async def main() -> None:
    args = parse_args()
    try:
        report = await benchmark(args)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"benchmark failed: {exc}") from None

    rendered_json = json.dumps(report, indent=2, sort_keys=True) + "\n"
    rendered_markdown = render_markdown(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered_json)
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(rendered_markdown)
    print(rendered_markdown)


if __name__ == "__main__":
    asyncio.run(main())
