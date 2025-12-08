"""Type decoder for converting raw storage values to Solidity types."""

import re
from typing import Any, Optional

from web3 import Web3

from app.models.domain import DecodedValue, StorageType, StorageVariable


class TypeDecoder:
    """Decodes raw storage slot values to typed Python values."""

    def decode(
        self,
        raw_value: bytes,
        type_info: StorageType,
        offset: int = 0,
    ) -> DecodedValue:
        """
        Decode a raw slot value using type information.

        Storage is right-aligned, so offset specifies byte position from the right.
        """
        # Ensure 32 bytes
        if len(raw_value) < 32:
            raw_value = raw_value.rjust(32, b"\x00")

        # Extract relevant bytes based on offset and size
        size = type_info.num_bytes or 32
        start = 32 - offset - size
        end = 32 - offset
        relevant_bytes = raw_value[start:end]

        # Decode based on type
        decoded = self._decode_by_type(relevant_bytes, type_info)

        # Format for display
        display = self.format_value(decoded, type_info.label)

        return DecodedValue(
            raw="0x" + raw_value.hex(),
            decoded=decoded,
            type_label=type_info.label,
            display=display,
        )

    def _decode_by_type(self, data: bytes, type_info: StorageType) -> Any:
        """Decode bytes based on type."""
        label = type_info.label.lower()
        base = type_info.base_type or label

        # Boolean
        if base in ("bool", "t_bool") or "bool" in label:
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
        if base.startswith("bytes") and base not in ("bytes", "t_bytes"):
            n = type_info.num_bytes or self._extract_bits(base) // 8 or len(data)
            return self._decode_bytesN(data, n)

        # Enum (stored as uint)
        if "enum" in label.lower():
            return self._decode_uint(data)

        # Contract type (stored as address)
        if type_info.kind == "contract":
            return self._decode_address(data)

        # Default to hex
        return "0x" + data.hex()

    def _decode_address(self, data: bytes) -> str:
        """Decode an address from storage (last 20 bytes, checksummed)."""
        addr_bytes = data[-20:] if len(data) >= 20 else data.rjust(20, b"\x00")
        try:
            return Web3.to_checksum_address(addr_bytes)
        except Exception:
            return "0x" + addr_bytes.hex()

    def _decode_uint(self, data: bytes) -> int:
        """Decode unsigned integer (big-endian)."""
        return int.from_bytes(data, "big")

    def _decode_int(self, data: bytes, bits: int) -> int:
        """Decode signed integer (two's complement)."""
        value = int.from_bytes(data, "big")
        sign_bit = 1 << (bits - 1)
        if value & sign_bit:
            value = value - (1 << bits)
        return value

    def _decode_bytesN(self, data: bytes, n: int) -> str:
        """Decode fixed-size bytes (left-aligned in storage)."""
        relevant = data[:n]
        return "0x" + relevant.hex()

    def _extract_bits(self, type_name: str) -> Optional[int]:
        """Extract bit width from type name like 'uint256' or 't_uint128'."""
        match = re.search(r"(\d+)", type_name)
        if match:
            return int(match.group(1))
        return None

    def decode_heuristic(self, raw_value: bytes) -> DecodedValue:
        """
        Attempt to decode without type information.

        Heuristics (priority order - prefer integers over booleans to avoid false positives):
        1. All zeros -> 0
        2. Small integer (fits in reasonable range, < 10^18)
        3. Address pattern (12 leading zeros, 20 bytes of non-zero data)
        4. Large integer (>= 10^18, likely a wei amount or timestamp)
        5. Default to bytes32 hex

        NOTE: We intentionally don't heuristically guess booleans because:
        - 0x...01 could be true OR the integer 1
        - 0x...00 is already caught by zero check
        - Without type info, integers are safer to display
        """
        if len(raw_value) < 32:
            raw_value = raw_value.rjust(32, b"\x00")

        raw_hex = "0x" + raw_value.hex()

        # Zero
        if raw_value == b"\x00" * 32:
            return DecodedValue(
                raw=raw_hex,
                decoded=0,
                type_label="uint256",
                display="0",
            )

        uint_value = int.from_bytes(raw_value, "big")

        # Small integer (< 10^18, unlikely to be wei or address-like)
        if uint_value < 10**18:
            return DecodedValue(
                raw=raw_hex,
                decoded=uint_value,
                type_label="uint256",
                display=f"{uint_value:,}",
            )

        # Address pattern (12 leading zeros = fits in 20 bytes)
        if self._looks_like_address(raw_value):
            addr = self._decode_address(raw_value)
            return DecodedValue(
                raw=raw_hex,
                decoded=addr,
                type_label="address",
                display=self._format_address(addr),
            )

        # Large integer - just show the number, don't guess units
        if uint_value < 2**256:
            return DecodedValue(
                raw=raw_hex,
                decoded=uint_value,
                type_label="uint256",
                display=f"{uint_value:,}",
            )

        # Default to bytes32
        return DecodedValue(
            raw=raw_hex,
            decoded=raw_hex,
            type_label="bytes32",
            display=raw_hex[:10] + "..." + raw_hex[-8:] if len(raw_hex) > 20 else raw_hex,
        )

    def _looks_like_address(self, data: bytes) -> bool:
        """Check if value looks like an address (12 leading zeros, non-zero address)."""
        if data[:12] != b"\x00" * 12:
            return False
        if data[12:] == b"\x00" * 20:
            return False
        return True

    def format_value(self, value: Any, type_label: str) -> str:
        """Format a decoded value for human-readable display."""
        # Boolean
        if isinstance(value, bool):
            return str(value).lower()

        # Address
        if isinstance(value, str) and value.startswith("0x") and len(value) == 42:
            return self._format_address(value)

        # Integer
        if isinstance(value, int):
            return self._format_integer(value, type_label)

        # Bytes/hex strings
        if isinstance(value, str) and value.startswith("0x"):
            if len(value) > 20:
                return value[:10] + "..." + value[-8:]
            return value

        # String
        if isinstance(value, str):
            if len(value) > 100:
                return f'"{value[:100]}..."'
            return f'"{value}"'

        return str(value)

    def _format_address(self, address: str) -> str:
        """Format address with truncation: 0xAbCd...EfGh"""
        if len(address) != 42:
            return address
        return f"{address[:6]}...{address[-4:]}"

    def _format_integer(self, value: int, type_label: str) -> str:
        """Format integer with comma separators (no abbreviations)."""
        return f"{value:,}"

    def decode_dynamic_bytes(
        self, length_slot_value: bytes, data_slot_values: list[bytes]
    ) -> bytes:
        """
        Decode dynamic bytes/string.

        Short encoding: length < 32, data in same slot (length * 2 in last byte)
        Long encoding: length >= 32, data at keccak256(slot)
        """
        last_byte = length_slot_value[-1]
        if last_byte & 1 == 0:
            # Short encoding
            length = last_byte // 2
            return length_slot_value[:length]
        else:
            # Long encoding
            full_value = int.from_bytes(length_slot_value, "big")
            length = (full_value - 1) // 2
            data = b"".join(data_slot_values)
            return data[:length]

    def decode_string(
        self, length_slot_value: bytes, data_slot_values: list[bytes]
    ) -> str:
        """Decode dynamic string."""
        raw_bytes = self.decode_dynamic_bytes(length_slot_value, data_slot_values)
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return "0x" + raw_bytes.hex()

    def decode_array_length(self, slot_value: bytes) -> int:
        """Decode dynamic array length from its base slot."""
        return int.from_bytes(slot_value, "big")

    def decode_packed_slot(
        self,
        raw_value: bytes,
        variables: list[StorageVariable],
        types: dict[str, StorageType],
    ) -> dict[str, DecodedValue]:
        """
        Decode all packed variables from a single slot.

        Args:
            raw_value: The 32-byte slot value
            variables: List of variables that share this slot (sorted by offset)
            types: Type definitions from storage layout

        Returns: {variable_name: DecodedValue}
        """
        result = {}
        for var in variables:
            type_info = types.get(var.type_id)
            if type_info:
                # Use the variable's size and offset for extraction
                decoded = self.decode(raw_value, type_info, offset=var.offset)
                result[var.name] = decoded
        return result
