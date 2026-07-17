/**
 * Client-side slot computation utilities for mappings and arrays.
 * Uses viem for keccak256 hashing and ABI encoding.
 */

import { keccak256, encodeAbiParameters, parseAbiParameters, pad, toHex } from 'viem';

/**
 * Compute storage slot for a mapping entry.
 * Formula: keccak256(abi.encode(key, baseSlot))
 */
export function computeMappingSlot(
  baseSlot: bigint,
  key: string,
  keyType: string
): bigint {
  const keyTypeLower = keyType.toLowerCase();
  let encodedData: `0x${string}`;

  if (keyTypeLower.includes('address')) {
    // Address key: abi.encode(address, uint256)
    encodedData = encodeAbiParameters(
      parseAbiParameters('address, uint256'),
      [key as `0x${string}`, baseSlot]
    );
  } else if (keyTypeLower.includes('uint') || keyTypeLower.startsWith('t_uint')) {
    // Uint key: abi.encode(uint256, uint256)
    encodedData = encodeAbiParameters(
      parseAbiParameters('uint256, uint256'),
      [BigInt(key), baseSlot]
    );
  } else if (keyTypeLower.includes('int') && !keyTypeLower.includes('uint')) {
    // Signed int key: abi.encode(int256, uint256)
    encodedData = encodeAbiParameters(
      parseAbiParameters('int256, uint256'),
      [BigInt(key), baseSlot]
    );
  } else if (keyTypeLower.includes('bytes32')) {
    // Bytes32 key: abi.encode(bytes32, uint256)
    const keyBytes = key.startsWith('0x') ? key : `0x${key}`;
    encodedData = encodeAbiParameters(
      parseAbiParameters('bytes32, uint256'),
      [keyBytes as `0x${string}`, baseSlot]
    );
  } else {
    // Default: treat as bytes32
    const keyBytes = key.startsWith('0x')
      ? pad(key as `0x${string}`, { size: 32 })
      : pad(toHex(key), { size: 32 });
    encodedData = encodeAbiParameters(
      parseAbiParameters('bytes32, uint256'),
      [keyBytes as `0x${string}`, baseSlot]
    );
  }

  const hash = keccak256(encodedData);
  return BigInt(hash);
}

/**
 * Compute slot for nested mapping: mapping(K1 => mapping(K2 => V))
 * Apply iteratively - outer key first, then inner key(s).
 */
export function computeNestedMappingSlot(
  baseSlot: bigint,
  keys: { value: string; type: string }[]
): bigint {
  let currentSlot = baseSlot;
  for (const { value, type } of keys) {
    currentSlot = computeMappingSlot(currentSlot, value, type);
  }
  return currentSlot;
}

/**
 * Compute storage slot for a dynamic array element.
 * Array length is stored at baseSlot.
 * Elements start at keccak256(baseSlot).
 */
export function computeDynamicArraySlot(
  baseSlot: bigint,
  index: number,
  elementSlots: number = 1
): bigint {
  const encodedSlot = encodeAbiParameters(
    parseAbiParameters('uint256'),
    [baseSlot]
  );
  const dataStart = BigInt(keccak256(encodedSlot));
  return dataStart + BigInt(index * elementSlots);
}

/**
 * Compute storage slot for a static array element.
 * Static arrays store elements contiguously from baseSlot.
 */
export function computeStaticArraySlot(
  baseSlot: bigint,
  index: number,
  elementSlots: number = 1
): bigint {
  return baseSlot + BigInt(index * elementSlots);
}

/**
 * Format a slot as hex string (with 0x prefix).
 */
export function slotToHex(slot: bigint): string {
  return `0x${slot.toString(16)}`;
}

/**
 * Get human-readable key type hint for input placeholder.
 */
export function getKeyTypeHint(keyType: string): string {
  const lower = keyType.toLowerCase();
  if (lower.includes('address')) return 'Enter address (0x...)';
  if (lower.includes('uint')) return 'Enter number';
  if (lower.includes('int') && !lower.includes('uint')) return 'Enter number (can be negative)';
  if (lower.includes('bytes32')) return 'Enter bytes32 (0x...)';
  if (lower.includes('bytes')) return 'Enter bytes (0x...)';
  if (lower.includes('string')) return 'Enter string';
  return 'Enter key';
}

/**
 * Validate a key value based on its type.
 * Returns error message if invalid, null if valid.
 */
export function validateKey(value: string, keyType: string): string | null {
  if (!value.trim()) return 'Key is required';

  const lower = keyType.toLowerCase();

  if (lower.includes('address')) {
    if (!value.startsWith('0x')) return 'Address must start with 0x';
    if (value.length !== 42) return 'Address must be 42 characters';
    if (!/^0x[0-9a-fA-F]{40}$/.test(value)) return 'Invalid address format';
  } else if (lower.includes('uint')) {
    try {
      const n = BigInt(value);
      if (n < BigInt(0)) return 'Uint cannot be negative';
    } catch {
      return 'Invalid number';
    }
  } else if (lower.includes('int') && !lower.includes('uint')) {
    try {
      BigInt(value);
    } catch {
      return 'Invalid number';
    }
  } else if (lower.includes('bytes32')) {
    if (!value.startsWith('0x')) return 'Bytes32 must start with 0x';
    if (value.length !== 66) return 'Bytes32 must be 66 characters';
    if (!/^0x[0-9a-fA-F]{64}$/.test(value)) return 'Invalid bytes32 format';
  }

  return null;
}
