# SlotScan Next Steps

This document outlines potential enhancements and improvements for SlotScan beyond the MVP implementation.

## Current Status: MVP Complete

All core services are implemented and functional:
- Contract Resolver with Sourcify/Etherscan integration
- Layout Parser with direct Sourcify layout support
- Storage Reader with batch RPC and mapping slot computation
- Transaction Tracer with mapping key inference
- Type Decoder with heuristic decoding
- PostgreSQL persistence layer
- FastAPI backend with graceful degradation
- Next.js frontend with React Query

---

## Priority 1: Core Improvements

### 1.1 Nested Mapping Key Inference

**Current limitation**: Only single-level address-keyed mappings are matched via candidate address inference.

**Enhancement**: Support nested mappings like `allowances[owner][spender]` by:
- Parsing Approval events for both owner and spender
- Computing nested slots: `keccak256(spender || keccak256(owner || base_slot))`
- Displaying as `allowances[0x...owner][0x...spender]`

**Files**: `backend/app/services/tracer.py`

### 1.2 uint256/bytes32 Mapping Keys

**Current limitation**: Only address-keyed mappings are matched.

**Enhancement**: Support uint256 and bytes32 keys by:
- Extracting numeric values from log data
- Parsing function input data for key arguments
- Computing slots with appropriate encoding

**Files**: `backend/app/utils/slots.py`, `backend/app/services/tracer.py`

### 1.3 Error Visibility

**Current limitation**: Layout parsing failures are silently caught.

**Enhancement**: Add structured logging and optional `layout_error` field in API responses to help debug why layouts fail to parse.

**Files**: `backend/app/api/routes/*.py`, `backend/app/services/resolver.py`

---

## Priority 2: Multi-Chain Support

### 2.1 Additional Chain Explorers

**Current**: Only Ethereum mainnet explorer URLs configured.

**Enhancement**: Add explorer URL mappings for:
- Polygon (polygonscan.com)
- Arbitrum (arbiscan.io)
- Optimism (optimistic.etherscan.io)
- Base (basescan.org)
- BSC (bscscan.com)

**Files**: `frontend/src/lib/constants.ts`

### 2.2 Chain-Specific RPC Configuration

**Enhancement**: Support multiple RPC endpoints per chain with fallback logic.

**Files**: `backend/app/config.py`, `backend/app/services/web3_provider.py`

---

## Priority 3: UI Enhancements

### 3.1 Storage Tree View

**Current**: Flat list of slots on contract page.

**Enhancement**: Hierarchical tree view showing:
- Grouped static variables
- Expandable structs with member fields
- Collapsible mapping entries

**Files**: `frontend/src/components/storage/StorageTree.tsx`

### 3.2 Mapping Key Input

**Enhancement**: Allow users to manually enter mapping keys to explore specific entries.

**Files**: `frontend/src/components/storage/MappingKeyInput.tsx`

### 3.3 Block Selector

**Enhancement**: Block number input with "latest" option and block range navigation.

**Files**: `frontend/src/components/storage/BlockSelector.tsx`

### 3.4 Mobile Responsiveness

**Current**: Desktop-first design.

**Enhancement**: Responsive layouts for tablet and mobile viewing.

**Files**: Various component files, `tailwind.config.js`

---

## Priority 4: Advanced Features

### 4.1 Storage Comparison

**Enhancement**: Compare storage state between two blocks, showing added/removed/changed slots.

**API**: `GET /api/storage/{chain_id}/{address}/compare?block1=X&block2=Y`

### 4.2 Historical Transaction List

**Enhancement**: List recent transactions that modified a contract's storage.

**API**: `GET /api/contracts/{chain_id}/{address}/transactions`

### 4.3 Contract Upgrade Tracking

**Enhancement**: For proxy contracts, track implementation changes over time.

### 4.4 Export Functionality

**Enhancement**: Export storage snapshots and diffs as JSON/CSV.

---

## Priority 5: Performance & Scalability

### 5.1 Caching Improvements

**Enhancement**:
- Add Redis for high-frequency lookups
- Implement cache warming for popular contracts
- Add cache TTL configuration

### 5.2 Background Workers

**Enhancement**: Offload heavy operations (compilation, tracing) to background workers.

### 5.3 Rate Limiting

**Enhancement**: Add rate limiting per IP/API key to prevent abuse.

---

## Priority 6: Developer Experience

### 6.1 Testing

**Enhancement**:
- Add comprehensive unit tests for all services
- Add integration tests with test contracts
- Add E2E tests with Playwright

### 6.2 Documentation

**Enhancement**:
- API documentation with OpenAPI/Swagger
- Developer guide for local setup
- Architecture documentation

### 6.3 Deployment

**Enhancement**:
- Docker Compose for local development
- Kubernetes manifests for production
- CI/CD pipeline configuration

---

## Out of Scope (V1)

These features were explicitly excluded from the MVP and remain out of scope:

- Beacon proxy support
- Diamond proxy support
- Cross-contract storage aggregation
- Real-time subscription to storage changes
- Charts and visualizations
- User accounts and saved searches

---

## Technical Debt

### Known Issues

1. **Silent exception handling**: Several `except Exception` blocks silently swallow errors. These should be logged.

2. **Hardcoded chain IDs**: Some chain-specific logic assumes mainnet. Should be configurable.

3. **Missing input validation**: API endpoints should validate address format more strictly.

### Code Quality

1. Add type hints to all function signatures
2. Add docstrings to public methods
3. Consolidate duplicate utility functions
4. Add request timeout handling
