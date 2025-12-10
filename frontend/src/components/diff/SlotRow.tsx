'use client';

/**
 * SlotRow - Renders a single storage slot change row
 *
 * Display rules documented in: src/DISPLAY_STYLE_GUIDE.md
 * Key rules:
 * - VARIABLE column: Names/types only (tree-style for structs)
 * - VALUE column: Values only (never show type/name)
 *
 * Architecture for packed fields:
 * - Struct header gets its own <tr> row
 * - Each packed field gets its own <tr> row
 * - This leverages HTML table's natural row alignment
 */

import { useState } from 'react';
import { SlotChangeResponse, PackedFieldResponse, StructDefinitionResponse, StorageChangeResponse } from '@/lib/types';
import {
  cn,
  formatSlotShort,
  formatDecodedValue,
  formatObjectMultiline,
  getCopyValue,
  getTooltipValue,
  truncateAddress,
  truncateHash,
} from '@/lib/utils';
import { HoverCell } from '@/components/ui/HoverCell';
import { HoverCard, HoverCardSection, HoverCardDivider, HoverCardRow } from '@/components/ui/HoverCard';
import { Tooltip } from '@/components/ui/Tooltip';

interface SlotRowProps {
  slot: SlotChangeResponse;
  showHex: boolean;
  chainId: string;
  showStep?: boolean;
  isFirst?: boolean;
  isLast?: boolean;
}

// Helper to check if a packed field has changed
const hasFieldChanged = (f: PackedFieldResponse): boolean => {
  const initialDisplay = formatDecodedValue(f.before.value_decoded);
  const finalDisplay = formatDecodedValue(f.after.value_decoded);
  return initialDisplay !== finalDisplay;
};

const stringifyValue = (val: unknown, fallback: string): string => {
  if (val === null || val === undefined) return fallback;
  if (typeof val === 'object') {
    return formatObjectMultiline(val as Record<string, unknown>);
  }
  return String(val);
};

const stringifyValueForCopy = (val: unknown, fallback: string): string => {
  if (val === null || val === undefined) return fallback;
  if (typeof val === 'object') {
    try {
      return JSON.stringify(val);
    } catch {
      return fallback;
    }
  }
  return String(val);
};

// Helper to check if a value represents zero
const isZeroValue = (encoded: string, decoded: unknown): boolean => {
  if (encoded === '0x' + '0'.repeat(64)) return true;
  if (encoded === '0x0' || encoded === '0x00') return true;
  if (decoded === 0 || decoded === '0' || decoded === BigInt(0)) return true;
  if (decoded === null || decoded === undefined) return false;
  const str = String(decoded);
  return str === '0' || str === '0x0' || /^0x0+$/.test(str);
};

// Get changed packed fields
const getChangedPackedFields = (fields: PackedFieldResponse[]): PackedFieldResponse[] => {
  return fields.filter(hasFieldChanged);
};

const makeHoverProps = (decoded: unknown, encoded: string) => {
  return {
    value: decoded !== null && decoded !== undefined ? getCopyValue(decoded, encoded) : encoded,
    tooltip: getTooltipValue(decoded, encoded),
  };
};

