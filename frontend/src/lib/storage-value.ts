import {
  formatDecodedValue,
  getCopyValue,
  getTooltipValue,
  truncateHash,
} from './utils';

export type StorageValueMode = 'decoded' | 'hex';

export interface StorageValuePresentation {
  display: string;
  full: string;
  copyValue: string;
  semanticValue: unknown;
}

const LONG_TEXT_LENGTH = 48;

function serializeDecodedValue(value: unknown): string {
  if (value === null) return 'null';
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value) ?? String(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function compactValue(value: string): string {
  if (/^0x[a-fA-F0-9]{16,}$/.test(value)) return truncateHash(value, 6);
  if (value.includes('\n') || value.length <= LONG_TEXT_LENGTH) return value;
  return `${value.slice(0, 28)}…${value.slice(-16)}`;
}

/**
 * Derive one canonical display, disclosure, and copy representation for a
 * scalar storage value. Structured values remain the responsibility of their
 * field/tree renderers.
 */
export function deriveStorageValue({
  decoded,
  encoded = null,
  mode = 'decoded',
  missing = 'unknown',
}: {
  decoded: unknown;
  encoded?: string | null;
  mode?: StorageValueMode;
  missing?: string;
}): StorageValuePresentation {
  if (mode === 'hex') {
    const full = encoded ?? missing;
    return {
      display: compactValue(full),
      full,
      copyValue: full,
      semanticValue: encoded,
    };
  }

  if (decoded !== null && decoded !== undefined) {
    const fallback = encoded ?? serializeDecodedValue(decoded);
    const rendered = formatDecodedValue(decoded);
    return {
      display: compactValue(rendered),
      full: getTooltipValue(decoded, fallback),
      copyValue: getCopyValue(decoded, fallback),
      semanticValue: decoded,
    };
  }

  if (encoded !== null) {
    return {
      display: compactValue(encoded),
      full: encoded,
      copyValue: encoded,
      semanticValue: encoded,
    };
  }

  if (decoded === null) {
    return {
      display: 'null',
      full: 'null',
      copyValue: 'null',
      semanticValue: null,
    };
  }

  return {
    display: missing,
    full: missing,
    copyValue: missing,
    semanticValue: undefined,
  };
}
