import { PackedFieldResponse, SlotChangeResponse } from '@/lib/types';
import {
  formatDecodedValue,
  formatSlotShort,
  getCopyValue,
  getTooltipValue,
  truncateAddress,
  truncateHash,
} from '@/lib/utils';

export function storageHoverProps(decoded: unknown, encoded: string | null) {
  const fallback = encoded ?? 'unknown';
  return {
    value: decoded !== null && decoded !== undefined ? getCopyValue(decoded, fallback) : fallback,
    tooltip: getTooltipValue(decoded, fallback),
  };
}

export function packedFieldChanged(field: PackedFieldResponse): boolean {
  return formatDecodedValue(field.before.value_decoded) !== formatDecodedValue(field.after.value_decoded);
}

export function storageValueIsZero(encoded: string | null, decoded: unknown): boolean {
  if (encoded === `0x${'0'.repeat(64)}` || encoded === '0x0' || encoded === '0x00') return true;
  if (decoded === 0 || decoded === '0' || decoded === BigInt(0)) return true;
  if (decoded === null || decoded === undefined) return false;
  const value = String(decoded);
  return value === '0' || value === '0x0' || /^0x0+$/.test(value);
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

function slotDisplay(slotHex: string, showHex: boolean): string {
  try {
    const value = BigInt(slotHex);
    if (!showHex && value <= BigInt(999)) return value.toString();
    const hex = value.toString(16);
    return hex.length <= 4 ? `0x${hex}` : `0x${hex.slice(0, 2)}..`;
  } catch {
    return formatSlotShort(slotHex, 4);
  }
}

export function deriveSlotDisplay(slot: SlotChangeResponse, showHex: boolean) {
  const hasPacked = Boolean(slot.packed_fields?.length);
  const changedPackedFields = hasPacked
    ? (slot.packed_fields ?? []).filter(packedFieldChanged)
    : [];
  const showPackedAsTree = hasPacked && (
    Boolean(slot.struct_definition?.name) || changedPackedFields.length > 1
  );
  const singlePackedField = hasPacked && !showPackedAsTree && changedPackedFields.length === 1
    ? changedPackedFields[0]
    : null;
  const variablePath = slot.variable_path?.match(/^([^(]+)/)?.[1]?.trim();
  const variableLabel = slot.variable_path?.match(/\(([^)]+)\)$/)?.[1] ?? null;
  const resolvedLeafType = slot.struct_field && slot.struct_definition
    ? slot.struct_definition.members.find((member) => member.name === slot.struct_field)?.type_label
      || slot.value_type
      || slot.type_label
    : slot.value_type || slot.type_label;
  const isStaticArray = slot.array_index !== null && slot.array_index !== undefined
    && !slot.is_mapping && !slot.is_dynamic_array;
  const isDynamicArray = Boolean(slot.is_dynamic_array && slot.array_index !== null);

  return {
    hasInterimChanges: slot.changes.length > 1,
    hasPacked,
    hasParams: Boolean(slot.params?.length),
    isDynamicArray,
    isStaticArray,
    variableDisplayName: variablePath || slot.variable_name || formatSlotShort(slot.slot, 4),
    variableLabel,
    hasKeyedVariablePath: Boolean(slot.variable_path?.includes('[')),
    resolvedLeafType,
    slotNumber: slotDisplay(slot.slot, showHex),
    firstStep: slot.changes[0]?.step ?? null,
    changedPackedFields,
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