// Individual packed field row component
const PackedFieldRow = ({
  field,
  isLast,
  isFirst,
  totalFields,
  chainId,
  showStep,
  slotInfo,
  initialEncoded,
  finalEncoded,
  borderClass,
}: {
  field: PackedFieldResponse;
  isLast: boolean;
  isFirst: boolean;
  totalFields: number;
  chainId: string;
  showStep?: boolean;
  slotInfo?: { display: string; full: string };
  initialEncoded: string;
  finalEncoded: string;
  borderClass?: string;
}) => {
  // Only show tree structure when there are multiple fields (otherwise it's misleading)
  const showTree = totalFields > 1;
  const initialDisplay = formatDecodedValue(field.before.value_decoded);
  const finalDisplay = formatDecodedValue(field.after.value_decoded);
  const isInitialZero = initialDisplay === '0' || initialDisplay === 'false';
  const isFinalZero = finalDisplay === '0' || finalDisplay === 'false';

  return (
    <tr className={cn('hover:bg-gray-50/50', borderClass)}>
      {/* Expand button column - empty for field rows */}
      <td className="px-1 py-0.5 w-5 align-top">
        <span className="w-4 h-4 inline-block" />
      </td>

      {/* Variable column: tree line + branch + type + name */}
      <td className="pl-1 pr-1 py-0.5 w-48 relative">
        {/* Vertical tree line - absolutely positioned to span full cell height */}
        {showTree && !isLast && (
          <div
            className="absolute bg-gray-300"
            style={{ left: '5px', top: 0, bottom: 0, width: '1px' }}
          />
        )}
        {/* For last item: vertical line only to the branch point */}
        {showTree && isLast && (
          <div
            className="absolute bg-gray-300"
            style={{ left: '5px', top: 0, width: '1px', height: '50%' }}
          />
        )}
        {/* Horizontal branch */}
        {showTree && (
          <div
            className="absolute bg-gray-300"
            style={{ left: '5px', top: '50%', width: '8px', height: '1px', transform: 'translateY(-50%)' }}
          />
        )}
        <div className="text-xs font-mono leading-tight pl-4">
          <span className="text-gray-400">{field.type_label}</span>{' '}
          <span className="text-gray-900 font-medium">{field.name}</span>
        </div>
      </td>

      {/* Value column: stacked before/after using flexbox */}
      <td className="px-1 py-0.5 align-top">
        <div className="flex flex-col">
          <div className={cn('text-xs font-mono leading-tight flex items-center gap-1',
            isInitialZero ? 'text-gray-300' : 'text-gray-500')}>
            <HoverCell
              display={initialDisplay}
              {...makeHoverProps(field.before.value_decoded, initialEncoded)}
              chainId={chainId}
              colorClass={cn('text-xs font-mono', isInitialZero ? 'text-gray-300' : 'text-gray-500')}
              forceActions
            />
            <span className="text-gray-400">→</span>
          </div>
          <div className={cn('text-xs font-mono leading-tight',
            isFinalZero ? 'text-gray-300' : 'text-gray-900')}>
            <HoverCell
              display={finalDisplay}
              {...makeHoverProps(field.after.value_decoded, finalEncoded)}
              chainId={chainId}
              colorClass={cn('text-xs font-mono', isFinalZero ? 'text-gray-300' : 'text-gray-900')}
              forceActions
            />
          </div>
        </div>
      </td>

      {/* Slot column - only show on first field if no struct header */}
      <td className="px-1 py-0 w-8 align-top">
        {slotInfo && (
          <HoverCard content={<div className="font-mono text-xs text-gray-100 break-all">{slotInfo.full}</div>} position="top">
            <HoverCell
              display={slotInfo.display}
              value={slotInfo.full}
              colorClass="text-xs text-gray-500 font-mono"
              forceActions
            />
          </HoverCard>
        )}
      </td>

      {/* Step column */}
      {showStep && (
        <td className="px-1 py-0 text-right w-8 align-top" />
      )}
    </tr>
  );
};

