# SlotScan

Ethereum smart contract storage analyzer. View storage layouts, decode values, and trace transaction storage changes.

## Components

- **Backend** (`/backend`): FastAPI API for fetching sources, parsing layouts, reading storage, and tracing txs.
- **Frontend** (`/frontend`): Next.js UI for browsing storage and diffs.
- **PostgreSQL**: Caches contract metadata and results.

Transaction-wide history is available at
`GET /api/slotscan/tx/{chain_id}/{tx_hash}`. Add
`?include_global_order=true` for execution-ordered event references. The API
groups every persistent write owner and retains restored, no-op, and reverted
slot histories. Storage layouts are fetched from Sourcify when available;
missing layouts degrade to raw slots without request-time compilation.

## Quick Start

### 1. Database (skip if you have postgres running)

```bash
createdb slotscan_dev
```

### 2. Backend

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head  # creates tables (only needed once)
python -m app.main    # starts server on :8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev  # starts on :3000
```

## Configuration

Copy `.env` to project root and edit:

```
DATABASE_URL=postgresql+asyncpg://wavey@localhost:5432/slotscan_dev
RPC_URL_1=http://your-rpc:8545
ETHERSCAN_API_KEY_1=your-key
```

## Notes

- **alembic**: Database migration tool. `alembic upgrade head` applies schema changes.
- **uvicorn**: ASGI server. Used internally by `python -m app.main`. Add `--reload` for auto-reload during dev.
