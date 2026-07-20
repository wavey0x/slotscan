import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function valuesEqual(before: unknown, after: unknown): boolean {
  if (Object.is(before, after)) return true;
  if (typeof before !== 'object' || typeof after !== 'object') return false;
  try {
    return JSON.stringify(before) === JSON.stringify(after);
  } catch {
    return false;
  }
}

export function isAddress(value: string): boolean {
  return /^0x[a-fA-F0-9]{40}$/.test(value);
}

export function isTxHash(value: string): boolean {
  return /^0x[a-fA-F0-9]{64}$/.test(value);
}

const COPY_TEXT_LENGTH = 20;
const COPY_NUMERIC_DIGITS = 12;

export function shouldShowCopyAction(value: unknown, display?: string): boolean {
  if (value === null || value === undefined || typeof value === 'boolean') return false;

  let raw: string;
  try {
    raw = typeof value === 'object'
      ? JSON.stringify(value) ?? String(value)
      : String(value);
  } catch {
    raw = String(value);
  }
  if (display !== undefined && display !== raw) return true;
  if (isAddress(raw) || isTxHash(raw)) return true;
  if (/^0x[a-fA-F0-9]{8,}$/.test(raw)) return true;

  const numeric = raw.replace(/,/g, '');
  if (/^-?\d+$/.test(numeric)) {
    return numeric.replace(/^-/, '').length > COPY_NUMERIC_DIGITS;
  }

  return raw.length > COPY_TEXT_LENGTH;
}

export function truncateAddress(address: string): string {
  if (address.length !== 42) return address;
  return `${address.slice(0, 6)}...${address.slice(-4)}`;
}

export function truncateHash(hash: string, chars = 8): string {
  if (hash.length <= chars * 2 + 3) return hash;
  return `${hash.slice(0, chars + 2)}...${hash.slice(-chars)}`;
}

export function truncateTxHash(hash: string): string {
  return truncateHash(hash, 6);
}

export function formatSlotShort(slot: string, chars = 6): string {
  if (!slot.startsWith('0x')) return slot;
  return truncateHash(slot, chars);
}

export function truncateSlot(slot: string): string {
  if (slot.length <= 18) return slot;
  return slot.substring(0, 10) + '...' + slot.substring(slot.length - 6);
}

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

const RECENT_SEARCHES_KEY = 'slotscan_recent_inspections';
const MAX_RECENT = 10;

export interface RecentInspection {
  chain: string;
  kind: 'contract' | 'transaction';
  value: string;
  name?: string;
  timestamp: number;
}

export function saveRecentInspection(item: Omit<RecentInspection, 'timestamp'>) {
  try {
    const existing = getRecentInspections();
    const filtered = existing.filter(
      (candidate) => !(
        candidate.chain === item.chain
        && candidate.kind === item.kind
        && candidate.value.toLowerCase() === item.value.toLowerCase()
      )
    );
    const updated = [{ ...item, timestamp: Date.now() }, ...filtered].slice(
      0,
      MAX_RECENT
    );
    localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(updated));
  } catch {
    // localStorage not available
  }
}

