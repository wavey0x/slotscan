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

// Abbreviate extremely large integers (>= 1e30) for display while preserving readability
const BIG_ABBREV_THRESHOLD = 10n ** 30n;

function tryParseBigInt(value: string): bigint | null {
  const cleaned = value.replace(/,/g, '');
  if (/^-?\d+$/.test(cleaned)) {
    try {
      return BigInt(cleaned);
    } catch {
      return null;
    }
  }
  return null;
}

function abbreviateBigInt(value: bigint): string {
  const isNegative = value < 0;
  const absStr = (isNegative ? -value : value).toString();
  const mantissa = absStr.length > 1 ? `${absStr[0]}.${absStr.slice(1, 5)}` : absStr;
  const exponent = absStr.length - 1;
  return `${isNegative ? '-' : ''}${mantissa}e${exponent}`;
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

  // Render objects more usefully than "[object Object]"
  if (typeof value === 'object') {
    return formatObjectMultiline(value as Record<string, unknown>);
  }

  // Try BigInt parsing (handles comma-separated integers)
  const big = tryParseBigInt(str);
  if (big !== null) {
    return formatBigNumber(big);
  }

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
// Render object fields as multi-line type name + value when both are available
export function formatObjectMultiline(value: Record<string, unknown>): string {
  return Object.entries(value)
    .map(([k, v]) => {
      // Try to infer simple type label for display
      let typeLabel = '';
      if (typeof v === 'string') {
        typeLabel = v.startsWith('0x') ? 'address' : 'string';
      } else if (typeof v === 'number' || typeof v === 'bigint') {
        typeLabel = 'uint256';
      } else if (typeof v === 'boolean') {
        typeLabel = 'bool';
      }
      const renderedVal = typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v);
      return `${typeLabel ? typeLabel + ' ' : ''}${k} = ${renderedVal}`;
    })
    .join('\n');
}

export function getCopyValue(
  decoded: unknown,
  display: string | null,
  raw: string
): string {
  const isSci = (s: string) => /^-?\d+(?:\.\d+)?e[+-]?\d+$/i.test(s);
  // Prefer decoded when it is trustworthy; otherwise fall back to raw.
  try {
    if (decoded === null || decoded === undefined) return raw;
    if (typeof decoded === 'bigint') return decoded.toString();
    if (typeof decoded === 'number') {
      if (!Number.isFinite(decoded)) return raw;
      // For potentially large ints, derive from raw if it looks like a full 32-byte hex
      if (Math.abs(decoded) >= 1e15 && /^0x[0-9a-fA-F]{64}$/.test(raw)) {
        return BigInt(raw).toString();
      }
      return decoded.toString();
    }
    if (typeof decoded === 'string') {
      const cleaned = decoded.replace(/,/g, '');
      if (/^-?\d+$/.test(cleaned)) return cleaned;
      if (isSci(cleaned) && /^0x[0-9a-fA-F]+$/.test(raw)) {
        try {
          return BigInt(raw).toString();
        } catch {
          return cleaned;
        }
      }
      return decoded;
    }
    if (typeof decoded === 'object') {
      return JSON.stringify(decoded);
    }
  } catch {
    // ignore and fall through
  }
  return display ?? raw;
}

export function formatScientific(value: string | number | bigint): string | null {
  try {
    if (typeof value === 'bigint') {
      const s = value < 0 ? (-value).toString() : value.toString();
      if (s === '0') return '0';
      const mantissa = s.length > 1 ? `${s[0]}.${s.slice(1, 5)}` : s;
      const exp = s.length - 1;
      return `${value < 0 ? '-' : ''}${mantissa}e${exp}`;
    }
    const str = typeof value === 'number' ? value.toString() : String(value);
    const cleaned = str.replace(/,/g, '');
    if (/^-?\d+$/.test(cleaned)) {
      const big = BigInt(cleaned);
      return formatScientific(big);
    }
    return null;
  } catch {
    return null;
  }
}

export function getTooltipValue(
  decoded: unknown,
  display: string | null,
  raw: string
): string {
  const fallback = display ?? raw;
  if (decoded === null || decoded === undefined) return fallback;
  const sci = formatScientific(decoded as any);
  return sci ?? fallback;
}
