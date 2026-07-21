const SMALL_DECLARATION_SLOT_MAX = BigInt(999);
const SLOT_EDGE_CHARACTERS = 2;

export interface StorageLocationInput {
  slot: string;
  endSlot?: string | null;
  byteOffset?: number | null;
  byteSize?: string | number | null;
  isRoot?: boolean;
}

export interface FormattedStorageLocation {
  slot: string;
  fullSlot: string;
  qualifier: string | null;
  display: string;
  full: string;
}

function compactSlot(value: string): string {
  try {
    const slot = BigInt(value);
    if (slot <= SMALL_DECLARATION_SLOT_MAX) return slot.toString();

    const normalized = `0x${slot.toString(16)}`;
    const compactLength = 2 + SLOT_EDGE_CHARACTERS * 2 + 1;
    if (normalized.length <= compactLength) return normalized;
    return `${normalized.slice(0, SLOT_EDGE_CHARACTERS + 2)}…${normalized.slice(-SLOT_EDGE_CHARACTERS)}`;
  } catch {
    const compactLength = SLOT_EDGE_CHARACTERS * 2 + 1;
    if (value.length <= compactLength) return value;
    return `${value.slice(0, SLOT_EDGE_CHARACTERS)}…${value.slice(-SLOT_EDGE_CHARACTERS)}`;
  }
}

function locationQualifier({
  byteOffset,
  byteSize,
  isRoot,
}: StorageLocationInput): string | null {
  if (isRoot) return 'root';

  const offset = byteOffset ?? 0;
  if (byteSize === null || byteSize === undefined) {
    return offset > 0 ? `byte offset ${offset}` : null;
  }

  const size = Number(byteSize);
  if (!Number.isFinite(size) || size <= 0) {
    return offset > 0 ? `byte offset ${offset}` : null;
  }
  if (offset === 0 && size === 32) return null;
  return `bytes ${offset}–${offset + size - 1}`;
}

function locationEndSlot(input: StorageLocationInput): string | null {
  if (input.endSlot) return input.endSlot;

  const offset = input.byteOffset ?? 0;
  const size = Number(input.byteSize);
  if (!Number.isFinite(size) || size <= 0) return null;
  const additionalSlots = Math.ceil((offset + size) / 32) - 1;
  if (additionalSlots <= 0) return null;

  try {
    const end = BigInt(input.slot) + BigInt(additionalSlots);
    return input.slot.startsWith('0x') ? `0x${end.toString(16)}` : end.toString();
  } catch {
    return null;
  }
}

export function formatStorageLocation(input: StorageLocationInput): FormattedStorageLocation {
  const endSlot = locationEndSlot(input);
  const hasRange = Boolean(endSlot && endSlot !== input.slot);
  const slot = hasRange
    ? `${compactSlot(input.slot)}–${compactSlot(endSlot!)}`
    : compactSlot(input.slot);
  const fullSlot = hasRange
    ? `${input.slot}–${endSlot}`
    : input.slot;
  const qualifier = locationQualifier(input);

  return {
    slot,
    fullSlot,
    qualifier,
    display: qualifier ? `${slot} · ${qualifier}` : slot,
    full: qualifier ? `${fullSlot} · ${qualifier}` : fullSlot,
  };
}
