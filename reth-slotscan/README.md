# reth-slotscan

`reth-slotscan` is SlotScan's downstream Reth full-node binary. It compiles the
upstream Reth crates at the pinned commit and adds one in-process
`slotscan_traceTransaction` RPC method backed by a native REVM inspector.

It is not a sidecar and does not maintain a modified Reth source tree. Run this
binary in place of the stock `reth` executable, using the same compatible data
directory and normal Reth CLI flags. Never run stock Reth and `reth-slotscan`
against the same data directory at the same time.

The custom binary is possible without editing an upstream checkout because
Reth exposes its node builder, RPC registry, trace semaphore, canonical
transaction replay, and REVM inspector hooks as public Rust APIs. This crate
links those upstream crates at one exact commit and adds a module at the
supported extension seam. `src/reth_adapter.rs` is the only version-sensitive
bridge.

## Performance model

The former backend path made two traces. Each independently replayed all
earlier transactions in the block, and each executed the target transaction;
one target execution also paid per-opcode JavaScript callback and serialization
cost.

The native path performs one prefix replay and one target execution. During
that target execution the Rust inspector records every ordered `SSTORE`,
`TSTORE`, and relevant `KECCAK256`, while Reth's normal trace builder produces
the prestate diff from the same result. This removes one prefix replay, one
target execution, JavaScript dispatch, and one RPC round trip without dropping
intermediary, no-op, restored, transient, or reverted writes.

## Build

The declared Rust toolchain is installed automatically by `rustup`:

```sh
cargo build --release
```

The resulting executable is `target/release/reth-slotscan`.

## RPC

```text
slotscan_traceTransaction(transaction_hash, limits)
```

The required `limits` object uses camel-case fields:

```json
{
  "maxSteps": 5000000,
  "maxWrites": 10000,
  "maxSha3Operations": 20000,
  "maxPreimageBytes": 5242880,
  "maxObservedStorage": 100000
}
```

These values cannot exceed the binary's hard collection ceilings. Collection
overflow never interrupts EVM execution: detailed evidence is discarded,
`degradedReason` becomes `trace_limit`, and the authoritative prestate diff is
still returned.

The method obeys Reth's standard `--rpc.max-tracing-requests` semaphore. Keep
the ordinary Reth HTTP namespaces enabled as usual; the binary only adds the
`slotscan` namespace.

## Validation

```sh
cargo check
cargo test
cargo clippy --all-targets -- -D warnings
```

The Rust suite executes synthetic bytecode through REVM for ordered old values,
delegate/callcode ownership, nested and root rollback, create/create2,
transient storage, EIP-7702 attribution, SHA3 capture, and collection limits.
The gated backend conformance suite keeps the old JS tracer and prestate tracer
under `backend/tests/` only as a differential oracle:

```sh
cd ../backend
RUN_RETH_TRACER_CONFORMANCE=1 venv/bin/python \
  -m unittest tests.test_reth_tracer_conformance -v
```

For the manual release gate, run interleaved concurrency 1/2/4 measurements
against the custom node. Supplying the Reth PID adds CPU-time and peak-RSS
sampling; the RPC URL stays out of output:

```sh
cd ../backend
SLOTSCAN_BENCH_RPC_URL=http://127.0.0.1:8545 \
  venv/bin/python -m scripts.benchmark_native_trace \
  --reth-pid 12345 --rounds 10 0xTRANSACTION_HASH
```

Adopt only when the semantic suite is exact and the report shows either at
least 25% lower p50 trace latency than the concurrently overlapped legacy pair
or at least 40% lower Reth CPU per trace. Timing thresholds intentionally do not
run in CI.

## Reth upgrades

Reth-facing calls are isolated in `src/reth_adapter.rs` and node wiring in
`src/main.rs`. To upgrade:

1. Update the identical pinned Reth revisions in `Cargo.toml`.
2. Update `rust-toolchain.toml` to Reth's declared minimum.
3. Regenerate and commit `Cargo.lock`.
4. Run `cargo check`, `cargo test`, Clippy, the backend native differential
   suite, and a smoke check for both `eth_chainId` and
   `slotscan_traceTransaction`.
5. Review upstream changes only around
   `spawn_trace_transaction_in_block_with_inspector`, REVM inspector/journal
   hooks, and `GethTraceBuilder::geth_prestate_traces`.
6. Re-run the manual interleaved performance benchmark before deployment.

Do not support multiple Reth releases in one build. If one of those public
seams changes, adapt `src/main.rs` or `src/reth_adapter.rs`. If a required seam
disappears, propose a small upstream extension point before considering copied
replay internals or a maintained source fork.
