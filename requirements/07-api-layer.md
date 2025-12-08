# API Layer

## Overview

The API Layer is the FastAPI application that exposes HTTP endpoints for the frontend. It orchestrates the backend services (resolver, parser, reader, tracer) and handles request validation, error responses, and CORS. MVP constraints: Postgres is the only cache, all work is in-request, and degraded/partial responses are allowed (hex-only for unverified, trace unavailable, partial storage reads).

## Implementation Status: ✅ Complete

### Key Implementation Decisions

1. **Graceful Degradation**: All endpoints return 200 with degraded data rather than failing when possible. `trace_unavailable=True` signals UI to show warning instead of error.

2. **Layout Persistence**: Routes now save parsed layouts to the database after successful resolution, avoiding recompilation on subsequent requests.

3. **Response Models**: API responses include both `decoded` (Python value) and `display` (formatted string) for flexible UI rendering.

4. **CORS Configuration**: Configured for localhost:3000 development; production deployment will need environment-specific origins.

## Location

```
backend/app/main.py                 # FastAPI app
backend/app/api/routes/             # Route handlers
backend/app/api/dependencies.py     # Dependency injection
backend/app/models/api.py           # Request/Response models
```

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `fastapi` | Web framework |
| `uvicorn` | ASGI server |
| `pydantic` | Request/response validation |
| All backend services | Business logic |

## API Endpoints

### Contract Endpoints

```
GET /api/contracts/{chain_id}/{address}
    Get contract metadata (proxy info, verification status, etc.)

GET /api/contracts/{chain_id}/{address}/layout
    Get storage layout for a verified contract
```

### Storage Endpoints

```
GET /api/storage/{chain_id}/{address}
    Get storage snapshot at a block
    Query params: block (required)

GET /api/storage/{chain_id}/{address}/slot/{slot}
    Get single slot value
    Query params: block (required)
```

### Transaction Endpoints

```
GET /api/tx/{chain_id}/{address}/{tx_hash}
    Get storage changes for a contract in a transaction
```

## Request/Response Models

```python
# backend/app/models/api.py

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Any
from enum import Enum


# === Enums ===

class ChainId(int, Enum):
    MAINNET = 1
    SEPOLIA = 11155111


# === Request Models ===

class StorageQuery(BaseModel):
    """Query parameters for storage endpoints."""
    block: int = Field(..., description="Block number", ge=0)
    mapping_keys: Optional[dict[int, list[str]]] = Field(
        None,
        description="Mapping keys to include: {base_slot: [keys]}"
    )


class TxQuery(BaseModel):
    """Query parameters for transaction endpoints."""
    # No additional params needed - tx_hash in path


# === Response Models ===

class ContractResponse(BaseModel):
    """Contract metadata response."""
    chain_id: int
    address: str
    name: Optional[str]
    code_hash: Optional[str]

    is_proxy: bool
    proxy_type: Optional[str]
    implementation_address: Optional[str]

    is_verified: bool
    verification_source: Optional[str]
    compiler_version: Optional[str]

    has_layout: bool  # True if storage_layout available


class StorageTypeResponse(BaseModel):
    """Storage type definition."""
    id: str
    label: str
    kind: str  # value, array, mapping, struct
    encoding: str
    num_bytes: Optional[int]
    element_type: Optional[str]
    array_length: Optional[int]
    key_type: Optional[str]
    value_type: Optional[str]


class StorageVariableResponse(BaseModel):
    """Storage variable definition."""
    name: str
    slot: int
    offset: int
    size: int
    type_id: str
    type_label: str


class StorageLayoutResponse(BaseModel):
    """Full storage layout."""
    contract_name: str
    variables: List[StorageVariableResponse]
    types: dict[str, StorageTypeResponse]


class SlotValueResponse(BaseModel):
    """A single slot with its value."""
    slot: str  # Hex
    raw_value: str  # Hex bytes32
    variable_name: Optional[str]
    variable_path: Optional[str]  # e.g., "balances[0x...]"
    type_label: Optional[str]
    decoded_value: Optional[Any]
    display_value: Optional[str]  # Formatted for display


class StorageSnapshotResponse(BaseModel):
    """Storage state at a block."""
    chain_id: int
    address: str
    block_number: int
    slots: List[SlotValueResponse]
    is_complete: bool
    is_verified: bool  # Whether contract is verified


class StorageChangeResponse(BaseModel):
    """A single storage change."""
    slot: str
    variable_name: Optional[str]
    variable_path: Optional[str]
    type_label: Optional[str]

    old_raw: str
    new_raw: str
    old_decoded: Optional[Any]
    new_decoded: Optional[Any]
    old_display: Optional[str]
    new_display: Optional[str]


class TransactionDiffResponse(BaseModel):
    """Storage changes in a transaction."""
    chain_id: int
    address: str
    tx_hash: str
    block_number: int
    changes: List[StorageChangeResponse]
    is_complete: bool
    is_verified: bool


class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    code: str
    details: Optional[dict] = None
```

