import { PackedFieldResponse, SlotChangeResponse } from '@/lib/types';
import {
  formatDecodedValue,
  formatSlotShort,
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

export function canonicalVariablePath(path: string): string {
  return path.replace(/\s+\([^)]+\)\s*$/, '').trim();
}

export function slotVariablePath(
  slot: Pick<SlotChangeResponse, 'variable_name' | 'variable_path'>,
  memberName?: string | null,
): string | null {
  const rawBase = slot.variable_path || slot.variable_name;
  if (!rawBase) return null;

  const base = canonicalVariablePath(rawBase);
  if (!base) return null;
  if (!memberName || base.endsWith(`.${memberName}`)) return base;
  return `${base}.${memberName}`;
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

export function slotReferenceDisplay(slotHex: string, showHex: boolean): string {
  try {
    const value = BigInt(slotHex);
    if (!showHex && value <= BigInt(999)) return value.toString();
    const hex = value.toString(16);
    // Hashed slots (mappings, ERC-7201 bases) often share a prefix and differ
    // only in the trailing digits, so the suffix carries the distinguishing bits.
    return hex.length <= 6 ? `0x${hex}` : `0x${hex.slice(0, 2)}..${hex.slice(-2)}`;
  } catch {
    return formatSlotShort(slotHex, 4);
  }
}

export function dataPartTypeLabel(
  slot: Pick<SlotChangeResponse, 'data_part_index' | 'data_part_count'>,
  typeLabel: string | null | undefined,
): string | null | undefined {
  const index = slot.data_part_index;
  const count = slot.data_part_count;
  if (
    !typeLabel
    || index === null
    || index === undefined
    || count === null
    || count === undefined
    || count <= 0
    || index < 0
    || index >= count
  ) {
    return typeLabel;
  }
  return `${typeLabel} · ${index + 1}/${count}`;
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
  const baseVariablePath = slotVariablePath(slot);
  const displayVariablePath = singlePackedField && !showHex
    ? slotVariablePath(slot, singlePackedField.name)
    : baseVariablePath;
  const variableLabel = slot.variable_path?.match(/\(([^)]+)\)$/)?.[1] ?? null;
  const baseResolvedLeafType = (!showHex ? singlePackedField?.type_label : null)
    || (slot.struct_field && slot.struct_definition
    ? slot.struct_definition.members.find((member) => member.name === slot.struct_field)?.type_label
      || slot.value_type
      || slot.type_label
    : slot.value_type || slot.type_label);
  const resolvedLeafType = dataPartTypeLabel(slot, baseResolvedLeafType);
  const isStaticArray = slot.array_index !== null && slot.array_index !== undefined
    && !slot.is_mapping && !slot.is_dynamic_array;
  const isDynamicArray = Boolean(slot.is_dynamic_array && slot.array_index !== null);

  return {
    hasInterimChanges: slot.changes.length > 1,
    hasPacked,
    hasParams: Boolean(slot.params?.length),
    isDynamicArray,
    isStaticArray,
    baseVariablePath,
    displayVariablePath,
    variableDisplayName: displayVariablePath || slot.variable_name || formatSlotShort(slot.slot, 4),
    variableLabel,
    hasKeyedVariablePath: Boolean(displayVariablePath?.includes('[')),
    resolvedLeafType,
    slotNumber: slotReferenceDisplay(slot.slot, showHex),
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
