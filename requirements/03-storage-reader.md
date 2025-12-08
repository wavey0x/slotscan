# Storage Reader Service

## Overview

The Storage Reader fetches storage slot values at a specific block. It handles slot computation for complex types (mappings, arrays, structs), batches RPC calls for efficiency, and works with both verified (layout-aware) and unverified (raw scan) contracts.
MVP constraints: Postgres is the only cache, all work is in-request, unverified scans are shallow (0–256) plus current-trace slots, and degraded/partial responses are allowed.

## Implementation Status: ✅ Complete

### Key Implementation Decisions

1. **Slot Computation Utilities**: `compute_mapping_slot()` in `app/utils/slots.py` handles address, uint256, and bytes32 key types for mapping slot calculation.

2. **Batch RPC with Concurrency Limiting**: Uses asyncio semaphore to limit concurrent RPC calls while maximizing throughput.

3. **Heuristic Decoding for Unverified**: When no layout is available, heuristic decoding attempts to identify addresses, booleans, and small integers in raw slot values.

## Location

```
backend/app/services/storage.py
backend/app/utils/slots.py
```

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `web3.py` | RPC calls (`eth_getStorageAt`) |
| Layout Parser | StorageLayout for verified contracts |
| Type Decoder | Decode raw values |
| Database Layer | Cache snapshots (Postgres JSONB) |

## Public Interface

```python
@dataclass
class SlotValue:
    """A single storage slot with its value."""
    slot: str                      # Hex slot index
    raw_value: str                 # Hex bytes32 value
    variable: Optional[StorageVariable]  # Matched variable (if layout available)
    decoded_value: Optional[Any]   # Decoded value (if decodable)
    variable_path: Optional[str]   # e.g., "balances[0x...]" for mappings


@dataclass
class StorageSnapshot:
    """Complete storage state at a block."""
    chain_id: int
    address: str
    block_number: int
    slots: List[SlotValue]
    is_complete: bool              # False if truncated due to limits
    layout: Optional[StorageLayout]  # Layout used (if verified)


class StorageReader:
    """Reads storage state at a block."""

    async def read_at_block(
        self,
        chain_id: int,
        address: str,
        block_number: int,
        layout: Optional[StorageLayout] = None,
        include_mapping_keys: Optional[Dict[int, List[Any]]] = None
    ) -> StorageSnapshot:
        """
        Read all storage at a block.

        For verified contracts (layout provided):
            - Reads all static slots from layout
            - Reads mapping entries for provided keys

        For unverified contracts (no layout):
            - Scans slots 0-256 for non-zero values
            - Adds slots touched in the current request's trace (if provided)

        Args:
            chain_id: Chain ID
            address: Contract address
            block_number: Block to read at
            layout: Storage layout (if verified)
            include_mapping_keys: Dict of base_slot -> [keys] to read

        Returns:
            StorageSnapshot with all slot values
        """
        pass

    async def read_slot(
        self,
        chain_id: int,
        address: str,
        slot: int,
        block_number: int
    ) -> str:
        """Read a single slot value (hex string)."""
        pass

    async def read_slots_batch(
        self,
        chain_id: int,
        address: str,
        slots: List[int],
        block_number: int
    ) -> Dict[int, str]:
        """Read multiple slots in parallel, returns slot -> value dict."""
        pass

    def compute_mapping_slot(
        self,
        base_slot: int,
        key: Any,
        key_type: str
    ) -> int:
        """Compute the slot for a mapping entry."""
        pass

    def compute_array_slot(
        self,
        base_slot: int,
        index: int,
        element_size: int
    ) -> int:
        """Compute the slot for an array element."""
        pass
```

## Implementation Details

### 1. Slot Computation Utilities

