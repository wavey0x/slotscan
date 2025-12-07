# StorageScan - Ethereum Storage Analyzer

A minimalist tool for analyzing smart contract storage layouts, current values, and historical changes across EVM-compatible chains.

---

## Table of Contents

1. [Project Philosophy](#1-project-philosophy)
2. [User Stories](#2-user-stories)
3. [Architecture Overview](#3-architecture-overview)
4. [Technical Stack](#4-technical-stack)
5. [Contract Resolution & Layout](#5-contract-resolution--layout)
6. [Storage Reads & Change Detection](#6-storage-reads--change-detection)
7. [Complex Type Handling](#7-complex-type-handling)
8. [Unverified Contracts](#8-unverified-contracts)
9. [Caching & Performance](#9-caching--performance)
10. [UI/UX Design](#10-uiux-design)
11. [Data Models](#11-data-models)
12. [Future Features](#12-future-features)

---

## 1. Project Philosophy

### Primary Goal

Given `(chain, address, block OR transaction)`, provide:

- **Storage layout** - as rich as possible with full type information
- **Slot values at block** - decoded according to Solidity types
- **Changes within transaction** - which slots changed and how
- **Clean, programmatic access** - well-designed API for researchers (future)

### Design Principles

- **Minimalist UI** - Clean, organized, information-dense without clutter
- **Fast by default** - Aggressive caching, sensible limits, fail-fast behavior
- **Verified-first** - Best experience for verified contracts; graceful degradation for unverified
- **Single focus** - One contract, one block or transaction per query

### Conscious Limitations

| Constraint | Limit | Rationale |
|------------|-------|-----------|
| Contracts per query | 1 | Complexity management |
| Scope per query | 1 block or 1 transaction | Processing simplicity |
| Supported chains | Only chains with tracing RPC | Required for change detection |

### Out of Scope (v1)

- Block range queries (future feature)
- Multi-contract queries or cross-contract analysis
- Automated decompilation of unverified contracts
- Real-time subscription/streaming updates
- Time-series charts across multiple blocks

---

## 2. User Stories

### Story 1: DeFi User Investigating Historical State

**Persona:** Non-technical DeFi user with basic blockchain knowledge

**Scenario:**
> "I was told that a protocol's `maxWithdrawal` limit was changed right before I tried to withdraw, causing my transaction to fail. The variable is private so I can't just call a getter. I want to check what the value was at a specific block to verify this claim."

**User Journey:**
1. User navigates to StorageScan
2. Enters the protocol's contract address
3. Enters the block number they care about
4. Sees the full storage layout with decoded values
5. Finds `maxWithdrawal` in the tree view
6. Sees the value at that block: `100,000 USDC`
7. Changes block number to one block earlier
8. Sees the previous value: `1,000,000 USDC` — confirms the limit was lowered

**Key Requirements:**
- Must handle private/internal variables (not just public getters)
- Block number input must be prominent and easy to change
- Values must be human-readable (decoded, with units where possible)
- No blockchain development knowledge required to use

---

### Story 2: Security Researcher Analyzing a Hack

**Persona:** Security researcher or auditor investigating an exploit

**Scenario:**
> "A protocol was exploited in a complex transaction involving flash loans and multiple internal calls. I need to quickly see which storage slots were modified during this transaction to understand the attack vector."

**User Journey:**
1. Researcher navigates to StorageScan
2. Enters the victim contract address
3. Pastes the exploit transaction hash
4. Sees a clear list of all storage changes in that transaction:
   - `owner`: `0xProtocolMultisig...` → `0xAttacker...`
   - `balances[attacker]`: `0` → `5,000,000 USDC`
   - `totalSupply`: unchanged (not shown, or shown as no-change)
5. Can toggle to see raw hex values for deeper analysis
6. Can click on any slot to see its position in the storage layout

**Key Requirements:**
- Transaction hash input triggers automatic change detection
- Clear before/after diff view for all modified slots
- Ability to see raw hex values (for unverified or when needed)
- Fast — researcher may be analyzing many transactions
- Works even for unverified contracts (shows raw slots)

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Web Frontend                            │
│                    (Next.js + Tailwind CSS)                     │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                        API Server                               │
│                   (Python FastAPI + web3.py)                    │
├─────────────────────────────────────────────────────────────────┤
│  Services:                                                      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │  Contract    │ │   Storage    │ │      Change              │ │
│  │  Resolver    │ │   Reader     │ │      Detector            │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │   Layout     │ │    Type      │ │       Cache              │ │
│  │   Parser     │ │   Decoder    │ │       Manager            │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
         │                   │                    │
         ▼                   ▼                    ▼
┌─────────────┐    ┌─────────────────┐    ┌─────────────┐
│  Postgres   │    │   Redis Cache   │    │  RPC Nodes  │
│  (metadata, │    │   (hot cache)   │    │  (tracing)  │
│   layouts)  │    │                 │    │             │
└─────────────┘    └─────────────────┘    └─────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│              External Services                                  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐        │
│  │   Sourcify    │  │   Etherscan   │  │  Chain RPCs   │        │
│  │   (sources)   │  │   (sources)   │  │  (data)       │        │
│  └───────────────┘  └───────────────┘  └───────────────┘        │
└─────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| **Contract Resolver** | Detect proxies, fetch verification status, obtain source code |
| **Layout Parser** | Parse solc output, normalize storage layout to internal schema |
| **Storage Reader** | Batch `eth_getStorageAt` calls, handle slot computation |
| **Change Detector** | Trace transactions, extract SSTORE operations, map to layout |
| **Type Decoder** | Decode raw bytes32 values to Solidity types |
| **Cache Manager** | Coordinate Redis/Postgres caching strategies |

---

## 4. Technical Stack

### Backend

| Component | Technology | Rationale |
|-----------|------------|-----------|
| **Language** | Python 3.11+ | Ecosystem, web3.py compatibility |
| **Framework** | FastAPI | Async support, automatic OpenAPI docs, type hints |
| **Ethereum** | web3.py | De facto Python Ethereum library |
| **Database** | PostgreSQL | JSONB for layouts, reliable persistence |
| **Cache** | Redis | Fast ephemeral cache for hot data |
| **Task Queue** | None (v1) | Synchronous processing initially |

### Frontend

| Component | Technology | Rationale |
|-----------|------------|-----------|
| **Framework** | Next.js 14+ (App Router) | SSR, routing, React ecosystem |
| **Styling** | Tailwind CSS | Utility-first, minimal design system |
| **State** | React Query (TanStack Query) | Server state caching, loading states |
| **Components** | Headless UI / Radix | Accessible, unstyled primitives |
| **Charts** | Recharts or Lightweight Charts | Clean, minimal visualization |

### Project Structure

```
storagescan/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI application entry
│   │   ├── config.py               # Settings and environment
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── routes/
│   │   │   │   ├── contracts.py    # Contract endpoints
│   │   │   │   ├── storage.py      # Storage read endpoints
│   │   │   │   └── changes.py      # Change detection endpoints
│   │   │   └── dependencies.py     # Shared dependencies
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── resolver.py         # Contract resolution logic
│   │   │   ├── layout.py           # Layout parsing and normalization
│   │   │   ├── storage.py          # Storage reading logic
│   │   │   ├── tracer.py           # Transaction tracing
│   │   │   └── decoder.py          # Type decoding
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── domain.py           # Domain models (dataclasses)
│   │   │   ├── database.py         # SQLAlchemy models
│   │   │   └── api.py              # Pydantic request/response models
│   │   ├── repositories/
│   │   │   ├── __init__.py
│   │   │   ├── contracts.py        # Contract data access
│   │   │   └── cache.py            # Cache operations
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── ethereum.py         # Ethereum helpers
│   │       ├── solidity.py         # Solidity type helpers
│   │       └── slots.py            # Slot computation helpers
│   ├── tests/
│   ├── alembic/                    # Database migrations
│   ├── requirements.txt
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── app/                    # Next.js app router
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx            # Home/search page
│   │   │   └── contract/
│   │   │       └── [chain]/
│   │   │           └── [address]/
│   │   │               ├── page.tsx           # Contract overview
│   │   │               ├── layout/page.tsx    # Storage layout view
│   │   │               └── changes/page.tsx   # Change history
│   │   ├── components/
│   │   │   ├── ui/                 # Base UI components
│   │   │   ├── layout/             # Layout components
│   │   │   ├── storage/            # Storage-specific components
│   │   │   │   ├── StorageTree.tsx
│   │   │   │   ├── SlotValue.tsx
│   │   │   │   └── ChangeTable.tsx
│   │   │   └── contract/           # Contract-specific components
│   │   ├── lib/
│   │   │   ├── api.ts              # API client
│   │   │   └── utils.ts            # Frontend utilities
│   │   └── styles/
│   │       └── globals.css
│   ├── public/
│   ├── package.json
│   └── tailwind.config.js
├── docker-compose.yml
├── REQUIREMENTS.md
├── README.md
└── .env.example
```

---

## 5. Contract Resolution & Layout

### 5.1 Contract Resolution Pipeline

```
Input: (chainId, address)
                │
                ▼
        ┌───────────────┐
        │ eth_getCode() │
        └───────────────┘
                │
        ┌───────┴───────┐
        │ Is Contract?  │
        └───────────────┘
           │         │
          No        Yes
           │         │
           ▼         ▼
        [Error]  ┌──────────────────┐
                 │  Proxy Detection │
                 │  (EIP-1967, etc) │
                 └──────────────────┘
                          │
                 ┌────────┴────────┐
                 │    Is Proxy?    │
                 └─────────────────┘
                    │           │
                   Yes          No
                    │           │
                    ▼           │
         ┌──────────────────┐   │
         │ Resolve Impl     │   │
         │ Address          │   │
         └──────────────────┘   │
                    │           │
                    └─────┬─────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │ Try Sourcify    │
                 └─────────────────┘
                          │
                 ┌────────┴────────┐
                 │   Verified?     │
                 └─────────────────┘
                    │           │
                   Yes          No
                    │           │
                    │           ▼
                    │  ┌─────────────────┐
                    │  │ Try Etherscan   │
                    │  └─────────────────┘
                    │           │
                    └─────┬─────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │ Parse Layout    │
                 │ (if verified)   │
                 └─────────────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │ Store & Return  │
                 └─────────────────┘
```

### 5.2 Proxy Detection

Support the following proxy patterns:

| Pattern | Implementation Slot | Notes |
|---------|---------------------|-------|
| EIP-1967 Implementation | `0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc` | Most common |
| EIP-1967 Beacon | `0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50` | Beacon proxy |
| EIP-1967 Admin | `0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103` | Admin slot |
| EIP-1822 (UUPS) | `0xc5f16f0fcc639fa48a6947836d9850f504798523bf8c9a3a87d5876cf622bcf7` | Proxiable |
| OpenZeppelin Legacy | `0x7050c9e0f4ca769c69bd3a8ef740bc37934f8e2c036e5a723fd8ee048ed3f8c3` | Older OZ proxies |

### 5.3 Layout Schema

Internal normalized schema for storage layouts:

```python
@dataclass
class StorageVariable:
    name: str
    slot: int              # Base slot number
    offset: int            # Byte offset within slot (0-31)
    size: int              # Size in bytes
    type_id: str           # Reference to StorageType
    label: str             # Human-readable label

@dataclass
class StorageType:
    id: str
    label: str             # e.g., "t_uint256", "t_struct(Config)_storage"
    kind: Literal["value", "array", "mapping", "struct", "contract"]
    encoding: Literal["inplace", "bytes", "dynamic_array", "mapping"]

    # For value types
    base_type: Optional[str]           # e.g., "uint256", "address", "bool"
    num_bytes: Optional[int]

    # For arrays
    element_type: Optional[str]        # Type ID of element
    array_length: Optional[int]        # None for dynamic arrays

    # For mappings
    key_type: Optional[str]
    value_type: Optional[str]

    # For structs
    members: Optional[List[StorageVariable]]

@dataclass
class StorageLayout:
    contract_name: str
    variables: List[StorageVariable]
    types: Dict[str, StorageType]
```

### 5.4 Layout Parsing

For verified contracts with source code:

1. **Compile with `solc`** using exact compiler version and settings from metadata
2. **Extract `storageLayout`** from compiler output
3. **Normalize** to internal schema
4. **Cache** in PostgreSQL as JSONB

---

## 6. Storage Reads & Change Detection

### 6.1 Reading State at Block

For `(chainId, address, blockNumber)`:

**Verified Contracts:**
- Enumerate all slots from `storageLayout.storage`
- For dynamic types (arrays, mappings), only read known/tracked entries
- Parallel `eth_getStorageAt` calls with batching

**Unverified Contracts:**
- Read slots discovered via historical traces
- Optionally scan slot range 0-1024 for non-zero values
- Store discovered slots for future queries

### 6.2 Transaction Diff

For `(txHash, contractAddress)`:

```
1. debug_traceTransaction(txHash, { tracer: "prestateTracer" })
                    │
                    ▼
2. Extract all SSTORE operations
                    │
                    ▼
3. Filter by target contract address
                    │
                    ▼
4. For each (slot, oldValue, newValue):
   ├── Map slot → variable(s) via layout
   ├── Decode values according to type
   └── Build change record
                    │
                    ▼
5. Return list of decoded changes
```

**Key behavior:**
- When user provides a tx hash, automatically infer the block number
- Show both the **changes** (diff) and the **final state** after the transaction
- For complex transactions with many internal calls, capture all SSTORE ops

### 6.3 Input Modes

The application supports two input modes:

| Input | Behavior |
|-------|----------|
| **Block number** | Read storage state at that block (snapshot view) |
| **Transaction hash** | Show storage changes within that tx + final state |

When a transaction hash is provided:
1. Look up the transaction to get its block number
2. Trace the transaction to extract all storage writes
3. Display changes as before → after diff
4. Allow viewing full storage state at that block

---

## 7. Complex Type Handling

### 7.1 Slot Computation

| Type | Slot Formula |
|------|--------------|
| Simple variable | Declared slot |
| Struct field | `baseSlot + fieldOffset / 32` |
| Static array element | `baseSlot + index * elementSize / 32` |
| Dynamic array length | `baseSlot` |
| Dynamic array element | `keccak256(baseSlot) + index * ceil(elementSize / 32)` |
| Mapping value | `keccak256(abi.encode(key, baseSlot))` |
| Nested mapping | `keccak256(abi.encode(key2, keccak256(abi.encode(key1, baseSlot))))` |

### 7.2 Value Decoding

```python
def decode_slot_value(
    raw: bytes32,
    type_info: StorageType,
    offset: int = 0,
    size: int = 32
) -> DecodedValue:
    """
    Decode a raw slot value to its Solidity representation.

    Args:
        raw: The 32-byte slot value
        type_info: Type information from storage layout
        offset: Byte offset within slot (for packed values)
        size: Number of bytes to read

    Returns:
        DecodedValue with both raw and decoded representations
    """
```

**Supported value types:**

| Solidity Type | Decoding |
|---------------|----------|
| `bool` | `raw[offset] != 0` |
| `address` | `to_checksum_address(raw[offset:offset+20])` |
| `uintN` | Big-endian unsigned integer |
| `intN` | Big-endian signed integer (two's complement) |
| `bytesN` | Raw bytes, left-aligned |
| `bytes` | Length at slot, data at `keccak256(slot)` |
| `string` | Same as `bytes`, UTF-8 decoded |
| `enum` | Uint, with label from type definition |

### 7.3 Mapping Key Tracking

Since mapping keys cannot be enumerated from storage:

1. **From traces:** Extract keys from SSTORE operations
2. **From events:** Parse relevant event logs for key values
3. **From user input:** Allow manual key entry in UI
4. **Popular keys:** Pre-populate common keys (e.g., known whale addresses)

Store discovered mapping keys: `(chainId, contract, slot, key) → firstSeenBlock`

---

## 8. Unverified Contracts

### 8.1 Slot Discovery

Track slots via multiple sources:
- SSTORE operations from transaction traces
- Non-zero values from slot scans
- User-added manual slots

### 8.2 Display Mode

For unverified contracts, show "raw slot view":

| Column | Content |
|--------|---------|
| Slot | Hex slot index |
| Raw Value | bytes32 hex |
| Interpretations | Dropdown: address / uint256 / int256 / bytes32 / bool |

### 8.3 Heuristic Type Detection

Apply simple heuristics (not guaranteed):

| Heuristic | Suggested Type |
|-----------|----------------|
| Top 12 bytes zero, low 20 bytes non-zero | `address` |
| Only byte 31 is 0x00 or 0x01 | `bool` |
| Fits in uint64 range | `uint64` (show as decimal) |
| Otherwise | `bytes32` |

---

## 9. Caching & Performance

### 9.1 Cache Layers

| Data | Cache Location | TTL |
|------|----------------|-----|
| Contract metadata | PostgreSQL | Permanent |
| Storage layouts | PostgreSQL | Permanent |
| Verification status | PostgreSQL | 24 hours |
| Slot values (historical) | PostgreSQL | Permanent |
| Slot values (recent) | Redis | 1 minute |
| Transaction diffs | PostgreSQL | Permanent |
| Popular contract data | Redis | 5 minutes |

### 9.2 Query Limits

| Limit | Value | Behavior if Exceeded |
|-------|-------|---------------------|
| Request timeout | 15 seconds | Return partial + warning |
| Slots per contract | 10,000 | Paginate |
| Trace complexity | 10,000 SSTORE ops | Truncate + warning |

### 9.3 Performance Optimizations

1. **Batch RPC calls:** Group `eth_getStorageAt` calls
2. **Parallel requests:** Use `asyncio.gather` for independent calls
3. **Connection pooling:** Reuse RPC connections
4. **Incremental loading:** Stream large results to frontend
5. **Background refresh:** Pre-warm cache for popular contracts

---

## 10. UI/UX Design

### 10.1 Design Philosophy

**Core Principles:**

- **Minimalist** - Every element earns its place; no decorative clutter
- **Information-dense** - Show data efficiently without overwhelming
- **Hierarchical** - Clear visual hierarchy guides the eye
- **Responsive** - Works on desktop; tablet acceptable; mobile deprioritized

**Visual Language:**

| Element | Style |
|---------|-------|
| Background | Pure white (`#FFFFFF`) or very light gray (`#FAFAFA`) |
| Text | Near-black (`#1A1A1A`) for primary, gray (`#6B7280`) for secondary |
| Accents | Single accent color for interactive elements (subtle blue `#3B82F6`) |
| Borders | Light gray (`#E5E7EB`), 1px, used sparingly |
| Typography | System font stack, monospace for addresses/hashes/values |
| Spacing | Generous whitespace, consistent 4px/8px grid |

### 10.2 Page Structure

#### Home / Search

```
┌────────────────────────────────────────────────────────────────────┐
│  StorageScan                                          [chain ▼]   │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│         ┌──────────────────────────────────────────────┐          │
│         │  🔍  Contract Address or ENS Name            │          │
│         └──────────────────────────────────────────────┘          │
│                                                                    │
│         ┌──────────────────────────────────────────────┐          │
│         │  Block or Transaction Hash (optional)        │          │
│         └──────────────────────────────────────────────┘          │
│                                                                    │
│                        [ Analyze ]                                 │
│                                                                    │
│  ─────────────────────────────────────────────────────────────    │
│                                                                    │
│  Recent Searches                                                   │
│  • 0xA0b8...3c4d  USDC  (Ethereum)  2 min ago                     │
│  • 0x7a25...8f2e  Uniswap V3 Pool  (Ethereum)  15 min ago         │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

#### Contract Overview

```
┌────────────────────────────────────────────────────────────────────┐
│  StorageScan    [← Back]                              [chain ▼]   │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48                       │
│  USDC • USD Coin                                                   │
│  ✓ Verified on Etherscan                                          │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  Proxy: EIP-1967 Transparent                                │  │
│  │  Implementation: 0x43506...8f2a                             │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  [Storage Layout]    [Changes]    [Raw Slots]                     │
│  ═══════════════                                                  │
│                                                                    │
│  ...content based on selected tab...                              │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

#### Storage Layout View

```
┌────────────────────────────────────────────────────────────────────┐
│  STORAGE LAYOUT                           Block: [19234567 ▼]     │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ● Contract Root (Slot 0)                                         │
│  │                                                                │
│  ├─● owner (address) - Slot 0, Offset 0                           │
│  │    └ 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48               │
│  │                                                                │
│  ├─● paused (bool) - Slot 0, Offset 20                            │
│  │    └ false                                                     │
│  │                                                                │
│  ├─● balances (mapping(address => uint256)) - Slot 1              │
│  │  │                                                             │
│  │  ├─● balances[0x5678...eff2] - Slot keccak256(...)            │
│  │  │    └ 1,234,567.89 USDC                                      │
│  │  │                                                             │
│  │  └─● [+ Add Key]                                               │
│  │                                                                │
│  ├─● totalSupply (uint256) - Slot 2                               │
│  │    └ 24,567,891,234.56 USDC                                    │
│  │                                                                │
│  └─● config (struct Config) - Slot 3                              │
│     │                                                             │
│     ├─● config.fee (uint16) - Slot 3, Offset 0                    │
│     │    └ 30 (0.3%)                                              │
│     │                                                             │
│     └─● config.isActive (bool) - Slot 3, Offset 2                 │
│          └ true                                                   │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

#### Transaction Changes View

*Shown when user provides a transaction hash*

```
┌────────────────────────────────────────────────────────────────────┐
│  STORAGE CHANGES IN TRANSACTION                     [Show HEX ○]  │
│  0xab12...ef56                                                     │
│  Block 19,234,567                                                  │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  3 slots modified                                                  │
│                                                                    │
│  ┌─────────────────────┬─────────────────┬─────────────────────┐  │
│  │  Variable           │  Before         │  After              │  │
│  ├─────────────────────┼─────────────────┼─────────────────────┤  │
│  │  owner              │  0xProto...sig  │  0xAtta...ker       │  │
│  │  (address)          │                 │                     │  │
│  ├─────────────────────┼─────────────────┼─────────────────────┤  │
│  │  balances[0x5678..] │  0              │  5,000,000 USDC     │  │
│  │  (uint256)          │                 │                     │  │
│  ├─────────────────────┼─────────────────┼─────────────────────┤  │
│  │  _paused            │  false          │  true               │  │
│  │  (bool)             │                 │                     │  │
│  └─────────────────────┴─────────────────┴─────────────────────┘  │
│                                                                    │
│  ─────────────────────────────────────────────────────────────    │
│                                                                    │
│  [View Full Storage at Block 19,234,567 →]                        │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

### 10.3 Component Specifications

#### Storage Tree Component

- **Expand/collapse:** Click node to toggle children
- **Selection:** Click value to select slot (shows in Changes panel)
- **Hover:** Show full value in tooltip
- **Icons:** Minimal, monochrome icons for type indication
- **Indentation:** 24px per level

#### Transaction Diff Component

- **Sorting:** Click column headers to sort by variable name or change magnitude
- **Value display:** Toggle between decoded and hex via global toggle
- **Highlighting:** Visual diff highlighting (red for removed value, green for new)
- **Links:** Click variable name to see it in storage layout tree
- **Empty state:** "No storage changes in this transaction"

#### Value Display

| Type | Display Format |
|------|----------------|
| `address` | `0xA0b8...3c4d` (truncated middle, full on hover) |
| `uint256` (small) | Decimal with commas: `1,234,567` |
| `uint256` (large) | Scientific or with unit: `1.23M` / `1.23 ETH` |
| `bool` | `true` / `false` |
| `bytes32` | `0xab12...ef56` (truncated) |
| `string` | Quoted: `"Hello World"` |

### 10.4 Interactions

| Action | Behavior |
|--------|----------|
| Search submit | Navigate to contract page, show loading state |
| Tree node click | Expand/collapse children |
| Tree value click | Select slot, highlight in layout |
| Block input change | Refresh storage values for new block |
| Hex toggle | Switch all values between decoded/hex |
| Tx hash click | Open in block explorer (new tab) |

### 10.5 Loading & Error States

**Loading:**
- Skeleton placeholders matching content shape
- Subtle pulse animation
- Progressive loading (show partial data as available)

**Errors:**
- Inline error messages, not modal dialogs
- Clear error description with retry action
- Graceful degradation (show what we can)

**Empty States:**
- Helpful message explaining why empty
- Suggested action if applicable

---

## 11. Data Models

### 11.1 Database Schema

```sql
-- Contracts table
CREATE TABLE contracts (
    id SERIAL PRIMARY KEY,
    chain_id INTEGER NOT NULL,
    address VARCHAR(100) NOT NULL,
    name VARCHAR(200),
    is_proxy BOOLEAN DEFAULT FALSE,
    proxy_type VARCHAR(50),
    implementation_address VARCHAR(100),
    is_verified BOOLEAN DEFAULT FALSE,
    verification_source VARCHAR(50),  -- 'sourcify', 'etherscan'
    compiler_version VARCHAR(50),
    code_hash VARCHAR(100),
    storage_layout JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chain_id, address)
);

-- Discovered slots (for unverified contracts)
CREATE TABLE discovered_slots (
    id SERIAL PRIMARY KEY,
    chain_id INTEGER NOT NULL,
    contract_address VARCHAR(100) NOT NULL,
    slot VARCHAR(100) NOT NULL,
    first_seen_block BIGINT,
    first_seen_tx VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chain_id, contract_address, slot)
);

-- Mapping keys (for tracking known mapping keys)
CREATE TABLE mapping_keys (
    id SERIAL PRIMARY KEY,
    chain_id INTEGER NOT NULL,
    contract_address VARCHAR(100) NOT NULL,
    base_slot VARCHAR(100) NOT NULL,
    key_value VARCHAR(200) NOT NULL,
    key_type VARCHAR(50),
    first_seen_block BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chain_id, contract_address, base_slot, key_value)
);

-- Cached slot values
CREATE TABLE slot_values (
    id SERIAL PRIMARY KEY,
    chain_id INTEGER NOT NULL,
    contract_address VARCHAR(100) NOT NULL,
    slot VARCHAR(100) NOT NULL,
    block_number BIGINT NOT NULL,
    value VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chain_id, contract_address, slot, block_number)
);

-- Transaction diffs
CREATE TABLE tx_diffs (
    id SERIAL PRIMARY KEY,
    chain_id INTEGER NOT NULL,
    contract_address VARCHAR(100) NOT NULL,
    tx_hash VARCHAR(100) NOT NULL,
    block_number BIGINT NOT NULL,
    changes JSONB NOT NULL,  -- Array of {slot, oldValue, newValue}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chain_id, contract_address, tx_hash)
);

-- Indexes
CREATE INDEX idx_contracts_chain_address ON contracts(chain_id, address);
CREATE INDEX idx_slot_values_lookup ON slot_values(chain_id, contract_address, slot, block_number);
CREATE INDEX idx_tx_diffs_contract ON tx_diffs(chain_id, contract_address, block_number);
```

### 11.2 API Response Models

```python
# Contract info response
class ContractInfo(BaseModel):
    chain_id: int
    address: str
    name: Optional[str]
    is_proxy: bool
    proxy_type: Optional[str]
    implementation_address: Optional[str]
    is_verified: bool
    verification_source: Optional[str]
    compiler_version: Optional[str]

# Storage layout response
class StorageLayoutResponse(BaseModel):
    contract: ContractInfo
    block_number: int
    variables: List[StorageVariableWithValue]
    types: Dict[str, StorageType]

# Storage variable with current value
class StorageVariableWithValue(BaseModel):
    name: str
    slot: str
    offset: int
    size: int
    type_label: str
    raw_value: str
    decoded_value: Any
    children: Optional[List[StorageVariableWithValue]]

# Change record
class StorageChange(BaseModel):
    slot: str
    variable_path: Optional[str]  # e.g., "balances[0x...]"
    old_raw: str
    new_raw: str
    old_decoded: Optional[Any]
    new_decoded: Optional[Any]

# Transaction diff response
class TxDiffResponse(BaseModel):
    chain_id: int
    contract_address: str
    tx_hash: str
    block_number: int
    changes: List[StorageChange]
```

---

## 12. Future Features

*These features are documented for future consideration but are **not** part of the v1 scope.*

### 12.1 REST API

Endpoints for programmatic access:

```
GET  /api/v1/contracts/{chainId}/{address}
GET  /api/v1/contracts/{chainId}/{address}/layout?block={blockNumber}
GET  /api/v1/contracts/{chainId}/{address}/tx/{txHash}/diff
GET  /api/v1/contracts/{chainId}/{address}/blocks/{blockNumber}/diff
GET  /api/v1/contracts/{chainId}/{address}/range?from={block}&to={block}&mode={net|sampled}
```

### 12.2 CLI Tool

```bash
# Get contract info
storagescan info --chain mainnet --address 0x...

# View storage layout
storagescan layout --chain mainnet --address 0x... --block latest

# View transaction diff
storagescan diff --chain mainnet --address 0x... --tx 0x...

# View block changes
storagescan changes --chain mainnet --address 0x... --from 19234000 --to 19234567
```

### 12.3 Block Range Queries

For analyzing changes across multiple blocks:
- Net change between two blocks
- Sampled time series
- Full trace mode for small ranges

### 12.4 Additional Features

- **Multi-chain support** - Automatic chain detection from address
- **ENS resolution** - Support .eth names in search
- **Export functionality** - CSV/JSON export of changes
- **Notifications** - Watch a slot and get notified on changes
- **Comparison mode** - Side-by-side diff of two blocks
- **Shareable links** - Deep links to specific contract states

---

## Appendix A: Supported Chains (v1)

| Chain | Chain ID | RPC Requirements |
|-------|----------|------------------|
| Ethereum Mainnet | 1 | Full node with `debug_traceTransaction` |
| Sepolia | 11155111 | Full node with `debug_traceTransaction` |

*Additional chains can be added when tracing-capable RPC endpoints are available.*

---

## Appendix B: References

- [Solidity Storage Layout](https://docs.soliditylang.org/en/latest/internals/layout_in_storage.html)
- [EIP-1967: Standard Proxy Storage Slots](https://eips.ethereum.org/EIPS/eip-1967)
- [Sourcify API](https://docs.sourcify.dev/)
- [web3.py Documentation](https://web3py.readthedocs.io/)
