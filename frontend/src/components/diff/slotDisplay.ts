import { PackedFieldResponse, SlotChangeResponse } from '@/lib/types';
import {
  formatDecodedValue,
  getCopyValue,
  getTooltipValue,
  truncateAddress,
  truncateHash,
  valuesEqual,
} from '@/lib/utils';

export function storageHoverProps(decoded: unknown, encoded: string | null) {
  const fallback = encoded ?? 'unknown';
  return {
    value: decoded !== null && decoded !== undefined ? getCopyValue(decoded, fallback) : fallback,
    copyActionValue: decoded ?? fallback,
    tooltip: getTooltipValue(decoded, fallback),
  };
}

export function packedFieldChanged(field: PackedFieldResponse): boolean {
  return !valuesEqual(field.before.value_decoded, field.after.value_decoded);
}

export function storageDisplayValue(
  decoded: unknown,
  encoded: string | null,
  showHex: boolean,
): string {
  if (showHex) return encoded ?? 'unknown';
  if (decoded !== null && decoded !== undefined) return formatDecodedValue(decoded);
  return encoded ?? 'unknown';
}

export function storageKeyDisplay(key: string | null): { display: string; full: string } | null {
  if (!key) return null;
  if (/^0x[a-fA-F0-9]{40}$/.test(key)) return { display: truncateAddress(key), full: key };
  if (key.length > 16) return { display: truncateHash(key, 6), full: key };
  return { display: key, full: key };
}

export function deriveSlotDisplay(slot: SlotChangeResponse, showHex: boolean) {
  const packedFields = slot.packed_fields ?? [];
  const hasPacked = packedFields.length > 0;
  const changedPackedFields = hasPacked
    ? packedFields.filter(packedFieldChanged)
    : [];
  // Preserve the compact changed-fields view, but a fully no-op packed write
  // must still show the values that were rewritten.
  const displayedPackedFields = changedPackedFields.length > 0
    ? changedPackedFields
    : packedFields;
  const showPackedAsTree = hasPacked && displayedPackedFields.length > 1;
  const singlePackedField = hasPacked && !showPackedAsTree && displayedPackedFields.length === 1
    ? displayedPackedFields[0]
    : null;
  return {
    hasInterimChanges: slot.changes.length > 1,
    hasPacked,
    firstStep: slot.changes[0]?.step ?? null,
    displayedPackedFields,
    showPackedAsTree,
    singlePackedField,
    initialValue: singlePackedField && !showHex
      ? formatDecodedValue(singlePackedField.before.value_decoded)
      : storageDisplayValue(slot.before.value_decoded, slot.before.value_encoded, showHex),
    finalValue: singlePackedField && !showHex
      ? formatDecodedValue(singlePackedField.after.value_decoded)
      : storageDisplayValue(slot.after.value_decoded, slot.after.value_encoded, showHex),
    revertedWriteCount: slot.changes.filter((change) => change.frame_outcome === 'reverted').length,
  };
}