export function getRecentInspections(): RecentInspection[] {
  try {
    const stored = localStorage.getItem(RECENT_SEARCHES_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

export function removeRecentInspection(
  item: Pick<RecentInspection, 'chain' | 'kind' | 'value'>
) {
  try {
    const updated = getRecentInspections().filter(
      (candidate) => !(
        candidate.chain === item.chain
        && candidate.kind === item.kind
        && candidate.value.toLowerCase() === item.value.toLowerCase()
      )
    );
    if (updated.length > 0) {
      localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(updated));
    } else {
      localStorage.removeItem(RECENT_SEARCHES_KEY);
    }
  } catch {
    // localStorage not available
  }
}

export function clearRecentInspections() {
  try {
    localStorage.removeItem(RECENT_SEARCHES_KEY);
  } catch {
    // localStorage not available
  }
}

export function updateRecentSearchName(chain: string, address: string, name: string) {
  try {
    const existing = getRecentInspections();
    const updated = existing.map((item) =>
      item.kind === 'contract'
      && item.chain === chain
      && item.value.toLowerCase() === address.toLowerCase()
        ? { ...item, name }
        : item
    );
    localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(updated));
  } catch {
    // localStorage not available
  }
}

/**
 * Format a raw BigInt value with commas (no abbreviations)
 */
function formatBigNumber(value: string | number | bigint): string {
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
 * Digits above which integers display in compact scientific form.
 * Full precision stays available via copy actions and tooltips.
 */
const COMPACT_NUMERIC_DIGITS = 15;

/**
 * Compact display for very large integers, e.g. 1e27 or 1.2345e21.
 * Returns null when the value is small enough to display in full.
 */
function formatCompactNumber(value: bigint): string | null {
  const negative = value < BigInt(0);
  const digits = (negative ? -value : value).toString();
  if (digits.length <= COMPACT_NUMERIC_DIGITS) return null;
  const fraction = digits.slice(1, 5).replace(/0+$/, '');
  const mantissa = fraction ? `${digits[0]}.${fraction}` : digits[0];
  return `${negative ? '-' : ''}${mantissa}e${digits.length - 1}`;
}

/**
 * Format decoded value for display. Very large integers compact to
 * scientific notation and addresses middle-truncate; copy actions and
 * tooltips keep the full value. Pass fullAddresses where the surface
 * has room for the complete 42-character address.
 */
export function formatDecodedValue(
  value: unknown,
  options?: { fullAddresses?: boolean },
): string {
  if (value === null || value === undefined) return '';

  // Empty string should display as "" (with quotes) to indicate string type
  if (value === '') return '""';

  const str = String(value);

  // Render objects more usefully than "[object Object]"
  if (typeof value === 'object') {
    return formatObjectMultiline(value as Record<string, unknown>);
  }

  // Try BigInt parsing (handles comma-separated integers)
  const big = tryParseBigInt(str);
  if (big !== null) {
    return formatCompactNumber(big) ?? formatBigNumber(big);
  }

  // If it's a number string, format with commas
  if (/^-?\d+(\.\d+)?$/.test(str)) {
    return formatBigNumber(str);
  }

  // If it's an address, middle-truncate for display
  if (/^0x[a-fA-F0-9]{40}$/.test(str)) {
    return options?.fullAddresses ? str : truncateAddress(str);
  }

  return str;
}
// Render object fields as multi-line type name + value when both are available
function formatObjectMultiline(value: Record<string, unknown>): string {
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

export function getCopyValue(decoded: unknown, encoded: string): string {
  const isSci = (s: string) => /^-?\d+(?:\.\d+)?e[+-]?\d+$/i.test(s);
  // Prefer decoded when it is trustworthy; otherwise fall back to encoded.
  try {
    if (decoded === null || decoded === undefined) return encoded;
    if (typeof decoded === 'bigint') return decoded.toString();
    if (typeof decoded === 'number') {
      if (!Number.isFinite(decoded)) return encoded;
      // For potentially large ints, derive from encoded if it looks like a full 32-byte hex
      if (Math.abs(decoded) >= 1e15 && /^0x[0-9a-fA-F]{64}$/.test(encoded)) {
        return BigInt(encoded).toString();
      }
      return decoded.toString();
    }
    if (typeof decoded === 'boolean') return decoded.toString();
    if (typeof decoded === 'string') {
      const cleaned = decoded.replace(/,/g, '');
      if (/^-?\d+$/.test(cleaned)) return cleaned;
      if (isSci(cleaned) && /^0x[0-9a-fA-F]+$/.test(encoded)) {
        try {
          return BigInt(encoded).toString();
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
  return encoded;
}

export function getTooltipValue(decoded: unknown, encoded: string): string {
  const fullValue = getCopyValue(decoded, encoded);
  const cleaned = fullValue.replace(/,/g, '');
  return /^-?\d+$/.test(cleaned) ? formatBigNumber(cleaned) : fullValue;
}
