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
cargo build --locked --profile maxperf --features production
```

The resulting executable is `target/maxperf/reth-slotscan`. Production builds
set `SLOTSCAN_BUILD_COMMIT` to the source commit and use Reth's public version
metadata hook to report the SlotScan release, SlotScan commit, embedded Reth
release and commit, build profile, and enabled features.

Releases are built natively on GitHub's Ubuntu runner without Docker and
package this executable as a single top-level file named `reth`. The tag and
artifact use the downstream version derived from the embedded Reth release, for
example:

```text
reth-v2.3.0-slotscan.1
reth-v2.3.0-slotscan.1-x86_64-unknown-linux-gnu.tar.gz
```

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
`src/main.rs`. The manually dispatched `Build SlotScan Reth` workflow accepts
one stable upstream tag such as `v2.4.0`. It then:

1. Runs `scripts/update-reth.sh` to resolve the official tag to its exact
   commit, update all Reth pins and Rust metadata, and regenerate `Cargo.lock`.
2. Commits that deterministic source update only after validating its shape.
3. Runs `scripts/build-reth.sh`, which checks, tests, lints, builds with the
   `maxperf` profile, verifies embedded identity, and smoke-tests both ordinary
   Reth RPC and `slotscan_traceTransaction`.
4. Pushes the source commit and immutable release tag, then publishes the
   drop-in `reth` archive. An existing release is a successful no-op.

These scripts are the supported release interface. `server-setup update check`
can detect that upstream Reth is newer and offer to dispatch this workflow; it
does not compile on the node or deploy automatically. Once the release exists,
the normal `server-setup update apply` path installs it into the existing
binary location and service.

Before adopting a new upstream release, review changes around
`spawn_trace_transaction_in_block_with_inspector`, REVM inspector/journal
hooks, and `GethTraceBuilder::geth_prestate_traces`, then re-run the manual
interleaved performance benchmark.

Do not support multiple Reth releases in one build. If one of those public
seams changes, adapt `src/main.rs` or `src/reth_adapter.rs`. If a required seam
disappears, propose a small upstream extension point before considering copied
replay internals or a maintained source fork.
