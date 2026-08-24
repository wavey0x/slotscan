# SlotScan

Ethereum storage inspection and transaction forensics.

**Production:** [slotscan.info](https://slotscan.info)

SlotScan turns raw EVM storage into readable contract state. It resolves
verified layouts, decodes values, traces transaction-wide storage activity,
and compares layouts across contracts or historical blocks.

## Features

- Decode Solidity and Vyper storage layouts, including packed values,
  mappings, arrays, structs, and namespaced storage.
- Trace ordered `SSTORE` and `TSTORE` activity with immediate values, reverted
  writes, mapping preimages, and authoritative final state.
- Resolve proxies and EIP-7702 delegation at the selected historical block
  while keeping code identity separate from storage ownership.
- Compare exact compiler layouts by physical storage shape, packing, and
  encoding—not variable names.
- Run performance-critical analysis through a custom Reth binary with
  single-replay tracing and native vector storage reads.
- Preserve raw evidence and report incomplete analysis explicitly when source,
  layout, or trace detail is unavailable.

## Architecture

| Component | Purpose |
| --- | --- |
| [`frontend/`](frontend/) | Next.js application |
| [`backend/`](backend/) | FastAPI analysis API and SQLite-backed caches |
| [`reth-slotscan/`](reth-slotscan/) | Downstream Reth binary with native SlotScan RPC extensions |

The custom Reth node collects the state diff, ordered writes, call-frame
outcomes, storage reads, and SHA3 preimages in one canonical replay. Native
vector storage reads are pinned to one exact block hash for coherent results.

See [backend architecture](backend/ARCHITECTURE.md),
[Reth integration](reth-slotscan/README.md), and
[benchmark methodology](backend/benchmarks/README.md) for implementation
details.

## Local Development

Prerequisites:

- Python 3 with `venv`
- Node.js and npm
- A synced Ethereum mainnet node running the
  [`reth-slotscan`](reth-slotscan/README.md) binary

Copy the environment template and configure the RPC endpoint and Etherscan API
key. The default SQLite database is `backend/slotscan.sqlite3`; set
`DATABASE_PATH` to override it.

```bash
cp .env.example .env
```

Start the backend:

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.main
```

Start the frontend in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at [localhost:3000](http://localhost:3000) and the API at
[localhost:8000](http://localhost:8000).

## Development

Product behavior and invariants are defined in
[`REQUIREMENTS.md`](REQUIREMENTS.md). Repository conventions and proportional
validation requirements are defined in [`AGENTS.md`](AGENTS.md).
