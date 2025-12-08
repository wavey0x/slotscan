import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function isAddress(value: string): boolean {
  return /^0x[a-fA-F0-9]{40}$/.test(value);
}

export function isTxHash(value: string): boolean {
  return /^0x[a-fA-F0-9]{64}$/.test(value);
}

export function truncateAddress(address: string): string {
  if (address.length !== 42) return address;
  return `${address.slice(0, 6)}...${address.slice(-4)}`;
}

export function truncateHash(hash: string, chars = 8): string {
  if (hash.length <= chars * 2 + 3) return hash;
  return `${hash.slice(0, chars + 2)}...${hash.slice(-chars)}`;
}

export function formatSlot(slot: string): string {
  if (!slot.startsWith('0x')) return slot;
  try {
    const intVal = BigInt(slot);
    return `${slot} (${intVal.toString(10)})`;
  } catch {
    return slot;
  }
}

export function formatSlotShort(slot: string, chars = 6): string {
  if (!slot.startsWith('0x')) return slot;
  return truncateHash(slot, chars);
}

export function formatNumber(value: number | string): string {
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return String(value);
  return num.toLocaleString();
}

const RECENT_SEARCHES_KEY = 'storagescan_recent_searches';
const MAX_RECENT = 5;

export interface RecentSearch {
  chain: string;
  address: string;
  blockOrTx?: string;
  timestamp: number;
}

export function saveRecentSearch(search: Omit<RecentSearch, 'timestamp'>) {
  try {
    const existing = getRecentSearches();
    const filtered = existing.filter(
      (s) => !(s.chain === search.chain && s.address === search.address)
    );
    const updated = [{ ...search, timestamp: Date.now() }, ...filtered].slice(
      0,
      MAX_RECENT
    );
    localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(updated));
  } catch {
    // localStorage not available
  }
}

export function getRecentSearches(): RecentSearch[] {
  try {
    const stored = localStorage.getItem(RECENT_SEARCHES_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

export function clearRecentSearches() {
  try {
    localStorage.removeItem(RECENT_SEARCHES_KEY);
  } catch {
    // localStorage not available
  }
}

/**
 * Parse a variable path like "rewardData[0x...]" or "accountData[?]" into components
 * Now accepts optional API-provided mapping data for direct use
 */
export interface ParsedVariable {
  variableName: string;
  mappingKey: string | null;
  keyDisplay: string | null;
  isUnknownKey: boolean;
  isMapping: boolean;
  encoding: string | null;
}

export interface ParseVariablePathOptions {
  variablePath: string | null;
  slot: string;
  // New API-provided fields
  mappingKey?: string | null;
  isMapping?: boolean;
  encoding?: string | null;
  variableName?: string | null;
}

export function parseVariablePath(options: ParseVariablePathOptions): ParsedVariable {
  const { variablePath, slot, mappingKey, isMapping, encoding, variableName: apiVariableName } = options;

  // If API provides mapping_key directly, use it
  if (mappingKey) {
    const varName = apiVariableName || (variablePath?.replace(/\[.*\]$/, '') ?? formatSlotShort(slot, 6));
    const isAddress = /^0x[a-fA-F0-9]{40}$/.test(mappingKey);
    return {
      variableName: varName,
      mappingKey: mappingKey,
      keyDisplay: isAddress ? truncateAddress(mappingKey) : mappingKey,
      isUnknownKey: false,
      isMapping: isMapping ?? true,
      encoding: encoding ?? 'mapping',
    };
  }

  if (!variablePath) {
    return {
      variableName: formatSlotShort(slot, 6),
      mappingKey: null,
      keyDisplay: null,
      isUnknownKey: false,
      isMapping: isMapping ?? false,
      encoding: encoding ?? null,
    };
  }

  // Match patterns like "varName[key]" or "varName[?]"
  const match = variablePath.match(/^([^[]+)\[(.+)\]$/);
  if (!match) {
    return {
      variableName: variablePath,
      mappingKey: null,
      keyDisplay: null,
      isUnknownKey: false,
      isMapping: isMapping ?? false,
      encoding: encoding ?? null,
    };
  }

  const [, varName, key] = match;

  // Unknown key case
  if (key === '?') {
    return {
      variableName: varName,
      mappingKey: null,
      keyDisplay: '...',
      isUnknownKey: true,
      isMapping: isMapping ?? true,
      encoding: encoding ?? 'mapping',
    };
  }

  // Known key - truncate if address
  const isAddress = /^0x[a-fA-F0-9]{40}$/.test(key);
  return {
    variableName: varName,
    mappingKey: key,
    keyDisplay: isAddress ? truncateAddress(key) : key,
    isUnknownKey: false,
    isMapping: isMapping ?? true,
    encoding: encoding ?? 'mapping',
  };
}

/**
 * Format slot as decimal or hex
 */
export function formatSlotDecimal(slot: string): string {
  if (!slot.startsWith('0x')) return slot;
  try {
    const intVal = BigInt(slot);
    return intVal.toString(10);
  } catch {
    return slot;
  }
}

/**
 * Format a raw BigInt value with commas (no abbreviations)
 */
export function formatBigNumber(value: string | number | bigint): string {
  try {
    const str = String(value);
    // Handle decimal numbers
    if (str.includes('.')) {
      const [intPart, decPart] = str.split('.');
      return `${BigInt(intPart).toLocaleString()}.${decPart}`;
    }
    return BigInt(str).toLocaleString();
  } catch {
    return String(value);
  }
}

/**
 * Format decoded value without abbreviations
 */
export function formatDecodedValue(value: unknown): string {
  if (value === null || value === undefined) return '';

  const str = String(value);

  // If it's a number string, format with commas
  if (/^-?\d+(\.\d+)?$/.test(str)) {
    return formatBigNumber(str);
  }

  // If it's an address, return as-is
  if (/^0x[a-fA-F0-9]{40}$/.test(str)) {
    return str;
  }

  return str;
}
