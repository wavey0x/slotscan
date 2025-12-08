'use client';

import { useState } from 'react';
import { SlotChangeResponse, PackedFieldResponse, StructDefinitionResponse } from '@/lib/types';
import {
  cn,
  formatSlotShort,
  formatDecodedValue,
  truncateAddress,
  truncateHash,
} from '@/lib/utils';
import { HoverCell } from '@/components/ui/HoverCell';
import { Tooltip } from '@/components/ui/Tooltip';

interface SlotRowProps {
  slot: SlotChangeResponse;
  showHex: boolean;
  chainId: string;
}

// Helper to check if a packed field has changed
const hasFieldChanged = (f: PackedFieldResponse): boolean => {
  const initialDisplay = f.initial_display ?? formatDecodedValue(f.initial_decoded);
  const finalDisplay = f.final_display ?? formatDecodedValue(f.final_decoded);
  return initialDisplay !== finalDisplay;
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
}: {
  fields: PackedFieldResponse[];
  chainId: string;
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
                value={f.initial_decoded !== null ? String(f.initial_decoded) : initialDisplay}
                chainId={chainId}
                colorClass={cn('text-xs font-mono', isInitialZero ? 'text-gray-300' : 'text-gray-500')}
              />
              <span className="text-gray-400">→</span>
            </div>
            <div className={cn('text-xs font-mono leading-tight font-bold', isFinalZero ? 'text-gray-300' : 'text-gray-900')}>
              <HoverCell
                display={finalDisplay}
                value={f.final_decoded !== null ? String(f.final_decoded) : finalDisplay}
                chainId={chainId}
                colorClass={cn('text-xs font-mono font-bold', isFinalZero ? 'text-gray-300' : 'text-gray-900')}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
};