## Route Implementations

### Contract Routes

```python
# backend/app/api/routes/contracts.py

from fastapi import APIRouter, Depends, HTTPException
from app.api.dependencies import get_contract_service
from app.models.api import ContractResponse, StorageLayoutResponse

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


@router.get("/{chain_id}/{address}", response_model=ContractResponse)
async def get_contract(
    chain_id: int,
    address: str,
    service: ContractService = Depends(get_contract_service)
):
    """
    Get contract metadata.

    Returns proxy info, verification status, and whether layout is available.
    """
    try:
        metadata = await service.resolve_contract(chain_id, address)
    except NotAContractError:
        raise HTTPException(
            status_code=404,
            detail={"error": "Not a contract", "code": "NOT_CONTRACT"}
        )
    except RPCError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": str(e), "code": "RPC_ERROR"}
        )

    return ContractResponse(
        chain_id=metadata.chain_id,
        address=metadata.address,
        name=metadata.name,
        code_hash=metadata.code_hash,
        is_proxy=metadata.is_proxy,
        proxy_type=metadata.proxy_type,
        implementation_address=metadata.implementation_address,
        is_verified=metadata.is_verified,
        verification_source=metadata.verification_source,
        compiler_version=metadata.compiler_version,
        has_layout=metadata.storage_layout is not None
    )


@router.get("/{chain_id}/{address}/layout", response_model=StorageLayoutResponse)
async def get_layout(
    chain_id: int,
    address: str,
    service: ContractService = Depends(get_contract_service)
):
    """
    Get storage layout for a verified contract.

    Returns 404 if contract is not verified.
    """
    metadata = await service.resolve_contract(chain_id, address)

    if not metadata.is_verified or not metadata.storage_layout:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "Contract not verified or layout unavailable",
                "code": "NO_LAYOUT"
            }
        )

    layout = metadata.storage_layout
    return StorageLayoutResponse(
        contract_name=layout.contract_name,
        variables=[
            StorageVariableResponse(
                name=v.name,
                slot=v.slot,
                offset=v.offset,
                size=v.size,
                type_id=v.type_id,
                type_label=v.label
            )
            for v in layout.variables
        ],
        types={
            tid: StorageTypeResponse(
                id=t.id,
                label=t.label,
                kind=t.kind,
                encoding=t.encoding,
                num_bytes=t.num_bytes,
                element_type=t.element_type,
                array_length=t.array_length,
                key_type=t.key_type,
                value_type=t.value_type
            )
            for tid, t in layout.types.items()
        }
    )
```

### Storage Routes