```python
# backend/app/utils/slots.py

from web3 import Web3
from eth_abi import encode

def compute_mapping_slot(base_slot: int, key: Any, key_type: str) -> int:
    """
    Compute storage slot for a mapping entry.

    Formula: keccak256(abi.encode(key, base_slot))

    Args:
        base_slot: The slot where the mapping is declared
        key: The mapping key value
        key_type: Solidity type of key ("address", "uint256", etc.)

    Returns:
        Integer slot number
    """
    # Encode the key based on type
    if key_type in ("address", "t_address"):
        if isinstance(key, str):
            key = Web3.to_checksum_address(key)
        encoded_key = encode(["address"], [key])
    elif key_type.startswith("uint") or key_type.startswith("t_uint"):
        encoded_key = encode(["uint256"], [int(key)])
    elif key_type.startswith("int") or key_type.startswith("t_int"):
        encoded_key = encode(["int256"], [int(key)])
    elif key_type.startswith("bytes") or key_type.startswith("t_bytes"):
        if key_type in ("bytes32", "t_bytes32"):
            encoded_key = encode(["bytes32"], [key])
        else:
            encoded_key = encode(["bytes"], [key])
    else:
        # Default to bytes32
        encoded_key = encode(["bytes32"], [key])

    # Encode the slot (always uint256)
    encoded_slot = encode(["uint256"], [base_slot])

    # Concatenate key + slot and hash
    combined = encoded_key + encoded_slot
    slot_hash = Web3.keccak(combined)

    return int.from_bytes(slot_hash, "big")


def compute_nested_mapping_slot(
    base_slot: int,
    keys: List[Tuple[Any, str]]
) -> int:
    """
    Compute slot for nested mapping: mapping(K1 => mapping(K2 => V))

    Args:
        base_slot: Base slot of outermost mapping
        keys: List of (key_value, key_type) tuples, outer to inner

    Returns:
        Final slot number
    """
    current_slot = base_slot
    for key, key_type in keys:
        current_slot = compute_mapping_slot(current_slot, key, key_type)
    return current_slot


def compute_dynamic_array_slot(base_slot: int, index: int, element_slots: int = 1) -> int:
    """
    Compute storage slot for a dynamic array element.

    Array length is stored at base_slot.
    Elements start at keccak256(base_slot).

    Args:
        base_slot: The slot where array length is stored
        index: Array index (0-based)
        element_slots: Number of slots per element (1 for uint256, more for structs)

    Returns:
        Slot number for the element
    """
    # Hash the base slot to get start of array data
    encoded_slot = encode(["uint256"], [base_slot])
    data_start = int.from_bytes(Web3.keccak(encoded_slot), "big")

    # Element slot = data_start + index * element_slots
    return data_start + (index * element_slots)


def compute_static_array_slot(base_slot: int, index: int, element_slots: int = 1) -> int:
    """
    Compute storage slot for a static array element.

    Static arrays store elements contiguously from base_slot.

    Args:
        base_slot: The starting slot of the array
        index: Array index (0-based)
        element_slots: Number of slots per element

    Returns:
        Slot number for the element
    """
    return base_slot + (index * element_slots)


def compute_struct_field_slot(
    base_slot: int,
    field_offset: int,
    field_slot_offset: int = 0
) -> Tuple[int, int]:
    """
    Compute slot and byte offset for a struct field.

    Args:
        base_slot: Starting slot of the struct
        field_offset: Byte offset of field within struct
        field_slot_offset: Additional slot offset (for fields > 32 bytes into struct)

    Returns:
        (slot_number, byte_offset_within_slot)
    """
    slot = base_slot + (field_offset // 32) + field_slot_offset
    offset = field_offset % 32
    return (slot, offset)
```

### 2. Batch RPC Reading

```python
from asyncio import gather, Semaphore

class StorageReader:
    def __init__(self, web3_provider, config):
        self.web3_provider = web3_provider
        self.config = config
        self._semaphore = Semaphore(config.max_concurrent_rpc)

    async def read_slot(
        self,
        chain_id: int,
        address: str,
        slot: int,
        block_number: int
    ) -> str:
        """Read a single slot."""
        web3 = self.web3_provider.get_web3(chain_id)

        # Convert slot to hex
        slot_hex = hex(slot)

        async with self._semaphore:
            value = await web3.eth.get_storage_at(
                address,
                slot_hex,
                block_identifier=block_number
            )

        return value.hex()

    async def read_slots_batch(
        self,
        chain_id: int,
        address: str,
        slots: List[int],
        block_number: int
    ) -> Dict[int, str]:
        """
        Read multiple slots in parallel.

        Uses semaphore to limit concurrency.
        """
        if not slots:
            return {}

        # Deduplicate slots
        unique_slots = list(set(slots))

        # Create tasks
        tasks = [
            self.read_slot(chain_id, address, slot, block_number)
            for slot in unique_slots
        ]

        # Execute in parallel
        results = await gather(*tasks, return_exceptions=True)

        # Build result dict, handling errors
        slot_values = {}
        for slot, result in zip(unique_slots, results):
            if isinstance(result, Exception):
                # Log error but continue
                slot_values[slot] = "0x" + "00" * 32  # Zero value on error
            else:
                slot_values[slot] = result

        return slot_values
```

### 3. Verified Contract Reading

