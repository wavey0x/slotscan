# StorageScan Service Requirements Index

This directory contains detailed requirements for each service/module in the StorageScan application. Scope is lean MVP: single FastAPI service, Postgres as the only cache/persistence layer (JSONB blobs), no Redis, no background workers, and on-demand computation per request.

## Service Checklist

| # | Service | File | Status | Description |
|---|---------|------|--------|-------------|
| 1 | Contract Resolver | `01-contract-resolver.md` | ✅ Complete | Proxy detection (EIP-1967/UUPS), verification lookup, source fetching |
| 2 | Layout Parser | `02-layout-parser.md` | ✅ Complete | Parse solc output + Sourcify layouts, normalize to internal schema |
| 3 | Storage Reader | `03-storage-reader.md` | ✅ Complete | Read slots at block, compute complex type slots |
| 4 | Transaction Tracer | `04-transaction-tracer.md` | ✅ Complete | Trace txs with prestateTracer, mapping key inference |
| 5 | Type Decoder | `05-type-decoder.md` | ✅ Complete | Decode raw bytes32 to typed values, heuristic decoding |
| 6 | Database Layer | `06-database-layer.md` | ✅ Complete | Postgres persistence and cache (JSONB) |
| 7 | API Layer | `07-api-layer.md` | ✅ Complete | FastAPI routes, request/response handling |
| 8 | Frontend | `08-frontend.md` | ✅ Complete | Next.js UI application |

## Implementation Notes

### Key Implementation Decisions

1. **Sourcify Layout Priority**: Layouts are now parsed directly from Sourcify when available, avoiding recompilation. Solc fallback only used for Etherscan-only contracts.

2. **Mapping Key Inference**: The tracer collects candidate addresses from transaction receipts (from/to, log addresses, log topics/data) and trace state to match mapping slots via `keccak256(key || base_slot)`.

3. **No Weak Mapping Inference**: Unmatched slots are NOT speculatively assigned to mappings. If a slot cannot be matched via key computation, it remains unattributed with `variable=None`.

4. **Heuristic Decoding**: When no layout is available, the decoder uses heuristics (address detection, boolean detection, string detection) to present values meaningfully.

5. **Graceful Degradation**: All services handle failures gracefully - missing layouts show hex-only values, trace unavailability is communicated to the UI.

## Dependency Graph

```
                    ┌─────────────────┐
                    │    Frontend     │
                    │   (Next.js)     │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   API Layer     │
                    │   (FastAPI)     │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│   Contract    │   │    Storage    │   │  Transaction  │
│   Resolver    │   │    Reader     │   │    Tracer     │
└───────┬───────┘   └───────┬───────┘   └───────┬───────┘
        │                   │                   │
        ▼                   └─────────┬─────────┘
┌───────────────┐                     │
│    Layout     │                     ▼
│    Parser     │           ┌───────────────┐
└───────────────┘           │     Type      │
                            │    Decoder    │
                            └───────────────┘
        │                           │
        └───────────────┬───────────┘
                        │
                        ▼
               ┌───────────────┐
               │   Database    │
               │    Layer      │
               └───────────────┘
```

## Build Order (Recommended)

1. **Database Layer** - Foundation for all persistence
2. **Type Decoder** - No dependencies, pure functions
3. **Contract Resolver** - Depends on Database Layer
4. **Layout Parser** - Depends on Contract Resolver output
5. **Storage Reader** - Depends on Type Decoder, Layout Parser
6. **Transaction Tracer** - Depends on Type Decoder, Layout Parser
7. **API Layer** - Orchestrates all services
8. **Frontend** - Consumes API

## Cross-Cutting Concerns

### Configuration
All services share configuration via `app/config.py`:
- RPC endpoints per chain
- Database connection
- External API keys (Etherscan)
- Timeouts and limits

### Error Handling
Consistent error types across services:
- `ContractNotFoundError`
- `NotAContractError`
- `UnverifiedContractError`
- `RPCError`
- `TraceNotAvailableError`
- `DecodeError`

### Non-Goals (MVP)
- No Redis or multi-tier caching
- No background workers/queues
- No beacon/diamond proxy support
- No cross-contract aggregation; one contract per request

### Logging
Structured logging with context:
- Chain ID
- Contract address
- Block number / Tx hash
- Operation timing
