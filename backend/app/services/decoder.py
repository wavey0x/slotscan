"""Type decoder for converting raw storage values to Solidity types."""

import json
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

        # Decode based on type
        # For multi-slot structs, attempt slot-aware decoding first
        slot_struct = self._decode_struct_slot(relevant_bytes, type_info, slot_offset)
        if isinstance(slot_struct, DecodedValue):
            return slot_struct

        decoded = slot_struct if slot_struct is not None else self._decode_by_type(relevant_bytes, type_info)

        # Format for display, with nicer rendering for structs/collections
        if isinstance(decoded, dict):
            display = self._format_dict(decoded)
        elif isinstance(decoded, list):
            display = self._format_list(decoded)
        else:
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

        # Known custom structs (manually decoded)
        lower_label = label.lower()

        if "currentrateinfo" in lower_label:
            return self._decode_current_rate_info(data)
        if "exchangerateinfo" in lower_label:
            return self._decode_exchange_rate_info(data)
        if "rewardtype" in lower_label:
            return self._decode_reward_type(data)

        # Struct type (without known members) - use heuristic decoding
        # This handles nested structs where members aren't available in the layout
        if type_info.kind == "struct" or "struct" in label:
            # Pad back to 32 bytes and apply heuristic decoding
            padded = data.rjust(32, b"\x00")
            heuristic_result = self.decode_heuristic(padded)
            return heuristic_result.decoded

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

    def _decode_current_rate_info(self, raw_value: bytes) -> dict:
        """Decode ResupplyPairCore.CurrentRateInfo {uint64 lastTimestamp, uint64 ratePerSec, uint128 lastShares}."""
        if len(raw_value) < 32:
            raw_value = raw_value.rjust(32, b"\x00")
        last_timestamp = int.from_bytes(raw_value[-8:], "big")
        rate_per_sec = int.from_bytes(raw_value[-16:-8], "big")
        last_shares = int.from_bytes(raw_value[:-16], "big")
        return {
            "lastTimestamp": last_timestamp,
            "ratePerSec": rate_per_sec,
            "lastShares": last_shares,
        }

    def _decode_exchange_rate_info(self, raw_value: bytes) -> dict:
        """
        Decode ResupplyPairCore.ExchangeRateInfo:
        slot0 packs {address oracle, uint96 lastTimestamp}, slot1 is uint256 exchangeRate.
        We heuristically decide which layout we are seeing based on the high 12 bytes (timestamp size).
        """
        if len(raw_value) < 32:
            raw_value = raw_value.rjust(32, b"\x00")

        high_12 = raw_value[:12]      # timestamp bytes (uint96)
        low_20 = raw_value[-20:]      # address bytes

        last_timestamp = int.from_bytes(high_12, "big")
        exchange_rate = int.from_bytes(raw_value, "big")

        is_timestamp_reasonable = last_timestamp < 2**48
        low_20_nonzero = any(low_20)

        oracle_addr = self._decode_address(low_20) if low_20_nonzero else None

        # Always return consistent keys to avoid shape-mismatch across before/after
        if is_timestamp_reasonable or low_20_nonzero:
            return {
                "oracle": oracle_addr if oracle_addr else "0x" + "0" * 40,
                "lastTimestamp": last_timestamp,
                "exchangeRate": 0,
            }

        return {
            "oracle": "0x" + "0" * 40,
            "lastTimestamp": 0,
            "exchangeRate": exchange_rate,
        }

    def _decode_exchange_rate_info_slot(self, raw_value: bytes, slot_offset: int) -> DecodedValue:
        """Slot-aware decoder for ExchangeRateInfo."""
        raw_hex = "0x" + raw_value.hex()
        if slot_offset == 0:
            decoded = self._decode_exchange_rate_info(raw_value)
        else:
            # Exchange rate slot
            exchange_rate = int.from_bytes(raw_value, "big")
            decoded = {
                "oracle": "0x" + "0" * 40,
                "lastTimestamp": 0,
                "exchangeRate": exchange_rate,
            }
        display = self._format_dict(decoded) if isinstance(decoded, dict) else self.format_value(decoded, "struct")
        return DecodedValue(raw=raw_hex, decoded=decoded, type_label="struct ResupplyPairCore.ExchangeRateInfo", display=display)

    def _decode_reward_type(self, raw_value: bytes) -> dict:
        """
        Decode RewardDistributorMultiEpoch.RewardType:
        slot0 packs {address reward_token, bool is_non_claimable}, slot1 is uint256 reward_remaining.
        """
        if len(raw_value) < 32:
            raw_value = raw_value.rjust(32, b"\x00")

        # Attempt to parse as packed header: [padding][bool][address]
        # Layout: lowest 20 bytes = reward_token, byte before that = bool
        reward_token_bytes = raw_value[-20:]
        bool_byte = raw_value[-21] if len(raw_value) >= 21 else 0
        head = raw_value[:-21]

        reward_remaining = int.from_bytes(raw_value, "big")

        looks_packed = (reward_token_bytes != b"\x00" * 20) or (bool_byte in (0, 1))
        head_is_zero = all(b == 0 for b in head)

        if looks_packed and head_is_zero:
            return {
                "reward_token": self._decode_address(reward_token_bytes),
                "is_non_claimable": bool_byte != 0,
            }

        # Otherwise treat as reward_remaining slot
        return {"reward_remaining": reward_remaining}

    def _decode_reward_type_slot(self, raw_value: bytes, slot_offset: int) -> DecodedValue:
        """Slot-aware decoder for RewardType."""
        raw_hex = "0x" + raw_value.hex()
        if slot_offset == 0:
            decoded = self._decode_reward_type(raw_value)
        else:
            reward_remaining = int.from_bytes(raw_value, "big")
            decoded = {
                "reward_token": "0x" + "0" * 40,
                "is_non_claimable": False,
                "reward_remaining": reward_remaining,
            }
        display = self._format_dict(decoded) if isinstance(decoded, dict) else self.format_value(decoded, "struct")
        return DecodedValue(raw=raw_hex, decoded=decoded, type_label="struct RewardDistributorMultiEpoch.RewardType", display=display)

    def _decode_struct_slot(self, raw_value: bytes, type_info: StorageType, slot_offset: int) -> DecodedValue | None:
        """Attempt slot-aware struct decoding for known structs."""
        label = (type_info.label or "").lower()
        if "exchangerateinfo" in label:
            return self._decode_exchange_rate_info_slot(raw_value, slot_offset)
        if "rewardtype" in label:
            return self._decode_reward_type_slot(raw_value, slot_offset)
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
                display=self._abbreviate_int(uint_value),
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
                display=self._abbreviate_int(uint_value),
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
        """Return full checksum address without truncation."""
        return address

    def _format_integer(self, value: int, type_label: str) -> str:
        """Format integer with comma separators, abbreviating very large values (>=1e30)."""
        return self._abbreviate_int(value)

    def _abbreviate_int(self, value: int) -> str:
        """Abbreviate extremely large integers for display (>=1e30)."""
        threshold = 10**30
        is_neg = value < 0
        abs_val = -value if is_neg else value
        if abs_val < threshold:
            return f"{value:,}"
        s = str(abs_val)
        mantissa = s[0] + ("." + s[1:5] if len(s) > 1 else "")
        exp = len(s) - 1
        return f"{'-' if is_neg else ''}{mantissa}e{exp}"

    def _format_dict(self, value: dict) -> str:
        """Format dict values in a compact JSON style."""
        try:
            def fmt(v):
                if isinstance(v, int):
                    return self._abbreviate_int(v)
                if isinstance(v, list):
                    return [fmt(x) for x in v]
                if isinstance(v, dict):
                    return {k: fmt(x) for k, x in v.items()}
                return v

            formatted = fmt(value)
            return json.dumps(formatted, separators=(",", ":"), ensure_ascii=False)
        except Exception:
            return str(value)

    def _format_list(self, value: list) -> str:
        """Format list values in a compact JSON style."""
        try:
            formatted = []
            for v in value:
                if isinstance(v, int):
                    formatted.append(self._abbreviate_int(v))
                elif isinstance(v, dict):
                    formatted.append({k: v2 if not isinstance(v2, int) else self._abbreviate_int(v2) for k, v2 in v.items()})
                else:
                    formatted.append(v)
            return json.dumps(formatted, separators=(",", ":"), ensure_ascii=False)
        except Exception:
            return str(value)

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

    def decode_dynamic_bytes_slot(
        self, raw_value: bytes, type_label: str = "string"
    ) -> DecodedValue:
        """
        Decode a single slot for a dynamic bytes/string variable.

        Solidity dynamic bytes storage:
        - Short (< 32 bytes): data stored inline, length*2 in last byte (even)
        - Long (>= 32 bytes): length*2+1 in slot (odd), data at keccak256(slot)

        Args:
            raw_value: The 32-byte slot value
            type_label: The type label (e.g., "string", "bytes")

        Returns: DecodedValue with appropriate decoded content
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
                    display='""',
                )
            data = raw_value[:length]
            if type_label == "string":
                try:
                    decoded_str = data.decode("utf-8")
                    return DecodedValue(
                        raw=raw_hex,
                        decoded=decoded_str,
                        type_label=type_label,
                        display=f'"{decoded_str}"' if len(decoded_str) <= 50 else f'"{decoded_str[:50]}..."',
                    )
                except UnicodeDecodeError:
                    return DecodedValue(
                        raw=raw_hex,
                        decoded="0x" + data.hex(),
                        type_label=type_label,
                        display=f"0x{data.hex()[:20]}..." if len(data) > 10 else f"0x{data.hex()}",
                    )
            else:
                return DecodedValue(
                    raw=raw_hex,
                    decoded="0x" + data.hex(),
                    type_label=type_label,
                    display=f"0x{data.hex()[:20]}..." if len(data) > 10 else f"0x{data.hex()}",
                )
        else:
            # Long encoding: length*2+1 in slot, data at keccak256(slot)
            full_value = int.from_bytes(raw_value, "big")
            length = (full_value - 1) // 2
            return DecodedValue(
                raw=raw_hex,
                decoded=length,
                type_label=f"{type_label} (long)",
                display=f"length={length} bytes",
            )

    def decode_dynamic_bytes_data_slot(
        self, raw_value: bytes, type_label: str = "string", data_offset: int = 0
    ) -> DecodedValue:
        """
        Decode a data slot for a long dynamic bytes/string.

        These slots contain raw string/bytes data (32 bytes per slot).

        Args:
            raw_value: The 32-byte slot value
            type_label: The type label
            data_offset: Which data slot this is (0 for first, 1 for second, etc.)

        Returns: DecodedValue with the raw data content
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
                    display=f'"{decoded_str}"' if len(decoded_str) <= 50 else f'"{decoded_str[:50]}..."',
                )
            except UnicodeDecodeError:
                pass

        return DecodedValue(
            raw=raw_hex,
            decoded="0x" + raw_value.hex(),
            type_label=f"{type_label}[data:{data_offset}]" if data_offset > 0 else f"{type_label}[data]",
            display=f"0x{raw_value.hex()[:20]}...",
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
            if type_info:
                # Use the variable's size and offset for extraction
                decoded = self.decode(raw_value, type_info, offset=var.offset)
                result[var.name] = decoded
        return result