```python
async def _read_verified_contract(
    self,
    chain_id: int,
    address: str,
    block_number: int,
    layout: StorageLayout,
    mapping_keys: Optional[Dict[int, List[Any]]] = None
) -> List[SlotValue]:
    """
    Read storage for a verified contract using its layout.

    Reads:
    1. All static slots (value types, structs, static arrays)
    2. Mapping entries for provided keys
    3. Dynamic array lengths (but not all elements)
    """
    slots_to_read = []
    slot_to_var = {}  # Track which variable each slot belongs to

    # Collect static slots from layout
    for var in layout.variables:
        var_type = layout.get_type(var.type_id)
        if not var_type:
            continue

        if var_type.encoding in ("inplace", "bytes"):
            # Simple value type - read the slot(s)
            num_slots = max(1, (var_type.num_bytes or 32) // 32)
            for i in range(num_slots):
                slot = var.slot + i
                slots_to_read.append(slot)
                slot_to_var[slot] = (var, i)

        elif var_type.encoding == "dynamic_array":
            # Read array length at base slot
            slots_to_read.append(var.slot)
            slot_to_var[var.slot] = (var, 0)

        elif var_type.encoding == "mapping":
            # Mappings don't have a readable base slot
            # We'll add entries based on provided keys below
            pass

    # Add mapping entries for provided keys
    if mapping_keys:
        for base_slot, keys in mapping_keys.items():
            var = layout.get_variable_by_slot(base_slot)
            if not var:
                continue

            var_type = layout.get_type(var.type_id)
            if not var_type or var_type.encoding != "mapping":
                continue

            key_type = var_type.key_type
            for key in keys:
                computed_slot = compute_mapping_slot(base_slot, key, key_type)
                slots_to_read.append(computed_slot)
                slot_to_var[computed_slot] = (var, key)

    # Batch read all slots
    slot_values = await self.read_slots_batch(
        chain_id, address, slots_to_read, block_number
    )

    # Build SlotValue results
    results = []
    for slot, raw_value in slot_values.items():
        var_info = slot_to_var.get(slot)
        variable = var_info[0] if var_info else None
        extra = var_info[1] if var_info else None

        # Decode value if we have type info
        decoded = None
        variable_path = None

        if variable:
            var_type = layout.get_type(variable.type_id)
            if var_type:
                decoded = self.decoder.decode(
                    bytes.fromhex(raw_value[2:]),
                    var_type,
                    variable.offset
                )

            # Build variable path
            if var_type and var_type.encoding == "mapping" and extra is not None:
                variable_path = f"{variable.name}[{extra}]"
            else:
                variable_path = variable.name

        results.append(SlotValue(
            slot=hex(slot),
            raw_value=raw_value,
            variable=variable,
            decoded_value=decoded,
            variable_path=variable_path
        ))

    return results
```

### 4. Unverified Contract Reading

```python
async def _read_unverified_contract(
    self,
    chain_id: int,
    address: str,
    block_number: int,
    additional_slots: Optional[List[int]] = None
) -> List[SlotValue]:
    """
    Read storage for an unverified contract.

    Strategy:
    1. Scan slots 0-256 for non-zero values
    2. Include any additional slots (e.g., from tx traces)
    """
    # Build slot list: 0-256 + any additional
    slots_to_read = list(range(257))  # 0 through 256

    if additional_slots:
        slots_to_read.extend(additional_slots)
        slots_to_read = list(set(slots_to_read))  # Dedupe

    # Batch read
    slot_values = await self.read_slots_batch(
        chain_id, address, slots_to_read, block_number
    )

    # Filter to non-zero values only
    results = []
    zero_value = "0x" + "00" * 32

    for slot, raw_value in sorted(slot_values.items()):
        if raw_value != zero_value:
            results.append(SlotValue(
                slot=hex(slot),
                raw_value=raw_value,
                variable=None,
                decoded_value=None,
                variable_path=None
            ))

    return results
```

### 5. Main Read Flow

```python
async def read_at_block(
    self,
    chain_id: int,
    address: str,
    block_number: int,
    layout: Optional[StorageLayout] = None,
    include_mapping_keys: Optional[Dict[int, List[Any]]] = None
) -> StorageSnapshot:
    """
    Read complete storage state at a block.
    """
    address = Web3.to_checksum_address(address)

    # Check cache first
    cached = await self.cache.get_snapshot(chain_id, address, block_number)
    if cached:
        return cached

    # Read based on whether we have a layout
    if layout:
        slots = await self._read_verified_contract(
            chain_id, address, block_number, layout, include_mapping_keys
        )
    else:
        slots = await self._read_unverified_contract(
            chain_id, address, block_number
        )

    # Check if we hit limits
    is_complete = len(slots) < self.config.max_slots_per_contract

    snapshot = StorageSnapshot(
        chain_id=chain_id,
        address=address,
        block_number=block_number,
        slots=slots,
        is_complete=is_complete,
        layout=layout
    )

    # Cache the result
    await self.cache.save_snapshot(snapshot)

    return snapshot
```