// Component for rendering interim changes for packed struct slots
const InterimPackedChangeRows = ({
  change,
  changeIndex,
  totalChanges,
  packedFields,
  chainId,
  showStep,
  isFirstChange,
}: {
  change: StorageChangeResponse;
  changeIndex: number;
  totalChanges: number;
  packedFields: PackedFieldResponse[];
  chainId: string;
  showStep?: boolean;
  isFirstChange: boolean;
}) => {
  // Extract values from change.before/after.value_decoded using field names
  const getFieldValue = (decoded: unknown, fieldName: string): unknown => {
    if (decoded && typeof decoded === 'object' && fieldName in decoded) {
      return (decoded as Record<string, unknown>)[fieldName];
    }
    return null;
  };

  return (
    <>
      {packedFields.map((field, fieldIdx) => {
        const beforeVal = getFieldValue(change.before.value_decoded, field.name);
        const afterVal = getFieldValue(change.after.value_decoded, field.name);
        const beforeDisplay = formatDecodedValue(beforeVal);
        const afterDisplay = formatDecodedValue(afterVal);
        const isLast = fieldIdx === packedFields.length - 1;
        const isBeforeZero = beforeDisplay === '0' || beforeDisplay === 'false' || beforeDisplay === '""';
        const isAfterZero = afterDisplay === '0' || afterDisplay === 'false' || afterDisplay === '""';

        return (
          <tr
            key={fieldIdx}
            className={cn(
              'bg-gray-100/80',
              !isFirstChange && fieldIdx === 0 && 'border-t border-gray-300'
            )}
          >
            {/* Expand button column - empty */}
            <td className="pl-3 py-0.5 align-top" />

            {/* Change number column - only on first field */}
            <td className="pl-3 py-0.5 align-top">
              {fieldIdx === 0 && (
                <span className="text-[10px] text-gray-400">
                  {changeIndex + 1}/{totalChanges}
                </span>
              )}
            </td>

            {/* Field with tree structure + values */}
            <td className="pl-3 py-0.5 align-top">
              <div className="flex items-start gap-2 text-xs font-mono">
                {/* Tree glyph */}
                <span className="text-gray-300 select-none flex-shrink-0">
                  {isLast ? '└' : '├'}
                </span>
                {/* Type and name */}
                <span className="flex-shrink-0">
                  <span className="text-gray-400">{field.type_label}</span>{' '}
                  <span className="text-gray-600">{field.name}</span>
                </span>
                {/* Before → After values */}
                <span className="flex items-center gap-1">
                  <span className={isBeforeZero ? 'text-gray-300' : 'text-gray-500'}>{beforeDisplay}</span>
                  <span className="text-gray-400">→</span>
                  <span className={isAfterZero ? 'text-gray-300' : 'text-gray-700'}>{afterDisplay}</span>
                </span>
              </div>
            </td>

            {/* Empty slot column */}
            <td className="px-1 py-0.5 align-top" />

            {/* Step column - only on first field */}
            {showStep && (
              <td className="px-1 py-0.5 text-right align-top">
                {fieldIdx === 0 && change.step !== null && change.step !== undefined && (
                  <span className="text-[10px] text-gray-400 font-mono">
                    {change.step}
                  </span>
                )}
              </td>
            )}
          </tr>
        );
      })}
    </>
  );
};

