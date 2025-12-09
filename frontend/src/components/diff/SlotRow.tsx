'use client';

import { useState } from 'react';
import { SlotChangeResponse, PackedFieldResponse, StructDefinitionResponse } from '@/lib/types';
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
    // Render objects as multiline fields instead of compact JSON
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

// Helper to check if a value represents zero (handles various formats)
const isZeroValue = (encoded: string, decoded: unknown): boolean => {
  // Check raw hex
  if (encoded === '0x' + '0'.repeat(64)) return true;
  if (encoded === '0x0' || encoded === '0x00') return true;
  // Check decoded value
  if (decoded === 0 || decoded === '0' || decoded === BigInt(0)) return true;
  if (decoded === null || decoded === undefined) return false;
  // Check string representation
  const str = String(decoded);
  return str === '0' || str === '0x0' || /^0x0+$/.test(str);
};

// Get changed packed fields
const getChangedPackedFields = (fields: PackedFieldResponse[]): PackedFieldResponse[] => {
  return fields.filter(hasFieldChanged);
};

// Render packed field NAMES in VARIABLE column with tree-style hierarchy
// Each field takes 2 lines of height to align with the 2-line value display
// Uses continuous vertical line (│) connecting all fields
const PackedFieldsVariableDisplay = ({
  fields,
}: {
  fields: PackedFieldResponse[];
}) => {
  const changedFields = getChangedPackedFields(fields);
  const lastIdx = changedFields.length - 1;

  return (
    <div>
      {changedFields.map((f, idx) => {
        const isLast = idx === lastIdx;
        // Use ├ for middle items, └ for last item
        const branchGlyph = isLast ? '└' : '├';
        // Use │ for continuation line, empty space for last item
        const continuationGlyph = isLast ? ' ' : '│';
        return (
          <div key={idx} className={cn(!isLast && "border-b border-gray-100")}>
            {/* Line 1: branch glyph + field name */}
            <div className="text-xs font-mono leading-tight flex items-start">
              <span className="text-gray-300 select-none w-3">{branchGlyph}</span>
              <span>
                <span className="text-gray-400">{f.type_label}</span>{' '}
                <span className="text-gray-900 font-medium">{f.name}</span>
              </span>
            </div>
            {/* Line 2: continuation line or spacer */}
            <div className="text-xs font-mono leading-tight">
              <span className="text-gray-300 select-none w-3 inline-block">{continuationGlyph}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
};

// Render packed field VALUES in VALUE column (before on line 1, after on line 2)
// headerText is used to create an invisible spacer that matches the variable column header
const PackedFieldsValueDisplay = ({
  fields,
  chainId,
  initialEncoded,
  finalEncoded,
  headerText,
}: {
  fields: PackedFieldResponse[];
  chainId: string;
  initialEncoded: string;
  finalEncoded: string;
  headerText?: string;
}) => {
  const changedFields = getChangedPackedFields(fields);
  const lastIdx = changedFields.length - 1;

  return (
    <div>
      {/* Invisible spacer matching the variable column header (same text = same wrapping) */}
      {headerText && (
        <div className="text-xs font-mono leading-tight pb-0.5 border-b border-transparent break-words invisible">
          {headerText}
        </div>
      )}
      {changedFields.map((f, idx) => {
        const initialDisplay = formatDecodedValue(f.before.value_decoded);
        const finalDisplay = formatDecodedValue(f.after.value_decoded);
        const isInitialZero = initialDisplay === '0' || initialDisplay === 'false';
        const isFinalZero = finalDisplay === '0' || finalDisplay === 'false';
        const isLast = idx === lastIdx;
        return (
          <div key={idx} className={cn(!isLast && "border-b border-gray-100")}>
            {/* Line 1: before value with arrow */}
            <div className={cn('text-xs font-mono leading-tight flex items-center gap-1', isInitialZero ? 'text-gray-300' : 'text-gray-500')}>
              <HoverCell
                display={initialDisplay}
                {...makeHoverProps(f.before.value_decoded, initialEncoded)}
                chainId={chainId}
                colorClass={cn('text-xs font-mono', isInitialZero ? 'text-gray-300' : 'text-gray-500')}
                forceActions
              />
              <span className="text-gray-400">→</span>
            </div>
            {/* Line 2: after value */}
            <div className={cn('text-xs font-mono leading-tight', isFinalZero ? 'text-gray-300' : 'text-gray-900')}>
              <HoverCell
                display={finalDisplay}
                {...makeHoverProps(f.after.value_decoded, finalEncoded)}
                chainId={chainId}
                colorClass={cn('text-xs font-mono', isFinalZero ? 'text-gray-300' : 'text-gray-900')}
                forceActions
              />
            </div>
          </div>
        );
      })}
    </div>
  );
};

const isPlainObject = (val: unknown): val is Record<string, unknown> =>
  val !== null && typeof val === 'object' && !Array.isArray(val);

const makeHoverProps = (decoded: unknown, encoded: string) => {
  return {
    value: decoded !== null && decoded !== undefined ? getCopyValue(decoded, encoded) : encoded,
    tooltip: getTooltipValue(decoded, encoded),
  };
};

const guessTypeLabel = (v: unknown): string => {
  if (typeof v === 'string') {
    if (/^0x[a-fA-F0-9]{40}$/.test(v)) return 'address';
    if (/^0x[a-fA-F0-9]+$/.test(v)) return 'bytes';
    return 'string';
  }
  if (typeof v === 'number' || typeof v === 'bigint') return 'uint256';
  if (typeof v === 'boolean') return 'bool';
  return '';
};

const StructDiffDisplay = ({
  initial,
  final,
  chainId,
  structDefinition,
}: {
  initial: Record<string, unknown> | null;
  final: Record<string, unknown> | null;
  chainId: string;
  structDefinition?: StructDefinitionResponse | null;
}) => {
  const [expanded, setExpanded] = useState(false);

  // Use struct definition member order if available, otherwise use object keys
  const keys = structDefinition
    ? structDefinition.members.map((m) => m.name)
    : Array.from(new Set([...(initial ? Object.keys(initial) : []), ...(final ? Object.keys(final) : [])]));

  // Build a map from member name to type_label from struct definition
  const memberTypeMap = new Map(
    structDefinition?.members.map((m) => [m.name, m.type_label]) ?? []
  );

  // Pre-compute all display values
  const fieldData = keys.map((key) => {
    const beforeVal = initial ? initial[key] : undefined;
    const afterVal = final ? final[key] : undefined;
    // Use actual type from struct definition, fall back to guessing only if not available
    const typeLabel = memberTypeMap.get(key) ?? guessTypeLabel(afterVal ?? beforeVal);
    // Show "—" for missing values (value not fetched, could be anything)
    const beforeDisplay = beforeVal !== undefined ? formatDecodedValue(beforeVal) : '—';
    const afterDisplay = afterVal !== undefined ? formatDecodedValue(afterVal) : '—';
    return { key, typeLabel, beforeVal, afterVal, beforeDisplay, afterDisplay };
  });

  // Calculate max widths for vertical alignment of values
  const maxTypeWidth = Math.max(...fieldData.map((f) => f.typeLabel.length), 0);
  const maxNameWidth = Math.max(...fieldData.map((f) => f.key.length), 0);

  return (
    <div className="space-y-0.5">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="text-[10px] text-gray-500 font-mono flex items-center gap-1 hover:text-gray-800"
      >
        <span className="w-3 inline-block text-center">{expanded ? '−' : '+'}</span>
        <span>struct ({keys.length} {keys.length === 1 ? 'field' : 'fields'})</span>
      </button>
      {expanded && (
        <div className="space-y-0.5">
          {fieldData.map(({ key, typeLabel, beforeVal, afterVal, beforeDisplay, afterDisplay }) => {
            const isZeroBefore = beforeDisplay === '0' || beforeDisplay === 'false' || beforeDisplay === '0x0000000000000000000000000000000000000000';
            const isZeroAfter = afterDisplay === '0' || afterDisplay === 'false' || afterDisplay === '0x0000000000000000000000000000000000000000';
            const hasChanged = beforeDisplay !== afterDisplay;

            return (
              <div key={key} className="text-xs font-mono leading-tight">
                {/* Line 1: type + name (fixed width) + before value + arrow */}
                <div className="flex items-baseline">
                  <span className="text-gray-400" style={{ width: `${maxTypeWidth}ch`, marginRight: '0.5ch' }}>
                    {typeLabel}
                  </span>
                  <span className="text-gray-600" style={{ width: `${maxNameWidth}ch`, marginRight: '0.5ch' }}>
                    {key}
                  </span>
                  <span className={cn(isZeroBefore ? 'text-gray-300' : 'text-gray-500')}>
                    <HoverCell
                      display={beforeDisplay}
                      {...makeHoverProps(beforeVal, '')}
                      chainId={chainId}
                      colorClass={cn('text-xs font-mono', isZeroBefore ? 'text-gray-300' : 'text-gray-500')}
                      forceActions
                    />
                  </span>
                  <span className="text-gray-400 mx-1">→</span>
                </div>
                {/* Line 2: after value (indented to align with before values) */}
                <div
                  className={cn(isZeroAfter ? 'text-gray-300' : hasChanged ? 'text-gray-900' : 'text-gray-500')}
                  style={{ marginLeft: `${maxTypeWidth + maxNameWidth + 1}ch` }}
                >
                  <HoverCell
                    display={afterDisplay}
                    {...makeHoverProps(afterVal, '')}
                    chainId={chainId}
                    colorClass={cn('text-xs font-mono', isZeroAfter ? 'text-gray-300' : hasChanged ? 'text-gray-900' : 'text-gray-500')}
                    forceActions
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export function SlotRow({
  slot,
  showHex,
  chainId,
  showStep = true,
  isFirst = false,
}: SlotRowProps) {
  const [expanded, setExpanded] = useState(false);
  const hasInterimChanges = slot.changes.length > 1;
  const hasPacked = slot.packed_fields && slot.packed_fields.length > 1;
  const hasParams = slot.params && slot.params.length > 0;
  const isDynamicArray = slot.is_dynamic_array && slot.array_index !== null;
  // Show expand button only for interim changes (params/array moved to HoverCard)
  const canExpand = hasInterimChanges;

  const variableName = slot.variable_name || formatSlotShort(slot.slot, 4);

  // Extract label from variable_path if present (e.g., "rewards (array length)" -> "array length")
  const variableLabel = (() => {
    if (!slot.variable_path) return null;
    const match = slot.variable_path.match(/\(([^)]+)\)$/);
    return match ? match[1] : null;
  })();

  // Format slot number for the SLOT column
  // Non-hex mode: show decimal up to 999, then abbreviate aggressively
  // Hex mode: show hex, max 6 chars including 0x (e.g., 0x3e7, 0xa..)
  const formatSlotNumber = (slotHex: string): string => {
    try {
      const slotBigInt = BigInt(slotHex);

      if (showHex) {
        // Hex mode: max 6 chars including "0x" = 4 hex digits
        const hexStr = slotBigInt.toString(16);
        if (hexStr.length <= 4) {
          return '0x' + hexStr;
        }
        // Abbreviate: 0x + first 2 chars + ..
        return '0x' + hexStr.slice(0, 2) + '..';
      } else {
        // Non-hex mode: show decimal up to 999
        if (slotBigInt <= BigInt(999)) {
          return slotBigInt.toString();
        }
        // For large numbers, show abbreviated hex (max 6 chars)
        const hexStr = slotBigInt.toString(16);
        if (hexStr.length <= 4) {
          return '0x' + hexStr;
        }
        return '0x' + hexStr.slice(0, 2) + '..';
      }
    } catch {
      // Fallback for invalid input
      return formatSlotShort(slotHex, 4);
    }
  };
  const slotNumber = formatSlotNumber(slot.slot);

  const getDisplayValue = (decoded: unknown, encoded: string): string => {
    if (showHex) return encoded;
    if (decoded !== null && decoded !== undefined) return formatDecodedValue(decoded);
    return encoded;
  };

  // Use packed fields display if available and not in hex mode
  const initialValue = getDisplayValue(slot.before.value_decoded, slot.before.value_encoded);
  const finalValue = getDisplayValue(slot.after.value_decoded, slot.after.value_encoded);
  const structInitial = isPlainObject(slot.before.value_decoded) ? (slot.before.value_decoded as Record<string, unknown>) : null;
  const structFinal = isPlainObject(slot.after.value_decoded) ? (slot.after.value_decoded as Record<string, unknown>) : null;

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

  // Get the first step for the slot (from first change) - execution order
  const firstStep = slot.changes.length > 0 ? slot.changes[0].step : null;

  // Render struct definition with highlighted modified member
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

  // Render packed fields tooltip showing field types and names (no values)
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

  // Determine if we should show type_label (skip when redundant with struct/packed)
  const hasStructInfo = !!slot.struct_definition;
  const showTypeLabel = slot.type_label && !hasStructInfo && !hasPacked;

  // HoverCard content shows detailed variable info in a larger, interactive card
  const variableHoverContent = (
    <div className="space-y-2 min-w-[280px]">
      {/* Header: Variable name */}
      {slot.variable_name && (
        <div className="font-medium text-gray-100 text-sm">
          {slot.variable_name}
        </div>
      )}

      {/* Slot - just the hex for copying (decimal already in SLOT column) */}
      <HoverCardSection title="Slot">
        <div className="font-mono text-xs text-gray-300 break-all select-all">
          {slot.slot}
        </div>
      </HoverCardSection>

      {/* Type information - only show when not redundant with struct/packed */}
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

      {/* Value type for mappings - only when different and useful */}
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

      {/* Struct definition */}
      {slot.struct_definition && (
        <>
          <HoverCardDivider />
          {renderStructDefinition(slot.struct_definition, slot.struct_field)}
        </>
      )}

      {/* Packed fields info */}
      {hasPacked && slot.packed_fields && (
        <>
          <HoverCardDivider />
          <HoverCardSection title="Packed Fields">
            {renderPackedFieldsTooltip(slot.packed_fields)}
          </HoverCardSection>
        </>
      )}

      {/* Dynamic array index - interactive with copy */}
      {isDynamicArray && (
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

      {/* Mapping params - interactive with copy */}
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

  return (
    <>
      <tr className={cn('hover:bg-gray-50/50', expanded && 'bg-gray-50/30')}>
        <td className={cn('px-1 py-0.5 w-5', isFirst && 'pt-2')}>
          {canExpand ? (
            <button
              onClick={() => setExpanded(!expanded)}
              className="w-4 h-4 flex items-center justify-center text-gray-400 hover:text-gray-700 text-xs font-mono leading-none"
            >
              {expanded ? '−' : '+'}
            </button>
          ) : (
            <span className="w-4 h-4 inline-block" />
          )}
        </td>

        <td className={cn('px-1 py-0.5 align-top w-48 whitespace-normal', isFirst && 'pt-2')}>
          <HoverCard content={variableHoverContent} delay={200} maxWidth="max-w-sm">
            <div className="space-y-0 break-words">
              {/* Top line: struct type + variable name (for struct mappings) */}
              {slot.struct_definition?.name && (
                <div className="text-xs font-mono leading-tight">
                  <span className="text-gray-400">{slot.struct_definition.name}</span>{' '}
                  <span className="text-gray-900 font-medium">{slot.variable_name}</span>
                </div>
              )}
              {/* Top line for simple mappings (no struct): show variable name */}
              {slot.is_mapping && !slot.struct_definition?.name && slot.variable_name && (
                <div className="text-xs font-mono leading-tight">
                  <span className="text-gray-900 font-medium">{slot.variable_name}</span>
                </div>
              )}
              {/* Bottom line: member type + member name (for struct fields) */}
              {slot.struct_field && slot.struct_definition ? (
                <div className="text-xs font-mono leading-tight flex items-start">
                  <span className="text-gray-300 mr-1 select-none">└</span>
                  <span>
                    <span className="text-gray-400">
                      {slot.struct_definition.members.find(m => m.name === slot.struct_field)?.type_label}
                    </span>{' '}
                    <span className="text-gray-900 font-medium">{slot.struct_field}</span>
                  </span>
                </div>
              ) : slot.is_mapping && !slot.struct_definition?.name && slot.value_type ? (
                /* Mapping value type line (for simple mappings) */
                <div className="text-xs font-mono leading-tight flex items-start">
                  <span className="text-gray-300 mr-1 select-none">└</span>
                  <span className="text-gray-400">{slot.value_type}</span>
                </div>
              ) : !slot.struct_definition?.name && !slot.is_mapping && !hasPacked ? (
                /* Regular variable (no struct, no mapping, no packed) */
                <div className="text-xs font-mono leading-tight">
                  {(slot.value_type || slot.type_label) && (
                    <><span className="text-gray-400">{slot.value_type || slot.type_label}</span>{' '}</>
                  )}
                  <span className="text-gray-900 font-medium">{variableName}</span>
                  {variableLabel && (
                    <span className="text-gray-400 ml-1">({variableLabel})</span>
                  )}
                </div>
              ) : null}
              {/* Packed field names - shown INSTEAD of variable name for packed slots */}
              {hasPacked && (
                <PackedFieldsVariableDisplay fields={slot.packed_fields!} />
              )}
            </div>
          </HoverCard>
        </td>

        <td className={cn('px-1 py-0.5 align-top', isFirst && 'pt-2')}>
          {hasPacked && !showHex ? (
            <PackedFieldsValueDisplay
              fields={slot.packed_fields!}
              chainId={chainId}
              initialEncoded={slot.before.value_encoded}
              finalEncoded={slot.after.value_encoded}
              headerText={slot.struct_definition?.name ? `${slot.struct_definition.name} ${slot.variable_name || ''}` : undefined}
            />
          ) : (structInitial || structFinal) && !showHex ? (
            <StructDiffDisplay initial={structInitial} final={structFinal} chainId={chainId} structDefinition={slot.struct_definition} />
          ) : (
            <div className="space-y-0">
              <div className={cn('text-xs font-mono leading-tight flex items-center gap-1', isZeroValue(slot.before.value_encoded, slot.before.value_decoded) ? 'text-gray-300' : 'text-gray-500')}>
                <HoverCell
                  display={initialValue}
                  {...makeHoverProps(slot.before.value_decoded, slot.before.value_encoded)}
                  chainId={chainId}
                  colorClass={cn('text-xs font-mono', isZeroValue(slot.before.value_encoded, slot.before.value_decoded) ? 'text-gray-300' : 'text-gray-500')}
                  forceActions
                />
                <span className="text-gray-400">→</span>
              </div>
              <div className={cn('text-xs font-mono leading-tight', isZeroValue(slot.after.value_encoded, slot.after.value_decoded) ? 'text-gray-300' : 'text-gray-900')}>
                <HoverCell
                  display={finalValue}
                  {...makeHoverProps(slot.after.value_decoded, slot.after.value_encoded)}
                  chainId={chainId}
                  colorClass={cn('text-xs font-mono', isZeroValue(slot.after.value_encoded, slot.after.value_decoded) ? 'text-gray-300' : 'text-gray-900')}
                  forceActions
                />
              </div>
            </div>
          )}
        </td>

        <td className={cn('px-1 py-0.5 w-8', isFirst && 'pt-2')}>
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
          <td className={cn('px-1 py-0.5 text-right w-8', isFirst && 'pt-2')}>
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

      {/* Expanded interim changes rows */}
      {expanded && hasInterimChanges && slot.changes.map((change, idx) => {
          const oldVal = getDisplayValue(change.before.value_decoded, change.before.value_encoded);
          const newVal = getDisplayValue(change.after.value_decoded, change.after.value_encoded);
          const changeStructOld = isPlainObject(change.before.value_decoded) ? (change.before.value_decoded as Record<string, unknown>) : null;
          const changeStructNew = isPlainObject(change.after.value_decoded) ? (change.after.value_decoded as Record<string, unknown>) : null;
          const isFirstChange = idx === 0;

          return (
            <tr key={idx} className={cn('bg-gray-100/80', !isFirstChange && 'border-t border-gray-300')}>
              <td className="pl-3 py-0.5" />
              <td className="pl-3 py-0.5">
                <span className="text-[10px] text-gray-400">{idx + 1}/{slot.changes.length}</span>
              </td>
              <td className="pl-3 py-0.5">
                {(changeStructOld || changeStructNew) && !showHex ? (
                  <StructDiffDisplay initial={changeStructOld} final={changeStructNew} chainId={chainId} structDefinition={slot.struct_definition} />
                ) : (
                  <div className="space-y-0">
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
                )}
              </td>
              <td className="px-1 py-0.5" />
              {showStep && (
                <td className="px-1 py-0.5 text-right">
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