## Configuration

```python
@dataclass
class StorageReaderConfig:
    # Concurrency limits
    max_concurrent_rpc: int = 20       # Semaphore limit
    max_slots_per_contract: int = 10000  # Pagination limit

    # Unverified contract settings
    unverified_scan_range: int = 256   # Slots to scan (0 to N)

    # Timeouts
    rpc_timeout: float = 5.0           # Per-call timeout
    batch_timeout: float = 30.0        # Total batch timeout
```

## Slot Computation Examples

### Simple Mapping

```solidity
mapping(address => uint256) public balances;  // slot 0
```

To read `balances[0x1234...]`:
```python
slot = compute_mapping_slot(
    base_slot=0,
    key="0x1234...",
    key_type="address"
)
# slot = keccak256(abi.encode(address, 0))
```

### Nested Mapping

```solidity
mapping(address => mapping(address => uint256)) public allowance;  // slot 1
```

To read `allowance[owner][spender]`:
```python
slot = compute_nested_mapping_slot(
    base_slot=1,
    keys=[
        ("0xOwner...", "address"),
        ("0xSpender...", "address")
    ]
)
# slot = keccak256(abi.encode(spender, keccak256(abi.encode(owner, 1))))
```

### Dynamic Array

```solidity
uint256[] public values;  // slot 2
```

To read `values[5]`:
```python
# First, read length at slot 2
length = await reader.read_slot(chain_id, address, 2, block)

# Then compute element slot
element_slot = compute_dynamic_array_slot(base_slot=2, index=5)
# element_slot = keccak256(2) + 5
```

### Struct in Mapping

```solidity
struct Position {
    uint128 amount;    // offset 0, 16 bytes
    uint128 debt;      // offset 16, 16 bytes (packed in same slot)
    uint256 timestamp; // offset 32, next slot
}
mapping(address => Position) public positions;  // slot 3
```

To read `positions[user].timestamp`:
```python
# Compute mapping slot for user
mapping_slot = compute_mapping_slot(3, user_address, "address")

# timestamp is 32 bytes into struct, so next slot
timestamp_slot = mapping_slot + 1
```

## Error Handling

```python
class RPCError(Exception):
    """Raised when RPC call fails."""
    pass


class SlotLimitExceeded(Exception):
    """Raised when too many slots requested."""
    def __init__(self, requested: int, limit: int):
        self.requested = requested
        self.limit = limit
        super().__init__(f"Requested {requested} slots, limit is {limit}")
```

## Testing Strategy

### Unit Tests

1. **Slot computation**
   - Simple mapping slots
   - Nested mapping slots
   - Dynamic array slots
   - Struct field slots

2. **Batch reading**
   - Deduplication
   - Error handling
   - Concurrency limits

### Integration Tests

1. **Real contract reading**
   - Read USDC balances mapping
   - Read ERC20 totalSupply
   - Read struct values

2. **Unverified contract**
   - Scan finds non-zero slots
   - Additional slots included

## Performance Considerations

1. **Batch RPC**: Group reads to minimize round-trips
2. **Semaphore**: Prevent overwhelming RPC node
3. **Caching**: Cache snapshots in Postgres (JSONB) for repeated queries; optional TTL (e.g., 30 minutes)
4. **Degraded mode**: If RPC calls exceed timeout, return partial results with `is_complete=False` instead of failing
5. **Early termination**: Stop if limit exceeded
6. **Zero filtering**: Only return non-zero for unverified

## Example Usage

```python
reader = StorageReader(web3_provider, config, decoder, cache)

# Read verified contract
snapshot = await reader.read_at_block(
    chain_id=1,
    address="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    block_number=19000000,
    layout=usdc_layout,
    include_mapping_keys={
        9: ["0x1234...", "0x5678..."]  # balances mapping at slot 9
    }
)

for slot in snapshot.slots:
    print(f"{slot.variable_path}: {slot.decoded_value}")

# Read unverified contract
snapshot = await reader.read_at_block(
    chain_id=1,
    address="0xUnverified...",
    block_number=19000000
)

for slot in snapshot.slots:
    print(f"Slot {slot.slot}: {slot.raw_value}")
```
