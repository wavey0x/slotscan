# Backend analysis architecture

The backend keeps raw transaction evidence separate from contract-specific interpretation.

```text
TransactionTraceExtractor
  receipt + prestate diff + struct logs
              |
              v
StorageJournal
  ordered SSTORE/TSTORE events + frame rollback + authoritative state
              |
              v
TransactionAnalysisService
  LayoutIndex -> SlotPathResolver -> bound ValueDecoder
              |
              v
API presenters
  state summary + complete write history + evidence capabilities
```

## Evidence semantics

- Every observed write is retained, including no-ops, restored writes, and reverted writes.
- `effect` is one of `applied`, `noop`, or `reverted`.
- Slot-level `before` and `after` come from the reconciled journal, not the first and last displayed event.
- Unknown pre-write values remain `null`; they are never synthesized as zero.
- `persistent` and `transient` slot namespaces are distinct.
- Capability flags state whether execution order, frame outcomes, per-write old values, and final state are complete.
- Event truncation never changes the authoritative state summary.

## Persistence

- One local SQLite database stores all reproducible caches. Connections use WAL
  mode, `synchronous=NORMAL`, foreign keys, and a five-second busy timeout.
- Trace artifacts are transaction-scoped and keyed by `(chain_id, tx_hash)`.
- Contract projections are derived and are not duplicated in the trace cache.
- Historical address/proxy/layout associations are keyed by block.
- Raw compiler input/output, AST, storage/transient layouts, settings, exact build identifier, and source hashes are retained by fingerprint.
- Trace artifacts and parsed layouts use only the current application shape.
  Incompatible changes invalidate those reproducible caches instead of adding
  payload versions, dual readers, or retained legacy tables.

## Development compatibility policy

SlotScan is pre-launch. Refactors use hard cutovers for application-owned APIs,
routes, caches, and internal names. Version-aware code is reserved for real
input semantics such as compiler eras, EVM behavior, historical chain state,
and external provider protocols.

## Compiler isolation

Compiler processes run with bounded concurrency, input-size and wall-clock limits, and child-process CPU/memory limits where supported. Request-time compiler installation is disabled by default and the installed-version cache is capped when installation is explicitly enabled.

## Verification

```bash
cd backend
venv/bin/python -m unittest discover -s tests -v
ruff check app tests
venv/bin/alembic check
```