```python
# backend/app/api/routes/storage.py

from fastapi import APIRouter, Depends, HTTPException, Query
from app.api.dependencies import get_storage_service
from app.models.api import StorageSnapshotResponse, SlotValueResponse

router = APIRouter(prefix="/api/storage", tags=["storage"])


@router.get("/{chain_id}/{address}", response_model=StorageSnapshotResponse)
async def get_storage(
    chain_id: int,
    address: str,
    block: int = Query(..., ge=0, description="Block number"),
    mapping_keys: Optional[str] = Query(
        None,
        description="JSON-encoded mapping keys: {slot: [keys]}"
    ),
    service: StorageService = Depends(get_storage_service)
):
    """
    Get storage snapshot at a block.

    For verified contracts, returns all variables with decoded values.
    For unverified contracts, scans slots 0-256 for non-zero values.

    Optional mapping_keys parameter allows reading specific mapping entries.
    """
    # Parse mapping keys if provided
    keys_dict = None
    if mapping_keys:
        try:
            import json
            keys_dict = json.loads(mapping_keys)
            # Convert string keys to int
            keys_dict = {int(k): v for k, v in keys_dict.items()}
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail={"error": "Invalid mapping_keys format", "code": "INVALID_PARAMS"}
            )

    try:
        snapshot = await service.get_storage_at_block(
            chain_id=chain_id,
            address=address,
            block_number=block,
            mapping_keys=keys_dict
        )
    except NotAContractError:
        raise HTTPException(status_code=404, detail={"error": "Not a contract", "code": "NOT_CONTRACT"})
    except RPCError as e:
        raise HTTPException(status_code=502, detail={"error": str(e), "code": "RPC_ERROR"})

    return StorageSnapshotResponse(
        chain_id=snapshot.chain_id,
        address=snapshot.address,
        block_number=snapshot.block_number,
        slots=[
            SlotValueResponse(
                slot=s.slot,
                raw_value=s.raw_value,
                variable_name=s.variable.name if s.variable else None,
                variable_path=s.variable_path,
                type_label=s.variable.label if s.variable else None,
                decoded_value=s.decoded_value.decoded if s.decoded_value else None,
                display_value=s.decoded_value.display if s.decoded_value else None
            )
            for s in snapshot.slots
        ],
        is_complete=snapshot.is_complete,
        is_verified=snapshot.layout is not None
    )


@router.get("/{chain_id}/{address}/slot/{slot}", response_model=SlotValueResponse)
async def get_slot(
    chain_id: int,
    address: str,
    slot: str,  # Hex or decimal
    block: int = Query(..., ge=0),
    service: StorageService = Depends(get_storage_service)
):
    """
    Get a single slot value.

    Slot can be provided as hex (0x...) or decimal.
    """
    # Parse slot
    try:
        if slot.startswith("0x"):
            slot_int = int(slot, 16)
        else:
            slot_int = int(slot)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"error": "Invalid slot format", "code": "INVALID_SLOT"}
        )

    try:
        result = await service.get_single_slot(
            chain_id=chain_id,
            address=address,
            slot=slot_int,
            block_number=block
        )
    except RPCError as e:
        raise HTTPException(status_code=502, detail={"error": str(e), "code": "RPC_ERROR"})

    return SlotValueResponse(
        slot=hex(slot_int),
        raw_value=result.raw_value,
        variable_name=result.variable.name if result.variable else None,
        variable_path=result.variable_path,
        type_label=result.variable.label if result.variable else None,
        decoded_value=result.decoded_value.decoded if result.decoded_value else None,
        display_value=result.decoded_value.display if result.decoded_value else None
    )
```

### Transaction Routes

```python
# backend/app/api/routes/changes.py

from fastapi import APIRouter, Depends, HTTPException
from app.api.dependencies import get_tracer_service
from app.models.api import TransactionDiffResponse, StorageChangeResponse

router = APIRouter(prefix="/api/tx", tags=["transactions"])


@router.get("/{chain_id}/{address}/{tx_hash}", response_model=TransactionDiffResponse)
async def get_tx_diff(
    chain_id: int,
    address: str,
    tx_hash: str,
    service: TracerService = Depends(get_tracer_service)
):
    """
    Get storage changes for a contract in a transaction.

    Returns all SSTORE operations that modified the contract's storage,
    with before/after values decoded if contract is verified.
    """
    # Validate tx_hash format
    if not tx_hash.startswith("0x") or len(tx_hash) != 66:
        raise HTTPException(
            status_code=400,
            detail={"error": "Invalid transaction hash", "code": "INVALID_TX_HASH"}
        )

    try:
        diff = await service.trace_transaction(
            chain_id=chain_id,
            contract_address=address,
            tx_hash=tx_hash
        )
    except TransactionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": "Transaction not found", "code": "TX_NOT_FOUND"}
        )
    except TraceNotAvailableError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": str(e), "code": "TRACE_UNAVAILABLE"}
        )
    except NotAContractError:
        raise HTTPException(
            status_code=404,
            detail={"error": "Not a contract", "code": "NOT_CONTRACT"}
        )

    return TransactionDiffResponse(
        chain_id=diff.chain_id,
        address=diff.contract_address,
        tx_hash=diff.tx_hash,
        block_number=diff.block_number,
        changes=[
            StorageChangeResponse(
                slot=c.slot,
                variable_name=c.variable.name if c.variable else None,
                variable_path=c.variable_path,
                type_label=c.variable.label if c.variable else None,
                old_raw=c.old_value,
                new_raw=c.new_value,
                old_decoded=c.old_decoded.decoded if c.old_decoded else None,
                new_decoded=c.new_decoded.decoded if c.new_decoded else None,
                old_display=c.old_decoded.display if c.old_decoded else None,
                new_display=c.new_decoded.display if c.new_decoded else None
            )
            for c in diff.changes
        ],
        is_complete=diff.is_complete,
        is_verified=diff.layout is not None
    )
```

## Dependency Injection

