'use client';

/**
 * SlotRow - Renders a single storage slot change row
 *
 * Grouped slot summary. Display derivation, packed rows, and evidence detail are
 * deliberately kept in separate modules so this component owns only composition
 * and write-history expansion.
 */

import { useState } from 'react';
import { SlotChangeResponse } from '@/lib/types';
import {
  cn,
  valuesEqual,
} from '@/lib/utils';
import { HoverCell } from '@/components/ui/HoverCell';
import { DetailPopover } from '@/components/ui/DetailPopover';
import { isStructuredDecodedValue, StructuredValueDiff, ValueDiff } from './ValueDiff';
import { KeyedVariablePath } from './KeyedVariablePath';
import { StorageEvidenceDetail } from './StorageEvidenceDetail';
import { InterimPackedChangeRows, PackedFieldRow } from './PackedFieldRows';
import {
  deriveSlotDisplay,
  storageHoverProps,
  storageDisplayValue,
} from './slotDisplay';

interface SlotRowProps {
  slot: SlotChangeResponse;
  showHex: boolean;
  chainId: string;
  showStep?: boolean;
  isFirst?: boolean;
  isLast?: boolean;
}

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
  const {
    hasInterimChanges,
    hasPacked,
    variableDisplayName,
    variableLabel,
    hasKeyedVariablePath,
    resolvedLeafType,
    slotNumber,
    firstStep,
    displayedPackedFields,
    showPackedAsTree,
    singlePackedField,
    initialValue,
    finalValue,
    revertedWriteCount,
  } = deriveSlotDisplay(slot, showHex);
  const canExpand = hasInterimChanges;

  const revertedNotice = revertedWriteCount > 0 ? (
    <span className="inline-block mt-0.5 text-[9px] uppercase tracking-wide text-amber-600">
      {revertedWriteCount === 1 ? 'reverted write' : `${revertedWriteCount} reverted writes`}
    </span>
  ) : null;

  const variableDetail = <StorageEvidenceDetail slot={slot} chainId={chainId} />;

  // Expand button element
  const expandButton = (
    <button
      onClick={() => setExpanded(!expanded)}
      aria-label={expanded ? 'Collapse write history' : 'Expand write history'}
      aria-expanded={expanded}
      className="touch-hitbox w-4 h-4 flex items-center justify-center text-gray-400 hover:text-gray-700 text-xs font-mono leading-none"
    >
      {expanded ? '−' : '+'}
    </button>
  );

  return (
    <>
      {/* PACKED FIELDS: Struct header row (if has struct definition) */}
      {showPackedAsTree && slot.struct_definition?.name && (
        <tr className={cn('hover:bg-gray-50/50', expanded && 'bg-gray-50/30', slotBorderClass)}>
          <td className={cn('px-1 py-0.5 w-5 align-top', isFirst && 'pt-1')}>
            {canExpand ? expandButton : <span className="w-4 h-4 inline-block" />}
          </td>
          <td className={cn('px-1 py-0.5 align-top', isFirst && 'pt-1')} colSpan={2}>
            <DetailPopover content={variableDetail} delay={200} maxWidth="max-w-sm">
              <span className="text-xs font-mono leading-tight no-underline decoration-transparent">
                <span className="text-gray-400">{slot.struct_definition.name}</span>{' '}
                <span className="text-gray-900 font-medium">{slot.variable_name}</span>
              </span>
            </DetailPopover>
            {revertedNotice && <div>{revertedNotice}</div>}
          </td>
          <td className={cn('hidden px-1 py-0.5 w-8 align-top sm:table-cell', isFirst && 'pt-1')}>
            <DetailPopover content={<div className="font-mono text-xs text-gray-100 break-all">{slot.slot}</div>}>
              <HoverCell display={slotNumber} value={slot.slot} colorClass="text-xs text-gray-500 font-mono" />
            </DetailPopover>
          </td>
          {showStep && (
            <td className={cn('hidden px-1 py-0.5 text-right w-8 align-top sm:table-cell', isFirst && 'pt-1')}>
              {firstStep !== null && firstStep !== undefined && (
                <DetailPopover content={<div className="font-mono text-[10px] text-gray-100">Step: {firstStep}</div>}>
                  <span className="text-[10px] text-gray-400 font-mono cursor-default">
                    {firstStep}
                  </span>
                </DetailPopover>
              )}
            </td>
          )}
        </tr>
      )}

      {/* PACKED FIELDS: Individual field rows (only when showing as tree) */}
      {showPackedAsTree && !showHex && displayedPackedFields.map((field, idx) => (
        <PackedFieldRow
          key={idx}
          field={field}
          isLast={idx === displayedPackedFields.length - 1}
          totalFields={displayedPackedFields.length}
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
          <td className={cn('px-1 py-0.5 w-5 align-top', isFirst && 'pt-1')}>
            {canExpand ? expandButton : <span className="w-4 h-4 inline-block" />}
          </td>

          <td className={cn('px-1 py-0.5 align-top w-48 whitespace-normal', isFirst && 'pt-1')}>
            <DetailPopover content={variableDetail} delay={200} maxWidth="max-w-sm">
              {hasKeyedVariablePath && slot.variable_path ? (
                <KeyedVariablePath
                  path={slot.variable_path}
                  typeLabel={resolvedLeafType}
                  chainId={chainId}
                />
              ) : (
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
                      <span className="text-gray-900 font-medium">{variableDisplayName}</span>
                    </span>
                  )}
                  {/* Struct field member */}
                  {slot.struct_field && slot.struct_definition ? (
                    <span className="text-xs font-mono leading-tight flex items-start">
                      <span className="text-gray-300 mr-1 select-none">└</span>
                      <span>
                        <span className="text-gray-400">
                          {slot.struct_definition.members.find(m => m.name === slot.struct_field)?.type_label
                            || slot.value_type
                            || slot.type_label}
                        </span>{' '}
                        <span className="text-gray-900 font-medium">{variableDisplayName}</span>
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
              )}
            </DetailPopover>
            {revertedNotice && <div>{revertedNotice}</div>}
          </td>

          <td className={cn('px-1 py-0.5 align-top', isFirst && 'pt-1')}>
            {(() => {
              // Use packed field values if single packed field without struct
              const beforeDecoded = singlePackedField ? singlePackedField.before.value_decoded : slot.before.value_decoded;
              const afterDecoded = singlePackedField ? singlePackedField.after.value_decoded : slot.after.value_decoded;
              const unchanged = valuesEqual(beforeDecoded, afterDecoded);
              const afterClassName = unchanged ? 'text-gray-400' : 'text-gray-900';

              if (!showHex && isStructuredDecodedValue(beforeDecoded) && isStructuredDecodedValue(afterDecoded)) {
                return (
                  <StructuredValueDiff
                    before={beforeDecoded}
                    after={afterDecoded}
                    beforeClassName="text-gray-300"
                    afterClassName={unchanged ? 'text-gray-300' : 'text-gray-900'}
                  />
                );
              }

              return (
                <ValueDiff
                  unchanged={unchanged}
                  beforeClassName="text-gray-300"
                  afterClassName={afterClassName}
                  before={
                    <HoverCell
                      display={initialValue}
                      {...storageHoverProps(beforeDecoded, slot.before.value_encoded)}
                      chainId={chainId}
                      colorClass="text-xs font-mono text-gray-300"
                      wrap
                    />
                  }
                  after={
                    <HoverCell
                      display={finalValue}
                      {...storageHoverProps(afterDecoded, slot.after.value_encoded)}
                      chainId={chainId}
                      colorClass={cn('text-xs font-mono', afterClassName)}
                      wrap
                    />
                  }
                />
              );
            })()}
          </td>

          <td className={cn('hidden px-1 py-0.5 w-8 align-top sm:table-cell', isFirst && 'pt-1')}>
            <DetailPopover content={<div className="font-mono text-xs text-gray-100 break-all">{slot.slot}</div>}>
              <HoverCell display={slotNumber} value={slot.slot} colorClass="text-xs text-gray-500 font-mono" />
            </DetailPopover>
          </td>

          {showStep && (
            <td className={cn('hidden px-1 py-0.5 text-right w-8 align-top sm:table-cell', isFirst && 'pt-1')}>
              {firstStep !== null && firstStep !== undefined && (
                <DetailPopover content={<div className="font-mono text-[10px] text-gray-100">Step: {firstStep}</div>}>
                  <span className="text-[10px] text-gray-400 font-mono cursor-default">
                    {firstStep}
                  </span>
                </DetailPopover>
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
        const oldVal = storageDisplayValue(change.before.value_decoded, change.before.value_encoded, showHex);
        const newVal = storageDisplayValue(change.after.value_decoded, change.after.value_encoded, showHex);
        const unchanged = valuesEqual(change.before.value_decoded, change.after.value_decoded);
        const afterClassName = unchanged ? 'text-gray-400' : 'text-gray-900';

        return (
          <tr key={idx} className={cn('bg-gray-100/80', !isFirstChange && 'border-t border-gray-300')}>
            <td className="pl-3 py-0.5 align-top" />
            <td className="pl-3 py-0.5 align-top">
              <div className="flex flex-col items-start gap-0.5">
                <span className="text-[10px] text-gray-400">{idx + 1}/{slot.changes.length}</span>
                {change.frame_outcome === 'reverted' && (
                  <span className="text-[9px] uppercase tracking-wide text-amber-600">
                    reverted
                  </span>
                )}
              </div>
            </td>
            <td className="pl-3 py-0.5 align-top">
              {!showHex
                && isStructuredDecodedValue(change.before.value_decoded)
                && isStructuredDecodedValue(change.after.value_decoded) ? (
                <StructuredValueDiff
                  before={change.before.value_decoded}
                  after={change.after.value_decoded}
                  beforeClassName="text-gray-300"
                  afterClassName={afterClassName}
                />
              ) : (
                <ValueDiff
                  unchanged={unchanged}
                  beforeClassName="text-gray-300"
                  afterClassName={afterClassName}
                  before={
                    <HoverCell
                      display={oldVal}
                      {...storageHoverProps(change.before.value_decoded, change.before.value_encoded)}
                      chainId={chainId}
                      colorClass="text-xs font-mono text-gray-300"
                      wrap
                    />
                  }
                  after={
                    <HoverCell
                      display={newVal}
                      {...storageHoverProps(change.after.value_decoded, change.after.value_encoded)}
                      chainId={chainId}
                      colorClass={cn('text-xs font-mono', afterClassName)}
                      wrap
                    />
                  }
                />
              )}
            </td>
            <td className="hidden px-1 py-0.5 align-top sm:table-cell" />
            {showStep && (
              <td className="hidden px-1 py-0.5 text-right align-top sm:table-cell">
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
