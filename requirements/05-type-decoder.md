# Type Decoder Service

## Overview

The Type Decoder converts raw 32-byte storage slot values into human-readable Solidity types. It handles all primitive types and packed values. MVP constraints: when layout is unavailable (unverified), default to hex-only and optionally apply simple heuristics that can be disabled.

## Implementation Status: ✅ Complete

### Key Implementation Decisions

1. **Heuristic Decoding Always Applied**: When no layout is available, `decode_heuristic()` is automatically called to provide meaningful display values. Heuristics detect addresses (12 leading zero bytes), booleans (only last byte 0 or 1), and small integers.

2. **DecodedValue Structure**: Returns both `decoded` (Python value) and `display` (formatted string) fields, allowing UI flexibility in presentation.

3. **Packed Value Support**: Correctly handles byte offsets for packed storage variables (multiple values in one slot).

## Location

```
backend/app/services/decoder.py
backend/app/utils/solidity.py
```

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `eth_abi` | ABI encoding/decoding helpers |
| `web3.py` | Address checksumming |
| Layout Parser | StorageType definitions |

## Public Interface

```python
@dataclass
class DecodedValue:
    """A decoded storage value."""
    raw: str                     # Original hex value
    decoded: Any                 # Decoded Python value
    type_label: str              # Solidity type label
    display: str                 # Human-readable display string


class TypeDecoder:
    """Decodes raw storage values to Solidity types."""

    def decode(
        self,
        raw_value: bytes,
        type_info: StorageType,
        offset: int = 0
    ) -> DecodedValue:
        """
        Decode a raw slot value using type information.

        Args:
            raw_value: 32-byte slot value
            type_info: Type information from storage layout
            offset: Byte offset within slot (for packed values)

        Returns:
            DecodedValue with decoded and display representations
        """
        pass

    def decode_heuristic(
        self,
        raw_value: bytes
    ) -> DecodedValue:
        """
        Optional heuristic decode for unverified contracts; can be disabled.

        Attempts to guess the most likely type based on value patterns.
        """
        pass

    def format_value(
        self,
        value: Any,
        type_label: str,
        options: Optional[FormatOptions] = None
    ) -> str:
        """
        Format a decoded value for display.

        Handles large numbers, addresses, booleans, etc.
        """
        pass


@dataclass
class FormatOptions:
    """Options for value formatting."""
    truncate_addresses: bool = True      # 0xAbCd...EfGh
    use_units: bool = True               # Show as "1.5 ETH" vs "1500000000000000000"
    decimal_places: int = 6              # For decimal formatting
    max_string_length: int = 100         # Truncate long strings
```

## Implementation Details

### 1. Core Decoding Logic

```python
# backend/app/services/decoder.py

class TypeDecoder:
    """
    Decodes raw storage slot values to typed Python values.

    Storage layout rules:
    - Values are right-aligned (low-order bytes) within slots
    - Offset specifies byte position from right (0 = rightmost)
    - Packed values share a slot, each at different offsets
    """

    def decode(
        self,
        raw_value: bytes,
        type_info: StorageType,
        offset: int = 0
    ) -> DecodedValue:
        """Decode with type information."""
        # Ensure 32 bytes
        if len(raw_value) < 32:
            raw_value = raw_value.rjust(32, b'\x00')

        # Extract relevant bytes based on offset and size
        size = type_info.num_bytes or 32
        # Storage is right-aligned, so offset from the right
        start = 32 - offset - size
        end = 32 - offset
        relevant_bytes = raw_value[start:end]

        # Decode based on type kind
        decoded = self._decode_by_type(relevant_bytes, type_info)

        # Format for display
        display = self.format_value(decoded, type_info.label)

        return DecodedValue(
            raw="0x" + raw_value.hex(),
            decoded=decoded,
            type_label=type_info.label,
            display=display
        )

    def _decode_by_type(self, data: bytes, type_info: StorageType) -> Any:
        """Decode bytes based on type."""
        label = type_info.label.lower()
        base = type_info.base_type or label

        # Boolean
        if base in ("bool", "t_bool"):
            return data[-1] != 0 if data else False

        # Address
        if base in ("address", "t_address") or "address" in label:
            return self._decode_address(data)

        # Unsigned integers
        if base.startswith("uint") or base.startswith("t_uint"):
            return self._decode_uint(data)

        # Signed integers
        if base.startswith("int") or base.startswith("t_int"):
            bits = self._extract_bits(base) or 256
            return self._decode_int(data, bits)

        # Fixed-size bytes
        if base.startswith("bytes") and base != "bytes":
            return self._decode_bytesN(data, type_info.num_bytes or len(data))

        # Enum (stored as uint)
        if "enum" in label.lower():
            return self._decode_uint(data)

        # Contract type (stored as address)
        if type_info.kind == "contract":
            return self._decode_address(data)

        # Default to hex
        return "0x" + data.hex()
```

