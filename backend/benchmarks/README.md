# Reth tracer benchmark

This benchmark compares the transaction-evidence stage of the legacy SlotScan
backend with the native SlotScan Reth RPC on the same node and pinned mainnet
transactions.

- Legacy: fetch the receipt and prestate diff concurrently, then run the
  JavaScript compact tracer. This is three RPC calls and two EVM replays.
- Native: fetch the receipt and call `slotscan_traceTransaction` concurrently.
  This is two RPC calls and one EVM replay.

Before timing, the runner requires exact parity for the prestate diff, write
identity and ordering, SHA3 evidence, observed storage, step count, and
transaction identity. Intermediate `oldValue` fields are intentionally excluded
from parity because the legacy tracer did not provide them.

## Quick run

Run from `backend/` against a SlotScan Reth endpoint:

```bash
SLOTSCAN_BENCH_RPC_URL=http://127.0.0.1:8545 \
  venv/bin/python scripts/benchmark_native_trace.py \
  --rounds 7 \
  --output /tmp/slotscan-benchmark.json \
  --markdown-output /tmp/slotscan-benchmark.md
```

The default corpus contains:

| Case | Purpose |
|---|---|
| `erc20_transfer` | Small transaction and fixed-overhead behavior |
| `reverted_writes` | Large nested execution with persistent, transient, and reverted writes |
| `proxy_voting` | Large proxy/delegatecall execution with mapping and packed-slot evidence |

Use `--case NAME` to run a subset. For example, a fast smoke run is:

```bash
SLOTSCAN_BENCH_RPC_URL=http://127.0.0.1:8545 \
  venv/bin/python scripts/benchmark_native_trace.py \
  --case erc20_transfer --rounds 2 --warmups 0
```

## Publication run

For blog-quality numbers, use an otherwise idle node and collect enough
interleaved rounds:

```bash
SLOTSCAN_BENCH_RPC_URL=http://127.0.0.1:8545 \
  venv/bin/python scripts/benchmark_native_trace.py \
  --rounds 15 \
  --warmups 2 \
  --output /tmp/slotscan-benchmark.json \
  --markdown-output /tmp/slotscan-benchmark.md
```

Preserve the JSON report: it contains raw samples, the node-reported client
version, limits, corpus facts, and methodology. The Markdown table is suitable
for drafting a post.

Report these metrics:

- p50 and p95 evidence-extraction latency;
- p50 speedup and latency reduction;
- median response-size change;
- the architectural reduction from two EVM replays to one.

Do not turn wall-clock results into CI thresholds. For public claims, repeat the
complete run at least three times and use the median run.
