"""Type decoder for converting raw storage values to Solidity types."""

import logging
import re
from typing import Any, Optional

from web3 import Web3

from app.models.domain import DecodedValue, StorageType, StorageVariable

logger = logging.getLogger(__name__)


class TypeDecoder:
    """Decodes raw storage slot values to typed Python values."""

    # Type registry for looking up types by ID (set by caller when available)
    _type_registry: dict[str, StorageType] = {}

    def set_type_registry(self, types: dict[str, StorageType]) -> None:
        """Set the type registry for looking up nested types during decoding."""
        self._type_registry = types

    def decode(
        self,
        raw_value: bytes,
        type_info: StorageType,
        offset: int = 0,
        slot_offset: int = 0,
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

        # For structs with members, use generic struct decoding
        # Skip array types - their base slots store length, not struct data
        is_array_type = "[]" in (type_info.label or "").lower() or type_info.encoding == "dynamic_array"
        if not is_array_type and type_info.members:
            struct_result = self._decode_generic_struct(raw_value, type_info, slot_offset)
            if struct_result is not None:
                return DecodedValue(
                    raw="0x" + raw_value.hex(),
                    decoded=struct_result,
                    type_label=type_info.label,
                )

        # Decode based on type
        decoded = self._decode_by_type(relevant_bytes, type_info)

        return DecodedValue(
            raw="0x" + raw_value.hex(),
            decoded=decoded,
            type_label=type_info.label,
        )

    def _decode_generic_struct(
        self, raw_value: bytes, type_info: StorageType, slot_offset: int = 0
    ) -> Optional[dict]:
        """
        Decode a struct using its member definitions from the layout.

        For multi-slot structs, only decodes members at the given slot_offset.
        For single-slot (packed) structs, decodes all members.

        Args:
            raw_value: The 32-byte slot value
            type_info: Type info with members list
            slot_offset: Which slot within the struct (0 for first slot)

        Returns:
            Dict of {field_name: decoded_value} or None if decoding fails
        """
        if not type_info.members:
            return None

        result = {}

        # Find members at this slot offset
        members_at_slot = [m for m in type_info.members if m.slot == slot_offset]

        if not members_at_slot:
            # No members at this slot offset - might be a different slot of a multi-slot struct
            logger.debug(f"No members at slot_offset {slot_offset} for struct {type_info.label}")
            return None

        for member in members_at_slot:
            try:
                # Get member's type
                member_type = self._type_registry.get(member.type_id)
                if not member_type:
                    # Synthesize primitive types
                    member_type = self._synthesize_type(member.type_id)

                if member_type:
                    # Extract bytes for this member based on its offset and size
                    size = member.size or member_type.num_bytes or 32
                    byte_offset = member.offset

                    # Storage is right-aligned, so calculate extraction range
                    start = 32 - byte_offset - size
                    end = 32 - byte_offset

                    # Ensure valid range
                    start = max(0, start)
                    end = min(32, end)

                    member_bytes = raw_value[start:end]

                    # Decode the member (recursively handles nested structs)
                    decoded_value = self._decode_by_type(member_bytes, member_type)
                    result[member.name] = decoded_value
                else:
                    # Unknown type - use heuristic decoding
                    logger.debug(f"Unknown type {member.type_id} for member {member.name}, using heuristic")
                    size = member.size or 32
                    byte_offset = member.offset
                    start = max(0, 32 - byte_offset - size)
                    end = min(32, 32 - byte_offset)
                    member_bytes = raw_value[start:end].rjust(32, b"\x00")
                    heuristic_result = self.decode_heuristic(member_bytes)
                    result[member.name] = heuristic_result.decoded

            except Exception as e:
                logger.warning(f"Failed to decode struct member {member.name}: {e}")
                result[member.name] = None

        return result if result else None

    def _synthesize_type(self, type_id: str) -> Optional[StorageType]:
        """Synthesize a StorageType for common primitive types."""
        import re

        # uint types
        uint_match = re.match(r'^t_uint(\d+)$', type_id)
        if uint_match:
            bits = int(uint_match.group(1))
            return StorageType(
                id=type_id, label=f"uint{bits}", kind="value",
                encoding="inplace", num_bytes=bits // 8
            )

        # int types
        int_match = re.match(r'^t_int(\d+)$', type_id)
        if int_match:
            bits = int(int_match.group(1))
            return StorageType(
                id=type_id, label=f"int{bits}", kind="value",
                encoding="inplace", num_bytes=bits // 8
            )

        # address
        if type_id in ('t_address', 't_address_payable'):
            return StorageType(
                id=type_id, label="address", kind="value",
                encoding="inplace", num_bytes=20
            )

        # bool
        if type_id == 't_bool':
            return StorageType(
                id=type_id, label="bool", kind="value",
                encoding="inplace", num_bytes=1
            )

        # bytesN
        bytes_match = re.match(r'^t_bytes(\d+)$', type_id)
        if bytes_match:
            n = int(bytes_match.group(1))
            return StorageType(
                id=type_id, label=f"bytes{n}", kind="value",
                encoding="inplace", num_bytes=n
            )

        # Contract types (e.g., t_contract$_IERC20_$123) - stored as address
        if type_id.startswith('t_contract'):
            # Extract contract name from type_id like "t_contract$_IERC20_$123"
            contract_match = re.match(r'^t_contract\$_(\w+)_\$\d+$', type_id)
            contract_name = contract_match.group(1) if contract_match else "contract"
            return StorageType(
                id=type_id, label=contract_name, kind="contract",
                encoding="inplace", num_bytes=20
            )

        return None

    def _decode_by_type(self, data: bytes, type_info: StorageType) -> Any:
        """Decode bytes based on type."""
        label = (type_info.label or "").lower()
        base = type_info.base_type or label

        # Vyper String[N] - the base slot contains length, return as length indicator
        # Actual string decoding requires multiple slots and is handled separately
        vyper_string_match = re.match(r'^string\[(\d+)\]$', label)
        if vyper_string_match:
            length = int.from_bytes(data, "big")
            return f"[length: {length}]"

        # Vyper nonreentrant lock - decode as uint
        if "nonreentrant" in label and "lock" in label:
            return int.from_bytes(data, "big")

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
        if "enum" in label:
            return self._decode_uint(data)

        # Contract type (stored as address)
        # Check kind, or detect common contract/interface patterns by label
        if type_info.kind == "contract":
            return self._decode_address(data)

        # Interface types like ERC20, IERC20, ERC721 are stored as addresses
        if label.startswith("erc") or label.startswith("ierc"):
            return self._decode_address(data)

        # Check if this is an array type - array base slots store length, not struct data
        is_array_type = "[]" in label or type_info.encoding == "dynamic_array"

        # Dynamic array base slot stores length - decode as uint256
        if is_array_type:
            return self._decode_uint(data)

        # Struct type with members - use generic struct decoding
        # Note: This is handled in decode() for the full slot, but we might reach here
        # for nested types or when called directly
        if type_info.kind == "struct" and type_info.members:
            # Pad data back to 32 bytes for struct decoding
            padded = data.rjust(32, b"\x00")
            struct_result = self._decode_generic_struct(padded, type_info, slot_offset=0)
            if struct_result is not None:
                return struct_result

        # Struct type without members - use heuristic decoding
        if type_info.kind == "struct" or "struct" in label:
            padded = data.rjust(32, b"\x00")
            heuristic_result = self.decode_heuristic(padded)
            return heuristic_result.decoded

        # Solidity dynamic string
        if label == "string" or (type_info.encoding == "bytes" and "string" in label):
            padded = data.rjust(32, b"\x00")
            result = self.decode_dynamic_bytes_slot(padded, "string")
            return result.decoded

        # Solidity dynamic bytes (not fixed bytesN)
        if label == "bytes" or (type_info.encoding == "bytes" and label in ("bytes", "t_bytes_storage")):
            padded = data.rjust(32, b"\x00")
            result = self.decode_dynamic_bytes_slot(padded, "bytes")
            return result.decoded

        # User-defined value types (UDVTs) - kind="value" with inplace encoding
        # These are custom type aliases like "type Shares is uint112" or "type MyAddr is address"
        if type_info.kind == "value" and type_info.encoding == "inplace":
            # 20-byte values might be address type aliases - use address heuristic
            if type_info.num_bytes == 20:
                # Pad to 32 bytes and check if looks like address
                padded = data.rjust(32, b"\x00")
                if self._looks_like_address(padded):
                    return self._decode_address(data)
            # Otherwise decode as unsigned integer (most common case)
            return self._decode_uint(data)

        # Default to hex
        return "0x" + data.hex()

    def _decode_address(self, data: bytes) -> str:
        """Decode an address from storage (last 20 bytes, checksummed)."""
        addr_bytes = data[-20:] if len(data) >= 20 else data.rjust(20, b"\x00")
        try:
            return Web3.to_checksum_address(addr_bytes)
        except Exception as e:
            logger.debug(f"Address checksum failed, using hex: {e}")
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
            )

        uint_value = int.from_bytes(raw_value, "big")

        # Small integer (< 10^18, unlikely to be wei or address-like)
        if uint_value < 10**18:
            return DecodedValue(
                raw=raw_hex,
                decoded=uint_value,
                type_label="uint256",
            )

        # Address pattern (12 leading zeros = fits in 20 bytes)
        if self._looks_like_address(raw_value):
            addr = self._decode_address(raw_value)
            return DecodedValue(
                raw=raw_hex,
                decoded=addr,
                type_label="address",
            )

        # Large integer - just show the number
        if uint_value < 2**256:
            return DecodedValue(
                raw=raw_hex,
                decoded=uint_value,
                type_label="uint256",
            )

        # Default to bytes32
        return DecodedValue(
            raw=raw_hex,
            decoded=raw_hex,
            type_label="bytes32",
        )

    def _looks_like_address(self, data: bytes) -> bool:
        """Check if value looks like an address (12 leading zeros, non-zero address)."""
        if data[:12] != b"\x00" * 12:
            return False
        if data[12:] == b"\x00" * 20:
            return False
        return True

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

    def decode_vyper_string(
        self, length_slot_value: bytes, data_slot_values: list[bytes], max_length: int
    ) -> DecodedValue:
        """
        Decode a Vyper String[N] from its storage slots.

        Vyper string storage format:
        - Slot 0: Length as uint256
        - Slots 1..N: String data (left-aligned, ceil(max_length/32) slots)

        Args:
            length_slot_value: The 32-byte value from the length slot
            data_slot_values: List of 32-byte values from subsequent data slots
            max_length: The N in String[N]

        Returns:
            DecodedValue with the decoded string
        """
        raw_hex = "0x" + length_slot_value.hex()
        length = int.from_bytes(length_slot_value, "big")

        if length == 0:
            return DecodedValue(
                raw=raw_hex,
                decoded="",
                type_label=f"String[{max_length}]",
            )

        if length > max_length:
            # Invalid length, return raw
            return DecodedValue(
                raw=raw_hex,
                decoded=f"[invalid length: {length}]",
                type_label=f"String[{max_length}]",
            )

        # Concatenate data slots
        all_data = b"".join(data_slot_values)

        # Extract string bytes (length bytes from the start)
        string_bytes = all_data[:length]

        try:
            decoded_str = string_bytes.decode("utf-8")
            return DecodedValue(
                raw=raw_hex,
                decoded=decoded_str,
                type_label=f"String[{max_length}]",
            )
        except UnicodeDecodeError:
            return DecodedValue(
                raw=raw_hex,
                decoded="0x" + string_bytes.hex(),
                type_label=f"String[{max_length}]",
            )

    @staticmethod
    def is_vyper_string(type_label: str) -> tuple[bool, int]:
        """
        Check if a type label is a Vyper String[N] and return max length.

        Returns:
            (is_vyper_string, max_length) - max_length is 0 if not a Vyper string
        """
        match = re.match(r'^String\[(\d+)\]$', type_label or "")
        if match:
            return True, int(match.group(1))
        return False, 0

    def decode_dynamic_bytes_slot(
        self, raw_value: bytes, type_label: str = "string"
    ) -> DecodedValue:
        """
        Decode a single slot for a dynamic bytes/string variable.

        Solidity dynamic bytes storage:
        - Short (< 32 bytes): data stored inline, length*2 in last byte (even)
        - Long (>= 32 bytes): length*2+1 in slot (odd), data at keccak256(slot)
        """
        if len(raw_value) < 32:
            raw_value = raw_value.rjust(32, b"\x00")

        raw_hex = "0x" + raw_value.hex()
        last_byte = raw_value[-1]

        # Check if short or long encoding
        if last_byte & 1 == 0:
            # Short encoding: length*2 in last byte, data inline
            length = last_byte // 2
            if length == 0:
                return DecodedValue(
                    raw=raw_hex,
                    decoded="",
                    type_label=type_label,
                )
            data = raw_value[:length]
            if type_label == "string":
                try:
                    decoded_str = data.decode("utf-8")
                    return DecodedValue(
                        raw=raw_hex,
                        decoded=decoded_str,
                        type_label=type_label,
                    )
                except UnicodeDecodeError:
                    return DecodedValue(
                        raw=raw_hex,
                        decoded="0x" + data.hex(),
                        type_label=type_label,
                    )
            else:
                return DecodedValue(
                    raw=raw_hex,
                    decoded="0x" + data.hex(),
                    type_label=type_label,
                )
        else:
            # Long encoding: length*2+1 in slot, data at keccak256(slot)
            full_value = int.from_bytes(raw_value, "big")
            length = (full_value - 1) // 2
            return DecodedValue(
                raw=raw_hex,
                decoded=length,
                type_label=f"{type_label} length",
            )

    def decode_dynamic_bytes_data_slot(
        self, raw_value: bytes, type_label: str = "string", data_offset: int = 0
    ) -> DecodedValue:
        """
        Decode a data slot for a long dynamic bytes/string.

        These slots contain raw string/bytes data (32 bytes per slot).
        """
        if len(raw_value) < 32:
            raw_value = raw_value.rjust(32, b"\x00")

        raw_hex = "0x" + raw_value.hex()

        if type_label == "string":
            # Try to decode as UTF-8
            # Trim trailing nulls for display
            trimmed = raw_value.rstrip(b"\x00")
            try:
                decoded_str = trimmed.decode("utf-8")
                return DecodedValue(
                    raw=raw_hex,
                    decoded=decoded_str,
                    type_label=f"{type_label}[data:{data_offset}]" if data_offset > 0 else f"{type_label}[data]",
                )
            except UnicodeDecodeError:
                pass

        return DecodedValue(
            raw=raw_hex,
            decoded="0x" + raw_value.hex(),
            type_label=f"{type_label}[data:{data_offset}]" if data_offset > 0 else f"{type_label}[data]",
        )

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

            # Synthesize primitive types if not in types dict
            if not type_info:
                type_info = self._synthesize_type(var.type_id)

            if type_info:
                # Use the variable's size and offset for extraction
                decoded = self.decode(raw_value, type_info, offset=var.offset)
                result[var.name] = decoded
            else:
                # Fallback: extract bytes based on var.size and var.offset, decode heuristically
                logger.debug(f"Unknown type {var.type_id} for packed var {var.name}, using heuristic")
                size = var.size or 32
                start = 32 - var.offset - size
                end = 32 - var.offset
                start = max(0, start)
                end = min(32, end)
                member_bytes = raw_value[start:end].rjust(32, b"\x00")
                decoded = self.decode_heuristic(member_bytes)
                result[var.name] = decoded

        return result