### 2. Primitive Type Decoders

```python
def _decode_address(self, data: bytes) -> str:
    """
    Decode an address from storage.

    Addresses are 20 bytes, stored right-aligned in storage.
    """
    # Take last 20 bytes
    addr_bytes = data[-20:] if len(data) >= 20 else data.rjust(20, b'\x00')

    # Convert to checksum address
    try:
        return Web3.to_checksum_address(addr_bytes)
    except Exception:
        return "0x" + addr_bytes.hex()


def _decode_uint(self, data: bytes) -> int:
    """Decode unsigned integer (big-endian)."""
    return int.from_bytes(data, "big")


def _decode_int(self, data: bytes, bits: int) -> int:
    """
    Decode signed integer (two's complement).

    Args:
        data: Raw bytes
        bits: Bit width (8, 16, 32, ..., 256)
    """
    value = int.from_bytes(data, "big")
    # Check sign bit
    sign_bit = 1 << (bits - 1)
    if value & sign_bit:
        # Negative: compute two's complement
        value = value - (1 << bits)
    return value


def _decode_bytesN(self, data: bytes, n: int) -> str:
    """
    Decode fixed-size bytes (bytes1 through bytes32).

    Fixed bytes are left-aligned in storage.
    """
    # Take first n bytes
    relevant = data[:n]
    return "0x" + relevant.hex()


def _extract_bits(self, type_name: str) -> Optional[int]:
    """Extract bit width from type name like 'uint256' or 't_uint128'."""
    import re
    match = re.search(r'(\d+)', type_name)
    if match:
        return int(match.group(1))
    return None
```

### 3. Dynamic Type Handling

```python
def decode_dynamic_bytes(
    self,
    length_slot_value: bytes,
    data_slot_values: List[bytes]
) -> bytes:
    """
    Decode dynamic bytes/string.

    Layout:
    - Length (in bytes) stored at base slot
    - If length < 32: data stored in same slot (length * 2 + 1 in last byte)
    - If length >= 32: data at keccak256(slot), spanning multiple slots

    This requires multiple slot reads, handled by StorageReader.
    """
    # Check if short encoding (data in same slot)
    last_byte = length_slot_value[-1]
    if last_byte & 1 == 0:
        # Short encoding: length = last_byte / 2
        length = last_byte // 2
        # Data is in the first `length` bytes
        return length_slot_value[:length]
    else:
        # Long encoding: length = (value - 1) / 2
        full_value = int.from_bytes(length_slot_value, "big")
        length = (full_value - 1) // 2

        # Concatenate data slots
        data = b''.join(data_slot_values)
        return data[:length]


def decode_string(
    self,
    length_slot_value: bytes,
    data_slot_values: List[bytes]
) -> str:
    """Decode dynamic string (same as bytes, then UTF-8 decode)."""
    raw_bytes = self.decode_dynamic_bytes(length_slot_value, data_slot_values)
    try:
        return raw_bytes.decode('utf-8')
    except UnicodeDecodeError:
        return "0x" + raw_bytes.hex()  # Fall back to hex
```

### 4. Heuristic Decoding