export function SlotRow({
  slot,
  showHex,
  chainId,
}: SlotRowProps) {
  const [expanded, setExpanded] = useState(false);
  const hasInterimChanges = slot.changes.length > 1;
  const hasPacked = slot.packed_fields && slot.packed_fields.length > 1;
  const hasParams = slot.params && slot.params.length > 0;
  // Show expand button if there are params or interim changes
  const canExpand = hasParams || hasInterimChanges;

  const variableName = slot.variable_name || formatSlotShort(slot.slot, 4);

  // Format slot number for the SLOT column
  // When HEX mode is on: always show abbreviated hex
  // When HEX mode is off: show decimal for small slots, abbreviated hex for large slots
  const formatSlotNumber = (slotHex: string): string => {
    if (showHex) {
      // HEX mode: always show abbreviated hex
      return formatSlotShort(slotHex, 4);
    }
    try {
      const slotBigInt = BigInt(slotHex);
      // Only show decimal for small static slots (< 100)
      if (slotBigInt < BigInt(100)) {
        return slotBigInt.toString();
      }
      // Always abbreviate large slots (keccak256 hashes) to short hex
      return formatSlotShort(slotHex, 4);
    } catch {
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

  // Get the first PC for the slot (from first change)
  const firstPc = slot.changes.length > 0 ? slot.changes[0].pc : null;

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

  // Tooltip shows the opposite of what's displayed: hex shows name, name shows hex
  const variableTooltip = (
    <div className="space-y-1.5 text-xs">
      {showHex ? (
        // When showing hex, tooltip shows variable name (if available)
        slot.variable_name && <div className="font-medium">{slot.variable_name}</div>
      ) : (
        // When showing name, tooltip shows full hex slot
        <div className="font-mono">{slot.slot}</div>
      )}
      {slot.type_label && <div className="text-gray-400">{slot.type_label}</div>}
      {slot.struct_definition && renderStructDefinition(slot.struct_definition, slot.struct_field)}
    </div>
  );

  return (
    <>
      <tr className={cn('hover:bg-gray-50 border-t border-gray-100', expanded && 'bg-gray-50')}>
        <td className="px-1 py-0.5 w-6">
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

        <td className="px-1 py-0.5 align-top">
          <Tooltip content={variableTooltip} position="bottom" delay={200}>
            <div className="space-y-0">
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
                  {slot.value_type && (
                    <><span className="text-gray-400">{slot.value_type}</span>{' '}</>
                  )}
                  <span className="text-gray-900 font-medium">{variableName}</span>
                </div>
              ) : null}
              {/* Packed field names (shown in VARIABLE column) */}
              {hasPacked && (
                <PackedFieldsVariableDisplay fields={slot.packed_fields!} />
              )}
            </div>
          </Tooltip>
        </td>

        <td className="px-1 py-0.5 align-top">
          {hasPacked && !showHex ? (
            <PackedFieldsValueDisplay fields={slot.packed_fields!} chainId={chainId} />
          ) : (
            <div className="space-y-0">
              <div className={cn('text-xs font-mono leading-tight flex items-center gap-1', isZeroValue(slot.initial_raw, slot.initial_decoded) ? 'text-gray-300' : 'text-gray-500')}>
                <HoverCell
                  display={initialValue}
                  value={slot.initial_decoded !== null ? String(slot.initial_decoded) : slot.initial_raw}
                  chainId={chainId}
                  colorClass={cn('text-xs font-mono', isZeroValue(slot.initial_raw, slot.initial_decoded) ? 'text-gray-300' : 'text-gray-500')}
                />
                <span className="text-gray-400">→</span>
              </div>
              <div className={cn('text-xs font-mono leading-tight font-bold', isZeroValue(slot.final_raw, slot.final_decoded) ? 'text-gray-300' : 'text-gray-900')}>
                <HoverCell
                  display={finalValue}
                  value={slot.final_decoded !== null ? String(slot.final_decoded) : slot.final_raw}
                  chainId={chainId}
                  colorClass={cn('text-xs font-mono font-bold', isZeroValue(slot.final_raw, slot.final_decoded) ? 'text-gray-300' : 'text-gray-900')}
                />
              </div>
            </div>
          )}
        </td>

        <td className="px-1 py-0.5">
          <Tooltip content={slot.slot} position="bottom" delay={200}>
            <span className="text-xs text-gray-500 font-mono">
              {slotNumber}
            </span>
          </Tooltip>
        </td>

        <td className="px-1 py-0.5 text-right">
          {firstPc !== null && (
            <span className="text-[10px] text-gray-400 font-mono">
              {firstPc}
            </span>
          )}
        </td>
      </tr>

      {/* Expanded details row - show mapping keys and other metadata */}
      {expanded && hasParams && (
        <tr className="bg-gray-50">
          <td className="px-1 py-0.5" />
          <td colSpan={4} className="px-1 py-1.5">
            <div className="pl-2 space-y-1">
              {/* Mapping Params Section */}
              <div className="flex items-start gap-2">
                <span className="text-[10px] text-gray-400 font-medium w-12 flex-shrink-0">
                  {slot.variable_name ? slot.variable_name : 'Params'}
                </span>
                <div className="space-y-0.5">
                  {slot.params!.map((param, idx) => {
                    const formatted = formatKey(param.value);
                    return (
                      <div key={idx} className="text-[10px] font-mono leading-tight flex items-center gap-1">
                        <span className="text-gray-400 w-16">{param.type}</span>
                        {formatted && (
                          <HoverCell
                            display={param.label || formatted.display}
                            value={formatted.full}
                            chainId={chainId}
                            colorClass="text-gray-600 text-[10px]"
                          />
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}

      {/* Expanded interim changes rows */}
      {expanded && hasInterimChanges && slot.changes.map((change, idx) => {
        const oldVal = getDisplayValue(change.old_display, change.old_decoded, change.old_raw);
        const newVal = getDisplayValue(change.new_display, change.new_decoded, change.new_raw);

        return (
          <tr key={idx} className="bg-blue-50/50">
            <td className="px-1 py-0.5 text-right">
              <span className="text-[10px] text-gray-400 font-mono">{change.step}</span>
            </td>
            <td className="px-1 py-0.5">
              <span className="text-[10px] text-gray-400 pl-1">{idx + 1}/{slot.changes.length}</span>
            </td>
            <td className="px-1 py-0.5">
              <div className="space-y-0">
                <div className={cn('text-xs font-mono leading-tight flex items-center gap-1', isZeroValue(change.old_raw, change.old_decoded) ? 'text-gray-300' : 'text-gray-500')}>
                  <HoverCell
                    display={oldVal}
                    value={change.old_decoded !== null ? String(change.old_decoded) : change.old_raw}
                    chainId={chainId}
                    colorClass={cn('text-xs font-mono', isZeroValue(change.old_raw, change.old_decoded) ? 'text-gray-300' : 'text-gray-500')}
                  />
                  <span className="text-gray-400">→</span>
                </div>
                <div className={cn('text-xs font-mono leading-tight font-bold', isZeroValue(change.new_raw, change.new_decoded) ? 'text-gray-300' : 'text-gray-900')}>
                  <HoverCell
                    display={newVal}
                    value={change.new_decoded !== null ? String(change.new_decoded) : change.new_raw}
                    chainId={chainId}
                    colorClass={cn('text-xs font-mono font-bold', isZeroValue(change.new_raw, change.new_decoded) ? 'text-gray-300' : 'text-gray-900')}
                  />
                </div>
              </div>
            </td>
            <td className="px-1 py-0.5" />
            <td className="px-1 py-0.5 text-right">
              {change.pc !== null && (
                <span className="text-[10px] text-gray-400 font-mono">
                  {change.pc}
                </span>
              )}
            </td>
          </tr>
        );
      })}
    </>
  );
}