```python
# backend/app/api/dependencies.py

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.models.database import get_session

# Services (created once per request)

async def get_contract_service(
    session: AsyncSession = Depends(get_session),
    settings = Depends(get_settings)
) -> ContractService:
    """Get ContractService with all dependencies."""
    web3_provider = Web3Provider(settings.rpc_urls)
    contract_repo = ContractRepository(session)
    cache_repo = CacheRepository(session, settings.cache)

    resolver = ContractResolver(
        web3_provider=web3_provider,
        config=settings.resolver,
        cache=contract_repo
    )

    layout_parser = LayoutParser()

    return ContractService(
        resolver=resolver,
        layout_parser=layout_parser,
        contract_repo=contract_repo
    )


async def get_storage_service(
    session: AsyncSession = Depends(get_session),
    settings = Depends(get_settings)
) -> StorageService:
    """Get StorageService with all dependencies."""
    web3_provider = Web3Provider(settings.rpc_urls)
    contract_repo = ContractRepository(session)
    cache_repo = CacheRepository(session, settings.cache)

    decoder = TypeDecoder(settings.decoder)

    storage_reader = StorageReader(
        web3_provider=web3_provider,
        config=settings.storage,
        decoder=decoder,
        cache=cache_repo
    )

    resolver = ContractResolver(
        web3_provider=web3_provider,
        config=settings.resolver,
        cache=contract_repo
    )

    layout_parser = LayoutParser()

    return StorageService(
        storage_reader=storage_reader,
        resolver=resolver,
        layout_parser=layout_parser,
        contract_repo=contract_repo,
        cache_repo=cache_repo
    )


async def get_tracer_service(
    session: AsyncSession = Depends(get_session),
    settings = Depends(get_settings)
) -> TracerService:
    """Get TracerService with all dependencies."""
    # Similar setup...
    pass
```

## Main Application

```python
# backend/app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import contracts, storage, changes
from app.config import get_settings

def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="StorageScan API",
        description="Ethereum storage analyzer API",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc"
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(contracts.router)
    app.include_router(storage.router)
    app.include_router(changes.router)

    # Health check
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
```

## Error Handling

```python
# backend/app/api/errors.py

from fastapi import Request
from fastapi.responses import JSONResponse

ERROR_CODES = {
    "NOT_CONTRACT": 404,
    "NO_LAYOUT": 404,
    "TX_NOT_FOUND": 404,
    "INVALID_PARAMS": 400,
    "INVALID_SLOT": 400,
    "INVALID_TX_HASH": 400,
    "RPC_ERROR": 502,
    "TRACE_UNAVAILABLE": 502,
    "TIMEOUT": 504,
    "INTERNAL": 500
}


async def error_handler(request: Request, exc: Exception):
    """Global exception handler."""
    if isinstance(exc, NotAContractError):
        return JSONResponse(
            status_code=404,
            content={"error": str(exc), "code": "NOT_CONTRACT"}
        )
    elif isinstance(exc, RPCError):
        return JSONResponse(
            status_code=502,
            content={"error": str(exc), "code": "RPC_ERROR"}
        )
    # ... more handlers

    # Default
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "code": "INTERNAL"}
    )
```

## Configuration

```python
# backend/app/config.py

from pydantic import BaseSettings
from typing import List

class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # CORS
    cors_origins: List[str] = ["http://localhost:3000"]

    # Database
    database_url: str = "postgresql+asyncpg://wavey@localhost:5432/storagescan_dev"

    # RPC endpoints
    rpc_urls: dict = {
        1: "https://eth-mainnet.g.alchemy.com/v2/...",
        11155111: "https://eth-sepolia.g.alchemy.com/v2/..."
    }

    # External APIs
    etherscan_keys: dict = {
        1: "...",
        11155111: "..."
    }

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

## Testing Strategy

### Unit Tests

1. **Request validation**
   - Invalid chain_id
   - Invalid address format
   - Invalid tx_hash format

2. **Response serialization**
   - All model fields present
   - Correct types

### Integration Tests

1. **Full request flow**
   - Get contract -> Get storage
   - Get tx diff

2. **Error responses**
   - 404 for non-contract
   - 502 for RPC errors

## Running the Server

```bash
# Development
uvicorn app.main:app --reload --port 8000

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1-4
```

## Degraded Responses

- Tracing unavailable/timeouts: return HTTP 200 with `trace_unavailable` flag and warning.
- Contract unverified: return hex-only view.
- Storage read timeout: return partial snapshot with `is_complete=False`.
