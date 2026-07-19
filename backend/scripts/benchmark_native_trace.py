#!/usr/bin/env python3
"""Interleaved release benchmark for native SlotScan tracing.

The RPC URL is read only from SLOTSCAN_BENCH_RPC_URL and is never printed.
The old JavaScript tracer is imported from test support and is used solely as
the pre-cutover performance oracle.
"""

import argparse
import asyncio
import itertools
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import time
from urllib.request import Request, urlopen

from app.config import Settings
from tests.reth_js_oracle import TraceRPCClient as JsOracleTraceRPCClient


CONCURRENCY_LEVELS = (1, 2, 4)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


def parse_cpu_time(value: str) -> float:
    day_parts = value.strip().split("-")
    days = int(day_parts[0]) if len(day_parts) == 2 else 0
    clock = day_parts[-1].split(":")
    seconds = float(clock[-1])
    if len(clock) >= 2:
        seconds += int(clock[-2]) * 60
    if len(clock) == 3:
        seconds += int(clock[-3]) * 3_600
    return days * 86_400 + seconds


def process_sample(pid: int | None) -> tuple[float, int] | None:
    if pid is None:
        return None
    completed = subprocess.run(
        ["ps", "-o", "time=", "-o", "rss=", "-p", str(pid)],
        check=False,
        capture_output=True,
        text=True,
    )
    fields = completed.stdout.split()
    if completed.returncode != 0 or len(fields) != 2:
        raise RuntimeError(f"could not sample Reth process {pid}")
    return parse_cpu_time(fields[0]), int(fields[1]) * 1_024


class Rpc:
    def __init__(self, url: str):
        self.url = url
        self.request_ids = itertools.count(1)

    def call(self, method: str, params: list) -> tuple[object, int]:
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
        return envelope["result"], len(raw)


async def profiled_batch(pid: int | None, operation):
    before = process_sample(pid)
    max_rss = before[1] if before else 0
    running = True

    async def sample_memory():
        nonlocal max_rss
        while running:
            sample = await asyncio.to_thread(process_sample, pid)
            if sample:
                max_rss = max(max_rss, sample[1])
            await asyncio.sleep(0.05)

    sampler = asyncio.create_task(sample_memory()) if pid else None
    try:
        result = await operation
    finally:
        running = False
        if sampler:
            await sampler
    after = process_sample(pid)
    cpu_seconds = max(0.0, after[0] - before[0]) if before and after else None
    return result, cpu_seconds, max_rss or None


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("transaction_hash", nargs="+")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--reth-pid", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.rounds < 2:
        parser.error("--rounds must be at least 2")

    rpc_url = os.environ.get("SLOTSCAN_BENCH_RPC_URL")
    if not rpc_url:
        parser.error("SLOTSCAN_BENCH_RPC_URL is required")

    settings = Settings()
    oracle = JsOracleTraceRPCClient(object(), settings)
    tracer_source = oracle._compact_storage_tracer_source()
    limits = {
        "maxSteps": settings.max_trace_steps,
        "maxWrites": settings.max_sstore_ops,
        "maxSha3Operations": settings.max_trace_sha3_ops,
        "maxPreimageBytes": settings.max_trace_preimage_bytes,
        "maxObservedStorage": settings.max_prestate_storage_entries,
    }
    rpc = Rpc(rpc_url)

    async def baseline(transaction_hash: str) -> tuple[float, int]:
        started = time.perf_counter()
        prestate, compact = await asyncio.gather(
            asyncio.to_thread(
                rpc.call,
                "debug_traceTransaction",
                [
                    transaction_hash,
                    {
                        "tracer": "prestateTracer",
                        "tracerConfig": {"diffMode": True},
                    },
                ],
            ),
            asyncio.to_thread(
                rpc.call,
                "debug_traceTransaction",
                [transaction_hash, {"tracer": tracer_source}],
            ),
        )
        return time.perf_counter() - started, prestate[1] + compact[1]

    async def native(transaction_hash: str) -> tuple[float, int]:
        started = time.perf_counter()
        _, response_bytes = await asyncio.to_thread(
            rpc.call,
            "slotscan_traceTransaction",
            [transaction_hash, limits],
        )
        return time.perf_counter() - started, response_bytes

    report = {
        "rounds": args.rounds,
        "transactions": len(args.transaction_hash),
        "historical_concurrent_baseline_seconds": 1.205,
        "results": {},
    }
    for concurrency in CONCURRENCY_LEVELS:
        measurements = {
            "concurrent_js_plus_prestate": {
                "latency_seconds": [],
                "response_bytes": [],
                "cpu_seconds": [],
                "peak_rss_bytes": [],
            },
            "native_single_replay": {
                "latency_seconds": [],
                "response_bytes": [],
                "cpu_seconds": [],
                "peak_rss_bytes": [],
            },
        }
        modes = (
            ("concurrent_js_plus_prestate", baseline),
            ("native_single_replay", native),
        )
        for round_index in range(args.rounds):
            ordered_modes = modes if round_index % 2 == 0 else tuple(reversed(modes))
            hashes = [
                args.transaction_hash[
                    (round_index * concurrency + index) % len(args.transaction_hash)
                ]
                for index in range(concurrency)
            ]
            for name, operation in ordered_modes:
                batch, cpu_seconds, peak_rss = await profiled_batch(
                    args.reth_pid,
                    asyncio.gather(*(operation(tx_hash) for tx_hash in hashes)),
                )
                measurements[name]["latency_seconds"].extend(
                    latency for latency, _ in batch
                )
                measurements[name]["response_bytes"].extend(
                    size for _, size in batch
                )
                if cpu_seconds is not None:
                    measurements[name]["cpu_seconds"].append(
                        cpu_seconds / concurrency
                    )
                if peak_rss is not None:
                    measurements[name]["peak_rss_bytes"].append(peak_rss)

        summarized = {}
        for name, values in measurements.items():
            latencies = values["latency_seconds"]
            sizes = values["response_bytes"]
            summarized[name] = {
                "p50_latency_seconds": statistics.median(latencies),
                "p95_latency_seconds": percentile(latencies, 0.95),
                "median_response_bytes": statistics.median(sizes),
                "mean_cpu_seconds_per_trace": (
                    statistics.mean(values["cpu_seconds"])
                    if values["cpu_seconds"]
                    else None
                ),
                "peak_rss_bytes": (
                    max(values["peak_rss_bytes"])
                    if values["peak_rss_bytes"]
                    else None
                ),
            }
        baseline_result = summarized["concurrent_js_plus_prestate"]
        native_result = summarized["native_single_replay"]
        latency_reduction = 1 - (
            native_result["p50_latency_seconds"]
            / baseline_result["p50_latency_seconds"]
        )
        cpu_reduction = None
        if baseline_result["mean_cpu_seconds_per_trace"]:
            cpu_reduction = 1 - (
                native_result["mean_cpu_seconds_per_trace"]
                / baseline_result["mean_cpu_seconds_per_trace"]
            )
        summarized["release_gate"] = {
            "latency_reduction": latency_reduction,
            "cpu_reduction": cpu_reduction,
            "passes": latency_reduction >= 0.25
            or (cpu_reduction is not None and cpu_reduction >= 0.40),
        }
        report["results"][str(concurrency)] = summarized

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    asyncio.run(main())
