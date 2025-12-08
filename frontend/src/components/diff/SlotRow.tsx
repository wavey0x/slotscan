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
}

// Helper to check if a packed field has changed
const hasFieldChanged = (f: PackedFieldResponse): boolean => {
  const initialDisplay = f.initial_display ?? formatDecodedValue(f.initial_decoded);
  const finalDisplay = f.final_display ?? formatDecodedValue(f.final_decoded);
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
const isZeroValue = (raw: string, decoded: unknown): boolean => {
  // Check raw hex
  if (raw === '0x' + '0'.repeat(64)) return true;
  if (raw === '0x0' || raw === '0x00') return true;
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

// Render packed field NAMES in VARIABLE column (just type + name, no values)
const PackedFieldsVariableDisplay = ({
  fields,
}: {
  fields: PackedFieldResponse[];
}) => {
  const changedFields = getChangedPackedFields(fields);

  return (
    <div className="space-y-0.5">
      {changedFields.map((f, idx) => (
        <div key={idx} className="text-xs font-mono leading-tight">
          <span className="text-gray-400 mr-0.5">↳</span>
          <span className="text-gray-400">{f.type_label}</span>{' '}
          <span className="text-gray-900 font-medium">{f.name}</span>
        </div>
      ))}
    </div>
  );
};

// Render packed field VALUES in VALUE column (before on line 1, after on line 2)
const PackedFieldsValueDisplay = ({
  fields,
  chainId,
  initialRaw,
  finalRaw,
}: {
  fields: PackedFieldResponse[];
  chainId: string;
  initialRaw: string;
  finalRaw: string;
}) => {
  const changedFields = getChangedPackedFields(fields);

  return (
    <div className="space-y-0.5">
      {changedFields.map((f, idx) => {
        const initialDisplay = f.initial_display ?? formatDecodedValue(f.initial_decoded);
        const finalDisplay = f.final_display ?? formatDecodedValue(f.final_decoded);
        const isInitialZero = initialDisplay === '0' || initialDisplay === 'false';
        const isFinalZero = finalDisplay === '0' || finalDisplay === 'false';
        return (
          <div key={idx} className="space-y-0">
            <div className={cn('text-xs font-mono leading-tight flex items-center gap-1', isInitialZero ? 'text-gray-300' : 'text-gray-500')}>
              <HoverCell
                display={initialDisplay}
                {...makeHoverProps(
                  f.initial_decoded,
                  f.initial_display ?? initialDisplay,
                  initialRaw
                )}
                chainId={chainId}
                colorClass={cn('text-xs font-mono', isInitialZero ? 'text-gray-300' : 'text-gray-500')}
                forceActions
              />
              <span className="text-gray-400">→</span>
            </div>
            <div className={cn('text-xs font-mono leading-tight', isFinalZero ? 'text-gray-300' : 'text-gray-900')}>
              <HoverCell
                display={finalDisplay}
                {...makeHoverProps(
                  f.final_decoded,
                  f.final_display ?? finalDisplay,
                  finalRaw
                )}
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

const makeHoverProps = (decoded: unknown, display: string | null, raw: string) => {
  return {
    value: decoded !== null && decoded !== undefined ? getCopyValue(decoded, display ?? raw, raw) : (display ?? raw),
    tooltip: getTooltipValue(decoded, display ?? raw, raw),
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
                      {...makeHoverProps(beforeVal, beforeDisplay, '')}
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
                    {...makeHoverProps(afterVal, afterDisplay, '')}
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

  const getDisplayValue = (
    display: string | null,
    decoded: unknown,
    raw: string
  ): string => {
    if (showHex) return raw;
    if (display) return formatDecodedValue(display);
    if (decoded !== null && decoded !== undefined) return formatDecodedValue(decoded);
    return raw;
  };

  // Use packed fields display if available and not in hex mode
  const initialValue = getDisplayValue(slot.initial_display, slot.initial_decoded, slot.initial_raw);
  const finalValue = getDisplayValue(slot.final_display, slot.final_decoded, slot.final_raw);
  const structInitial = isPlainObject(slot.initial_decoded) ? (slot.initial_decoded as Record<string, unknown>) : null;
  const structFinal = isPlainObject(slot.final_decoded) ? (slot.final_decoded as Record<string, unknown>) : null;

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

  // Render packed fields tooltip showing ALL fields with their values
  const renderPackedFieldsTooltip = (fields: PackedFieldResponse[]) => (
    <div className="space-y-1 font-mono text-[10px]">
      {fields.map((f, idx) => {
        const changed = hasFieldChanged(f);
        const initialDisplay = f.initial_display ?? formatDecodedValue(f.initial_decoded);
        const finalDisplay = f.final_display ?? formatDecodedValue(f.final_decoded);
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
            <span className="text-gray-500">=</span>
            {changed ? (
              <>
                <span className="text-red-400">{initialDisplay}</span>
                <span className="text-gray-500">→</span>
                <span className="text-green-400">{finalDisplay}</span>
              </>
            ) : (
              <span className="text-gray-400">{finalDisplay}</span>
            )}
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
        <td className="px-1 py-0.5 w-5">
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

        <td className="px-1 py-0.5 align-top w-48 whitespace-normal">
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
                <div className="text-xs font-mono leading-tight">
                  <span className="text-gray-400 mr-0.5">↳</span>
                  <span className="text-gray-400">
                    {slot.struct_definition.members.find(m => m.name === slot.struct_field)?.type_label}
                  </span>{' '}
                  <span className="text-gray-900 font-medium">{slot.struct_field}</span>
                </div>
              ) : slot.is_mapping && !slot.struct_definition?.name && slot.value_type ? (
                /* Mapping value type line (for simple mappings) */
                <div className="text-xs font-mono leading-tight">
                  <span className="text-gray-400 mr-0.5">↳</span>
                  <span className="text-gray-400">{slot.value_type}</span>
                </div>
              ) : !slot.struct_definition?.name && !slot.is_mapping ? (
                /* Regular variable (no struct, no mapping) */
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
              {/* Packed field names (shown in VARIABLE column) */}
              {hasPacked && (
                <PackedFieldsVariableDisplay fields={slot.packed_fields!} />
              )}
            </div>
          </HoverCard>
        </td>

        <td className="px-1 py-0.5 align-top">
          {hasPacked && !showHex ? (
            <PackedFieldsValueDisplay fields={slot.packed_fields!} chainId={chainId} initialRaw={slot.initial_raw} finalRaw={slot.final_raw} />
          ) : (structInitial || structFinal) && !showHex ? (
            <StructDiffDisplay initial={structInitial} final={structFinal} chainId={chainId} structDefinition={slot.struct_definition} />
          ) : (
            <div className="space-y-0">
              <div className={cn('text-xs font-mono leading-tight flex items-center gap-1', isZeroValue(slot.initial_raw, slot.initial_decoded) ? 'text-gray-300' : 'text-gray-500')}>
                <HoverCell
                  display={initialValue}
                  {...makeHoverProps(
                    slot.initial_decoded,
                    slot.initial_display ?? slot.initial_raw,
                    slot.initial_raw
                  )}
                  chainId={chainId}
                  colorClass={cn('text-xs font-mono', isZeroValue(slot.initial_raw, slot.initial_decoded) ? 'text-gray-300' : 'text-gray-500')}
                  forceActions
                />
                <span className="text-gray-400">→</span>
              </div>
              <div className={cn('text-xs font-mono leading-tight', isZeroValue(slot.final_raw, slot.final_decoded) ? 'text-gray-300' : 'text-gray-900')}>
                <HoverCell
                  display={finalValue}
                  {...makeHoverProps(
                    slot.final_decoded,
                    slot.final_display ?? slot.final_raw,
                    slot.final_raw
                  )}
                  chainId={chainId}
                  colorClass={cn('text-xs font-mono', isZeroValue(slot.final_raw, slot.final_decoded) ? 'text-gray-300' : 'text-gray-900')}
                  forceActions
                />
              </div>
            </div>
          )}
        </td>

        <td className="px-1 py-0.5 w-8">
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
          <td className="px-1 py-0.5 text-right w-8">
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
          const oldVal = getDisplayValue(change.old_display, change.old_decoded, change.old_raw);
          const newVal = getDisplayValue(change.new_display, change.new_decoded, change.new_raw);
          const changeStructOld = isPlainObject(change.old_decoded) ? (change.old_decoded as Record<string, unknown>) : null;
          const changeStructNew = isPlainObject(change.new_decoded) ? (change.new_decoded as Record<string, unknown>) : null;
          const isFirst = idx === 0;

          return (
            <tr key={idx} className={cn('bg-gray-100/80', !isFirst && 'border-t border-gray-300')}>
              <td className="px-1 py-0.5" />
              <td className="px-1 py-0.5">
                <span className="text-[10px] text-gray-400 pl-1">{idx + 1}/{slot.changes.length}</span>
              </td>
              <td className="px-1 py-0.5">
                {(changeStructOld || changeStructNew) && !showHex ? (
                  <StructDiffDisplay initial={changeStructOld} final={changeStructNew} chainId={chainId} structDefinition={slot.struct_definition} />
                ) : (
                  <div className="space-y-0">
                    <div className={cn('text-xs font-mono leading-tight flex items-center gap-1', isZeroValue(change.old_raw, change.old_decoded) ? 'text-gray-300' : 'text-gray-500')}>
                      <HoverCell
                        display={oldVal}
                        {...makeHoverProps(
                          change.old_decoded,
                          change.old_display ?? change.old_raw,
                          change.old_raw
                        )}
                        chainId={chainId}
                        colorClass={cn('text-xs font-mono', isZeroValue(change.old_raw, change.old_decoded) ? 'text-gray-300' : 'text-gray-500')}
                      />
                      <span className="text-gray-400">→</span>
                    </div>
                    <div className={cn('text-xs font-mono leading-tight', isZeroValue(change.new_raw, change.new_decoded) ? 'text-gray-300' : 'text-gray-900')}>
                      <HoverCell
                        display={newVal}
                        {...makeHoverProps(
                          change.new_decoded,
                          change.new_display ?? change.new_raw,
                          change.new_raw
                        )}
                        chainId={chainId}
                        colorClass={cn('text-xs font-mono', isZeroValue(change.new_raw, change.new_decoded) ? 'text-gray-300' : 'text-gray-900')}
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