```python
def decode_heuristic(self, raw_value: bytes) -> DecodedValue:
    """
    Attempt to decode without type information.

    Heuristics (in order of checking):
    1. All zeros -> probably uninitialized (show as 0)
    2. Looks like address (12 leading zeros, 20 bytes of data)
    3. Looks like boolean (only last byte is 0 or 1)
    4. Small integer (fits in reasonable range)
    5. Default to bytes32 hex
    """
    if len(raw_value) < 32:
        raw_value = raw_value.rjust(32, b'\x00')

    # Check for zero
    if raw_value == b'\x00' * 32:
        return DecodedValue(
            raw="0x" + raw_value.hex(),
            decoded=0,
            type_label="uint256 (heuristic)",
            display="0"
        )

    # Check for address pattern
    if self._looks_like_address(raw_value):
        addr = self._decode_address(raw_value)
        return DecodedValue(
            raw="0x" + raw_value.hex(),
            decoded=addr,
            type_label="address (heuristic)",
            display=self._format_address(addr)
        )

    # Check for boolean pattern
    if self._looks_like_bool(raw_value):
        value = raw_value[-1] != 0
        return DecodedValue(
            raw="0x" + raw_value.hex(),
            decoded=value,
            type_label="bool (heuristic)",
            display=str(value).lower()
        )

    # Check for small integer
    uint_value = int.from_bytes(raw_value, "big")
    if uint_value < 10**18:  # Less than 1 ETH worth
        return DecodedValue(
            raw="0x" + raw_value.hex(),
            decoded=uint_value,
            type_label="uint256 (heuristic)",
            display=f"{uint_value:,}"
        )

    # Default to bytes32
    return DecodedValue(
        raw="0x" + raw_value.hex(),
        decoded="0x" + raw_value.hex(),
        type_label="bytes32",
        display="0x" + raw_value.hex()
    )


def _looks_like_address(self, data: bytes) -> bool:
    """Check if value looks like an address."""
    # First 12 bytes should be zero
    if data[:12] != b'\x00' * 12:
        return False
    # Last 20 bytes should be non-zero (not all zeros)
    if data[12:] == b'\x00' * 20:
        return False
    return True


def _looks_like_bool(self, data: bytes) -> bool:
    """Check if value looks like a boolean."""
    # First 31 bytes should be zero
    if data[:31] != b'\x00' * 31:
        return False
    # Last byte should be 0 or 1
    return data[-1] in (0, 1)
```

### 5. Value Formatting

```python
def format_value(
    self,
    value: Any,
    type_label: str,
    options: Optional[FormatOptions] = None
) -> str:
    """
    Format a decoded value for human-readable display.
    """
    options = options or FormatOptions()

    # Boolean
    if isinstance(value, bool):
        return str(value).lower()

    # Address
    if isinstance(value, str) and value.startswith("0x") and len(value) == 42:
        if options.truncate_addresses:
            return self._format_address(value)
        return value

    # Integer
    if isinstance(value, int):
        return self._format_integer(value, type_label, options)

    # Bytes
    if isinstance(value, (bytes, str)) and (
        isinstance(value, bytes) or value.startswith("0x")
    ):
        hex_val = value.hex() if isinstance(value, bytes) else value
        if len(hex_val) > 20:
            return hex_val[:10] + "..." + hex_val[-8:]
        return hex_val

    # String
    if isinstance(value, str):
        if len(value) > options.max_string_length:
            return f'"{value[:options.max_string_length]}..."'
        return f'"{value}"'

    # Default
    return str(value)


def _format_address(self, address: str) -> str:
    """Format address with truncation: 0xAbCd...EfGh"""
    if len(address) != 42:
        return address
    return f"{address[:6]}...{address[-4:]}"


def _format_integer(
    self,
    value: int,
    type_label: str,
    options: FormatOptions
) -> str:
    """Format integer with appropriate units."""
    # Check for common token decimals
    if options.use_units:
        # 18 decimals (ETH, most ERC20)
        if value >= 10**15 and "uint256" in type_label:
            eth_value = value / 10**18
            if eth_value == int(eth_value):
                return f"{int(eth_value):,}"
            return f"{eth_value:,.{options.decimal_places}f}"

        # 6 decimals (USDC, USDT)
        if value >= 10**4 and value < 10**15:
            possible_6dec = value / 10**6
            if possible_6dec < 10**12:  # Reasonable token amount
                if possible_6dec == int(possible_6dec):
                    return f"{int(possible_6dec):,}"
                return f"{possible_6dec:,.{min(options.decimal_places, 2)}f}"

    # Large numbers with abbreviation
    if value >= 10**12:
        return f"{value/10**12:.2f}T"
    if value >= 10**9:
        return f"{value/10**9:.2f}B"
    if value >= 10**6:
        return f"{value/10**6:.2f}M"
    if value >= 10**3:
        return f"{value:,}"

    return str(value)
```

