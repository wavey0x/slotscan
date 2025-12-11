"""Preimage resolution for SHA3/keccak256 hashes."""

import logging
import re
from typing import Optional

from eth_abi import encode as abi_encode
from web3 import Web3

from app.models.domain import StorageLayout

logger = logging.getLogger(__name__)


class PreimageResolver:
    """Resolves SHA3 hashes to their preimages for mapping slot decoding."""

    def build_preimage_lookup(self, sha3_trace: list[dict]) -> dict[str, str]:
        """
        Build a lookup from hash -> preimage for SHA3 operations.

        The preimage for a mapping slot is: abi.encode(key, base_slot)
        - For address keys: 32 bytes (left-padded address) + 32 bytes (slot)
        - For uint keys: 32 bytes (key) + 32 bytes (slot)

        Returns:
            preimage_lookup: {normalized_hash: preimage_hex}
        """
        preimage_lookup: dict[str, str] = {}

        for op in sha3_trace:
            hash_value = op.get("hash")
            preimage = op.get("preimage")
            if hash_value and preimage:
                normalized_hash = self._normalize_slot(hash_value)
                preimage_lookup[normalized_hash] = preimage

        logger.info(f"Built preimage lookup: {len(preimage_lookup)} entries from {len(sha3_trace)} SHA3 ops")
        return preimage_lookup

    def extract_constant_addresses(self, sources: dict[str, str]) -> list[str]:
        """
        Extract constant/immutable address declarations from Solidity sources.

        Looks for patterns like:
        - address constant CRV = 0xD533a949740bb3306d119CC777fa900bA034cd52;
        - address public constant CVX = 0x4e3FBD56CD56c3e72c1403e103b45Db9da5B9D2B;
        - address immutable TOKEN = 0x...;
        - IERC20 constant CRV = IERC20(0x...);

        Returns list of lowercase checksummed addresses.
        """
        addresses: set[str] = set()

        patterns = [
            r'(?:address|IERC20|ERC20|IERC20Metadata)\s+(?:public\s+)?(?:constant|immutable)\s+\w+\s*=\s*(0x[a-fA-F0-9]{40})',
            r'(?:IERC20|ERC20|IERC20Metadata)\s+(?:public\s+)?(?:constant|immutable)\s+\w+\s*=\s*\w+\((0x[a-fA-F0-9]{40})\)',
            r'(?:constant|immutable)\s+\w+\s*=\s*(?:\w+\()?(0x[a-fA-F0-9]{40})',
        ]

        for source_content in sources.values():
            for pattern in patterns:
                matches = re.findall(pattern, source_content, re.IGNORECASE)
                for match in matches:
                    try:
                        addr = Web3.to_checksum_address(match.lower())
                        addresses.add(addr.lower())
                    except Exception:
                        pass

        if addresses:
            logger.info(f"Extracted {len(addresses)} constant addresses from sources")

        return list(addresses)

    def build_constant_preimage_lookup(
        self,
        sources: dict[str, str],
        layout: StorageLayout,
    ) -> dict[str, str]:
        """
        Build preimage lookup for compile-time constant mapping keys.

        When a Solidity contract uses constant addresses as mapping keys:
            address constant CRV = 0x...;
            mapping(address => uint256) rewardMap;
            rewardMap[CRV] = 3;

        The compiler pre-computes keccak256(CRV || slot) at compile time and embeds
        the hash in bytecode as a constant (loaded via CODECOPY, not runtime SHA3).

        This method extracts constant addresses from source and computes their
        mapping slot hashes to supplement the runtime SHA3 preimage lookup.
        """
        constant_lookup: dict[str, str] = {}

        constant_addresses = self.extract_constant_addresses(sources)
        if not constant_addresses:
            return constant_lookup

        mapping_slots: list[tuple[str, int]] = []
        for var in layout.variables:
            var_type = layout.get_type(var.type_id)
            if var_type and var_type.encoding == "mapping":
                key_type = layout.get_type(var_type.key_type) if var_type.key_type else None
                if key_type and "address" in (key_type.label or "").lower():
                    mapping_slots.append((var.name, var.slot))

        if not mapping_slots:
            return constant_lookup

        for addr in constant_addresses:
            addr_checksummed = Web3.to_checksum_address(addr)
            for var_name, base_slot in mapping_slots:
                try:
                    preimage = abi_encode(["address", "uint256"], [addr_checksummed, base_slot])
                    slot_hash = Web3.keccak(preimage).hex()
                    normalized_hash = self._normalize_slot(slot_hash)
                    preimage_hex = "0x" + preimage.hex()
                    constant_lookup[normalized_hash] = preimage_hex

                    logger.debug(
                        f"Constant preimage: {var_name}[{addr[:10]}...] -> {normalized_hash[:20]}..."
                    )
                except Exception as e:
                    logger.debug(f"Failed to compute slot for {var_name}[{addr}]: {e}")

        if constant_lookup:
            logger.info(
                f"Built constant preimage lookup: {len(constant_lookup)} entries "
                f"from {len(constant_addresses)} addresses x {len(mapping_slots)} mappings"
            )

        return constant_lookup

    def parse_mapping_preimage(
        self, preimage: str, layout: Optional[StorageLayout]
    ) -> tuple[str | None, str | None, int | None]:
        """
        Parse a 64-byte mapping preimage into (key, base_slot, struct_offset).

        For mapping(key => value), preimage is: key (32 bytes) || base_slot (32 bytes)

        Returns: (key_hex, variable_name, struct_offset)
        """
        if not preimage or not preimage.startswith("0x"):
            return None, None, None

        preimage_bytes = preimage[2:]

        if len(preimage_bytes) == 128:  # 64 bytes * 2 hex chars
            key_hex = "0x" + preimage_bytes[:64]
            base_slot_hex = "0x" + preimage_bytes[64:]

            base_slot_int = int(base_slot_hex, 16)
            variable_name = None
            struct_offset = None

            if layout:
                for var in layout.variables:
                    var_slot = int(var.slot)
                    if var_slot == base_slot_int:
                        variable_name = var.label
                        break

            return key_hex, variable_name, struct_offset

        return None, None, None

    def decode_mapping_key(self, key_hex: str) -> str:
        """
        Decode a mapping key from its 32-byte hex representation.

        - If it looks like an address (first 12 bytes are zeros), format as address
        - If it's a small number, format as integer
        - Otherwise, return the hex
        """
        if not key_hex or not key_hex.startswith("0x"):
            return key_hex

        key_bytes = key_hex[2:]

        # Check if it's an address (first 24 hex chars are zeros)
        if len(key_bytes) == 64 and key_bytes[:24] == "0" * 24:
            return "0x" + key_bytes[24:]

        # Check if it's a small integer
        key_int = int(key_hex, 16)
        if key_int < 2**64:
            return str(key_int)

        return key_hex

    def _normalize_slot(self, slot: str) -> str:
        """Normalize slot to 66-char hex (0x + 64 chars)."""
        if isinstance(slot, int):
            return f"0x{slot:064x}"
        slot_clean = slot[2:] if slot.startswith("0x") else slot
        return f"0x{slot_clean.lower().zfill(64)}"