export function SlotRow({
  slot,
  showHex,
  chainId,
  showStep = true,
  isFirst = false,
  isLast = false,
}: SlotRowProps) {
  const [expanded, setExpanded] = useState(false);
  // Add top border to separate slots (but not the first one)
  const slotBorderClass = !isFirst ? 'border-t border-gray-200' : '';
  const hasInterimChanges = slot.changes.length > 1;
  const hasPacked = slot.packed_fields && slot.packed_fields.length >= 1;
  const hasParams = slot.params && slot.params.length > 0;
  const isDynamicArray = slot.is_dynamic_array && slot.array_index !== null;
  const canExpand = hasInterimChanges;

  // Use variable_path for display (includes array index/mapping key), fallback to variable_name
  const variableDisplayName = (() => {
    if (slot.variable_path) {
      // Extract the core path without parenthetical labels like "(length)"
      const match = slot.variable_path.match(/^([^(]+)/);
      return match ? match[1].trim() : slot.variable_path;
    }
    return slot.variable_name || formatSlotShort(slot.slot, 4);
  })();

  // For backward compatibility, also keep plain variable name
  const variableName = slot.variable_name || formatSlotShort(slot.slot, 4);

  const variableLabel = (() => {
    if (!slot.variable_path) return null;
    const match = slot.variable_path.match(/\(([^)]+)\)$/);
    return match ? match[1] : null;
  })();

  // Check if this is a static array element (has array_index but not is_mapping or is_dynamic_array)
  const isStaticArray = slot.array_index !== null && slot.array_index !== undefined &&
                        !slot.is_mapping && !slot.is_dynamic_array;

  const formatSlotNumber = (slotHex: string): string => {
    try {
      const slotBigInt = BigInt(slotHex);
      if (showHex) {
        const hexStr = slotBigInt.toString(16);
        if (hexStr.length <= 4) return '0x' + hexStr;
        return '0x' + hexStr.slice(0, 2) + '..';
      } else {
        if (slotBigInt <= BigInt(999)) return slotBigInt.toString();
        const hexStr = slotBigInt.toString(16);
        if (hexStr.length <= 4) return '0x' + hexStr;
        return '0x' + hexStr.slice(0, 2) + '..';
      }
    } catch {
      return formatSlotShort(slotHex, 4);
    }
  };
  const slotNumber = formatSlotNumber(slot.slot);

  const getDisplayValue = (decoded: unknown, encoded: string): string => {
    if (showHex) return encoded;
    if (decoded !== null && decoded !== undefined) return formatDecodedValue(decoded);
    return encoded;
  };

  const formatKey = (key: string | null): { display: string; full: string } | null => {
    if (!key) return null;
    if (/^0x[a-fA-F0-9]{40}$/.test(key)) {
      return { display: truncateAddress(key), full: key };
    }
    if (key.length > 16) {
      return { display: truncateHash(key, 6), full: key };
    }
    return { display: key, full: key };
  };

  const firstStep = slot.changes.length > 0 ? slot.changes[0].step : null;

  // Get changed packed fields
  const changedPackedFields = hasPacked ? getChangedPackedFields(slot.packed_fields!) : [];

  // Determine if we should show packed fields as a tree structure:
  // - Show tree when there's a struct definition (named struct), OR
  // - Show tree when there are 2+ changed packed fields
  // A single packed field without struct definition should render like a regular non-packed field
  const showPackedAsTree = hasPacked && (!!slot.struct_definition?.name || changedPackedFields.length > 1);

  // For single packed field without struct, use the packed field's values
  const singlePackedField = hasPacked && !showPackedAsTree && changedPackedFields.length === 1
    ? changedPackedFields[0]
    : null;

  const initialValue = singlePackedField && !showHex
    ? formatDecodedValue(singlePackedField.before.value_decoded)
    : getDisplayValue(slot.before.value_decoded, slot.before.value_encoded);
  const finalValue = singlePackedField && !showHex
    ? formatDecodedValue(singlePackedField.after.value_decoded)
    : getDisplayValue(slot.after.value_decoded, slot.after.value_encoded);

  const renderStructDefinition = (structDef: StructDefinitionResponse, modifiedField: string | null) => (
    <div className="space-y-1">
      <div className="font-medium text-gray-200">struct {structDef.name}</div>
      <div className="pl-2 space-y-0.5 font-mono text-[10px]">
        {structDef.members.map((member, idx) => {
          const isModified = member.name === modifiedField;
          return (
            <div
              key={idx}
              className={cn(
                'flex gap-2',
                isModified ? 'text-yellow-300 font-medium' : 'text-gray-400'
              )}
            >
              <span className="text-gray-500">[{member.slot_offset}]</span>
              <span>{member.type_label}</span>
              <span className={isModified ? 'text-yellow-300' : 'text-gray-300'}>{member.name}</span>
              {isModified && <span className="text-yellow-400 ml-1">*</span>}
            </div>
          );
        })}
      </div>
    </div>
  );

  const renderPackedFieldsTooltip = (fields: PackedFieldResponse[]) => (
    <div className="space-y-1 font-mono text-[10px]">
      {fields.map((f, idx) => {
        const changed = hasFieldChanged(f);
        return (
          <div
            key={idx}
            className={cn(
              'flex gap-2',
              changed ? 'text-yellow-300 font-medium' : 'text-gray-400'
            )}
          >
            <span className="text-gray-500">{f.type_label}</span>
            <span className={changed ? 'text-yellow-300' : 'text-gray-300'}>{f.name}</span>
            {changed && <span className="text-yellow-400 ml-1">*</span>}
          </div>
        );
      })}
    </div>
  );

  const hasStructInfo = !!slot.struct_definition;
  const showTypeLabel = slot.type_label && !hasStructInfo && !hasPacked;

  // HoverCard content for variable info
  const variableHoverContent = (
    <div className="space-y-2 min-w-[280px]">
      {slot.variable_name && (
        <div className="font-medium text-gray-100 text-sm">
          {slot.variable_name}
        </div>
      )}

      <HoverCardSection title="Slot">
        <div className="font-mono text-xs text-gray-300 break-all select-all">
          {slot.slot}
        </div>
      </HoverCardSection>

      {showTypeLabel && (
        <>
          <HoverCardDivider />
          <HoverCardSection title="Type">
            <div className="font-mono text-xs text-gray-300">
              {slot.type_label}
            </div>
          </HoverCardSection>
        </>
      )}

      {slot.value_type && slot.value_type !== slot.type_label && !hasStructInfo && (
        <>
          <HoverCardDivider />
          <HoverCardSection title="Value Type">
            <div className="font-mono text-xs text-gray-300">
              {slot.value_type}
            </div>
          </HoverCardSection>
        </>
      )}

      {slot.struct_definition && (
        <>
          <HoverCardDivider />
          {renderStructDefinition(slot.struct_definition, slot.struct_field)}
        </>
      )}

      {hasPacked && slot.packed_fields && (
        <>
          <HoverCardDivider />
          <HoverCardSection title="Packed Fields">
            {renderPackedFieldsTooltip(slot.packed_fields)}
          </HoverCardSection>
        </>
      )}

      {(isDynamicArray || isStaticArray) && (
        <>
          <HoverCardDivider />
          <HoverCardSection title="Array Index">
            <div className="flex items-center gap-2">
              <span className="text-gray-500 text-xs font-mono">uint256</span>
              <HoverCell
                display={String(slot.array_index)}
                value={String(slot.array_index)}
                chainId={chainId}
                colorClass="text-gray-200 text-xs font-mono"
                forceActions
              />
            </div>
          </HoverCardSection>
        </>
      )}

      {hasParams && slot.params && (
        <>
          <HoverCardDivider />
          <HoverCardSection title={slot.params.length > 1 ? 'Mapping Keys' : 'Mapping Key'}>
            <div className="space-y-1">
              {slot.params.map((param, idx) => {
                const formatted = formatKey(param.value);
                return (
                  <div key={idx} className="flex items-center gap-2">
                    <span className="text-gray-500 text-xs font-mono">{param.type}</span>
                    {formatted && (
                      <HoverCell
                        display={param.label || formatted.display}
                        value={formatted.full}
                        chainId={chainId}
                        colorClass="text-gray-200 text-xs font-mono"
                        forceActions
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </HoverCardSection>
        </>
      )}
    </div>
  );

  // Expand button element
  const expandButton = (
    <button
      onClick={() => setExpanded(!expanded)}
      className="w-4 h-4 flex items-center justify-center text-gray-400 hover:text-gray-700 text-xs font-mono leading-none"
    >
      {expanded ? '−' : '+'}
    </button>
  );

  return (
    <>
      {/* PACKED FIELDS: Struct header row (if has struct definition) */}
      {showPackedAsTree && slot.struct_definition?.name && (
        <tr className={cn('hover:bg-gray-50/50', expanded && 'bg-gray-50/30', slotBorderClass)}>
          <td className={cn('px-1 py-0.5 w-5 align-top', isFirst && 'pt-2')}>
            {canExpand ? expandButton : <span className="w-4 h-4 inline-block" />}
          </td>
          <td className={cn('px-1 py-0.5 align-top', isFirst && 'pt-2')} colSpan={2}>
            <HoverCard content={variableHoverContent} delay={200} maxWidth="max-w-sm">
              <span className="text-xs font-mono leading-tight no-underline decoration-transparent">
                <span className="text-gray-400">{slot.struct_definition.name}</span>{' '}
                <span className="text-gray-900 font-medium">{slot.variable_name}</span>
              </span>
            </HoverCard>
          </td>
          <td className={cn('px-1 py-0.5 w-8 align-top', isFirst && 'pt-2')}>
            <HoverCard content={<div className="font-mono text-xs text-gray-100 break-all">{slot.slot}</div>} position="top">
              <HoverCell
                display={slotNumber}
                value={slot.slot}
                colorClass="text-xs text-gray-500 font-mono"
                forceActions
              />
            </HoverCard>
          </td>
          {showStep && (
            <td className={cn('px-1 py-0.5 text-right w-8 align-top', isFirst && 'pt-2')}>
              {firstStep !== null && firstStep !== undefined && (
                <HoverCard content={<div className="font-mono text-[10px] text-gray-100">Step: {firstStep}</div>} position="top">
                  <span className="text-[10px] text-gray-400 font-mono cursor-default">
                    {firstStep}
                  </span>
                </HoverCard>
              )}
            </td>
          )}
        </tr>
      )}

      {/* PACKED FIELDS: Individual field rows (only when showing as tree) */}
      {showPackedAsTree && !showHex && changedPackedFields.map((field, idx) => (
        <PackedFieldRow
          key={idx}
          field={field}
          isFirst={idx === 0}
          isLast={idx === changedPackedFields.length - 1}
          totalFields={changedPackedFields.length}
          chainId={chainId}
          showStep={showStep}
          // Show slot/step on first field row only if no struct header
          slotInfo={!slot.struct_definition?.name && idx === 0 ? { display: slotNumber, full: slot.slot } : undefined}
          initialEncoded={slot.before.value_encoded}
          finalEncoded={slot.after.value_encoded}
          // Add border on first field row if no struct header
          borderClass={!slot.struct_definition?.name && idx === 0 ? slotBorderClass : undefined}
        />
      ))}

      {/* NON-PACKED, SINGLE PACKED FIELD, or HEX MODE: Single row */}
      {(!showPackedAsTree || showHex) && (
        <tr className={cn('hover:bg-gray-50/50', expanded && 'bg-gray-50/30', slotBorderClass)}>
          <td className={cn('px-1 py-0.5 w-5 align-top', isFirst && 'pt-2')}>
            {canExpand ? expandButton : <span className="w-4 h-4 inline-block" />}
          </td>

          <td className={cn('px-1 py-0.5 align-top w-48 whitespace-normal', isFirst && 'pt-2')}>
            <HoverCard content={variableHoverContent} delay={200} maxWidth="max-w-sm">
              <span className="space-y-0 break-words block no-underline decoration-transparent">
                {/* Struct type + variable name */}
                {slot.struct_definition?.name && (
                  <span className="text-xs font-mono leading-tight block">
                    <span className="text-gray-400">{slot.struct_definition.name}</span>{' '}
                    <span className="text-gray-900 font-medium">{slot.variable_name}</span>
                  </span>
                )}
                {/* Simple mapping variable name */}
                {slot.is_mapping && !slot.struct_definition?.name && slot.variable_name && (
                  <span className="text-xs font-mono leading-tight block">
                    <span className="text-gray-900 font-medium">{slot.variable_name}</span>
                  </span>
                )}
                {/* Struct field member */}
                {slot.struct_field && slot.struct_definition ? (
                  <span className="text-xs font-mono leading-tight flex items-start">
                    <span className="text-gray-300 mr-1 select-none">└</span>
                    <span>
                      <span className="text-gray-400">
                        {slot.struct_definition.members.find(m => m.name === slot.struct_field)?.type_label}
                      </span>{' '}
                      <span className="text-gray-900 font-medium">{slot.struct_field}</span>
                    </span>
                  </span>
                ) : slot.is_mapping && !slot.struct_definition?.name && slot.value_type ? (
                  <span className="text-xs font-mono leading-tight flex items-start">
                    <span className="text-gray-300 mr-1 select-none">└</span>
                    <span className="text-gray-400">{slot.value_type}</span>
                  </span>
                ) : !slot.struct_definition?.name && !slot.is_mapping ? (
                  <span className="text-xs font-mono leading-tight block">
                    {/* For single packed field, prefer packed field's type; otherwise use slot's type */}
                    {(singlePackedField?.type_label || slot.value_type || slot.type_label) && (
                      <><span className="text-gray-400">{singlePackedField?.type_label || slot.value_type || slot.type_label}</span>{' '}</>
                    )}
                    <span className="text-gray-900 font-medium">{singlePackedField?.name || variableDisplayName}</span>
                    {variableLabel && (
                      <span className="text-gray-400 ml-1">({variableLabel})</span>
                    )}
                  </span>
                ) : null}
              </span>
            </HoverCard>
          </td>

          <td className={cn('px-1 py-0.5 align-top', isFirst && 'pt-2')}>
            {(() => {
              // Use packed field values if single packed field without struct
              const beforeDecoded = singlePackedField ? singlePackedField.before.value_decoded : slot.before.value_decoded;
              const afterDecoded = singlePackedField ? singlePackedField.after.value_decoded : slot.after.value_decoded;
              const isInitialZero = initialValue === '0' || initialValue === 'false' || isZeroValue(slot.before.value_encoded, beforeDecoded);
              const isFinalZero = finalValue === '0' || finalValue === 'false' || isZeroValue(slot.after.value_encoded, afterDecoded);

              return (
                <div className="flex flex-col">
                  <div className={cn('text-xs font-mono leading-tight flex items-center gap-1', isInitialZero ? 'text-gray-300' : 'text-gray-500')}>
                    <HoverCell
                      display={initialValue}
                      {...makeHoverProps(beforeDecoded, slot.before.value_encoded)}
                      chainId={chainId}
                      colorClass={cn('text-xs font-mono', isInitialZero ? 'text-gray-300' : 'text-gray-500')}
                      forceActions
                    />
                    <span className="text-gray-400">→</span>
                  </div>
                  <div className={cn('text-xs font-mono leading-tight', isFinalZero ? 'text-gray-300' : 'text-gray-900')}>
                    <HoverCell
                      display={finalValue}
                      {...makeHoverProps(afterDecoded, slot.after.value_encoded)}
                      chainId={chainId}
                      colorClass={cn('text-xs font-mono', isFinalZero ? 'text-gray-300' : 'text-gray-900')}
                      forceActions
                    />
                  </div>
                </div>
              );
            })()}
          </td>

          <td className={cn('px-1 py-0.5 w-8 align-top', isFirst && 'pt-2')}>
            <HoverCard content={<div className="font-mono text-xs text-gray-100 break-all">{slot.slot}</div>} position="top">
              <HoverCell
                display={slotNumber}
                value={slot.slot}
                colorClass="text-xs text-gray-500 font-mono"
                forceActions
              />
            </HoverCard>
          </td>

          {showStep && (
            <td className={cn('px-1 py-0.5 text-right w-8 align-top', isFirst && 'pt-2')}>
              {firstStep !== null && firstStep !== undefined && (
                <HoverCard content={<div className="font-mono text-[10px] text-gray-100">Step: {firstStep}</div>} position="top">
                  <span className="text-[10px] text-gray-400 font-mono cursor-default">
                    {firstStep}
                  </span>
                </HoverCard>
              )}
            </td>
          )}
        </tr>
      )}

      {/* Expanded interim changes rows */}
      {expanded && hasInterimChanges && slot.changes.map((change, idx) => {
        const isFirstChange = idx === 0;

        // For packed struct slots, use tree-structured display
        if (hasPacked && slot.packed_fields && slot.packed_fields.length > 0) {
          return (
            <InterimPackedChangeRows
              key={idx}
              change={change}
              changeIndex={idx}
              totalChanges={slot.changes.length}
              packedFields={slot.packed_fields}
              chainId={chainId}
              showStep={showStep}
              isFirstChange={isFirstChange}
            />
          );
        }

        // Non-packed: existing flat display
        const oldVal = getDisplayValue(change.before.value_decoded, change.before.value_encoded);
        const newVal = getDisplayValue(change.after.value_decoded, change.after.value_encoded);

        return (
          <tr key={idx} className={cn('bg-gray-100/80', !isFirstChange && 'border-t border-gray-300')}>
            <td className="pl-3 py-0.5 align-top" />
            <td className="pl-3 py-0.5 align-top">
              <span className="text-[10px] text-gray-400">{idx + 1}/{slot.changes.length}</span>
            </td>
            <td className="pl-3 py-0.5 align-top">
              <div className="flex flex-col">
                <div className={cn('text-xs font-mono leading-tight flex items-center gap-1', isZeroValue(change.before.value_encoded, change.before.value_decoded) ? 'text-gray-300' : 'text-gray-500')}>
                  <HoverCell
                    display={oldVal}
                    {...makeHoverProps(change.before.value_decoded, change.before.value_encoded)}
                    chainId={chainId}
                    colorClass={cn('text-xs font-mono', isZeroValue(change.before.value_encoded, change.before.value_decoded) ? 'text-gray-300' : 'text-gray-500')}
                  />
                  <span className="text-gray-400">→</span>
                </div>
                <div className={cn('text-xs font-mono leading-tight', isZeroValue(change.after.value_encoded, change.after.value_decoded) ? 'text-gray-300' : 'text-gray-900')}>
                  <HoverCell
                    display={newVal}
                    {...makeHoverProps(change.after.value_decoded, change.after.value_encoded)}
                    chainId={chainId}
                    colorClass={cn('text-xs font-mono', isZeroValue(change.after.value_encoded, change.after.value_decoded) ? 'text-gray-300' : 'text-gray-900')}
                  />
                </div>
              </div>
            </td>
            <td className="px-1 py-0.5 align-top" />
            {showStep && (
              <td className="px-1 py-0.5 text-right align-top">
                {change.step !== null && change.step !== undefined && (
                  <span className="text-[10px] text-gray-400 font-mono">
                    {change.step}
                  </span>
                )}
              </td>
            )}
          </tr>
        );
      })}
    </>
  );
}