### 6. Struct and Array Decoding

```python
def decode_struct(
    self,
    slot_values: Dict[int, bytes],
    struct_type: StorageType,
    base_slot: int
) -> Dict[str, DecodedValue]:
    """
    Decode a struct from multiple slot values.

    Args:
        slot_values: Dict of slot -> raw value
        struct_type: Struct type definition with members
        base_slot: Starting slot of struct

    Returns:
        Dict of field_name -> DecodedValue
    """
    if not struct_type.members:
        return {}

    result = {}
    for member in struct_type.members:
        # Compute actual slot for this member
        member_slot = base_slot + member.slot
        raw = slot_values.get(member_slot, b'\x00' * 32)

        # Get member type
        # Note: member.type_id needs to be resolved from layout.types
        # This is a simplified version
        decoded = self.decode(raw, member.type_info, member.offset)
        result[member.name] = decoded

    return result


def decode_array_length(self, slot_value: bytes) -> int:
    """Decode dynamic array length from its base slot."""
    return int.from_bytes(slot_value, "big")
```

## Supported Types Reference

| Solidity Type | Decoding Method | Storage Layout |
|---------------|-----------------|----------------|
| `bool` | Last byte != 0 | 1 byte, right-aligned |
| `address` | Last 20 bytes, checksum | 20 bytes, right-aligned |
| `uint8`-`uint256` | Big-endian unsigned | N/8 bytes, right-aligned |
| `int8`-`int256` | Two's complement | N/8 bytes, right-aligned |
| `bytes1`-`bytes32` | First N bytes | N bytes, left-aligned |
| `bytes` (dynamic) | Length + data slots | Special encoding |
| `string` | Same as bytes, UTF-8 | Special encoding |
| `enum` | As uint | Size depends on variant count |
| `contract` | As address | 20 bytes, right-aligned |

## Error Handling

```python
class DecodeError(Exception):
    """Raised when decoding fails."""
    def __init__(self, type_label: str, reason: str):
        self.type_label = type_label
        self.reason = reason
        super().__init__(f"Failed to decode {type_label}: {reason}")
```

## Heuristic Decoding (optional, unverified)
- Address-like: top 12 bytes zero, low 20 bytes non-zero.
- Bool-like: only last byte is 0x00/0x01.
- Small uint: value fits in uint64.
- Otherwise default to bytes32. Always label results as heuristic and allow disabling.

## Testing Strategy

### Unit Tests

1. **Primitive types**
   - Decode uint8 through uint256
   - Decode int8 through int256 (positive and negative)
   - Decode address
   - Decode bool
   - Decode bytes1 through bytes32

2. **Packed values**
   - Multiple values in one slot
   - Correct offset handling

3. **Heuristic decoding**
   - Address detection
   - Boolean detection
   - Small integer detection

4. **Formatting**
   - Address truncation
   - Large number formatting
   - Unit display

### Edge Cases

- Zero values
- Max values (type(uint256).max)
- Negative integers
- Invalid UTF-8 in strings

## Configuration

```python
@dataclass
class DecoderConfig:
    # Formatting defaults
    default_decimal_places: int = 6
    truncate_addresses: bool = True
    show_units: bool = True

    # Heuristic thresholds
    small_int_threshold: int = 10**18
```

## Example Usage

```python
decoder = TypeDecoder(config)

# Decode with type info
uint_type = StorageType(id="t_uint256", label="uint256", kind="value", ...)
result = decoder.decode(
    raw_value=bytes.fromhex("00" * 28 + "00989680"),  # 10,000,000
    type_info=uint_type,
    offset=0
)
print(result.decoded)  # 10000000
print(result.display)  # "10,000,000" or "10M"

# Decode address
addr_type = StorageType(id="t_address", label="address", kind="value", ...)
result = decoder.decode(
    raw_value=bytes.fromhex("00" * 12 + "a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"),
    type_info=addr_type
)
print(result.display)  # "0xA0b8...eB48"

# Heuristic decode (no type info)
result = decoder.decode_heuristic(
    bytes.fromhex("00" * 12 + "a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48")
)
print(result.type_label)  # "address (heuristic)"
```
