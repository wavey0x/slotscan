import { PackedFieldResponse, SlotChangeResponse } from '@/lib/types';
import {
  truncateAddress,
  truncateHash,
  valuesEqual,
} from '@/lib/utils';

export function packedFieldChanged(field: PackedFieldResponse): boolean {
  return !valuesEqual(field.before.value_decoded, field.after.value_decoded);
}

export function storageKeyDisplay(key: string | null): { display: string; full: string } | null {
  if (!key) return null;
  if (/^0x[a-fA-F0-9]{40}$/.test(key)) return { display: truncateAddress(key), full: key };
  if (key.length > 16) return { display: truncateHash(key, 6), full: key };
  return { display: key, full: key };
}

export function deriveSlotDisplay(slot: SlotChangeResponse) {
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
    revertedWriteCount: slot.changes.filter((change) => change.frame_outcome === 'reverted').length,
  };
}
