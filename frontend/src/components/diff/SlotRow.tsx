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
import { formatStorageLocation } from '@/lib/storage-location';
import {
  cn,
  valuesEqual,
} from '@/lib/utils';
import { HoverCell } from '@/components/ui/HoverCell';
import { DetailPopover } from '@/components/ui/DetailPopover';
import { StorageLocationCell } from '@/components/ui/StorageLocationCell';
import {
  deriveStructuredValueFields,
  isStructuredDecodedValue,
  StructuredFieldNames,
  StructuredValueDiff,
  ValueDiff,
} from './ValueDiff';
import { StorageEvidenceDetail } from './StorageEvidenceDetail';
import { StorageVariableCell } from './StorageVariableCell';
import { InterimPackedChangeRows, PackedFieldRow } from './PackedFieldRows';
import { deriveStorageIdentity, storageIdentityMetadata } from './storageIdentity';
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
}

export function SlotRow({
  slot,
  showHex,
  chainId,
  showStep = true,
  isFirst = false,
}: SlotRowProps) {
  const [expanded, setExpanded] = useState(false);
  // Add top border to separate slots (but not the first one)
  const slotBorderClass = !isFirst ? 'border-t border-gray-200' : '';
  const {
    hasInterimChanges,
    hasPacked,
    firstStep,
    displayedPackedFields,
    showPackedAsTree,
    singlePackedField,
    initialValue,
    finalValue,
    revertedWriteCount,
  } = deriveSlotDisplay(slot, showHex);
  const structMember = slot.struct_field && slot.struct_definition
    ? slot.struct_definition.members.find((member) => member.name === slot.struct_field) ?? null
    : null;
  const identityMember = singlePackedField || structMember;
  const identity = deriveStorageIdentity(slot, identityMember, {
    packed: hasPacked && !identityMember,
  });
  const parentIdentity = deriveStorageIdentity(slot, null, { packed: hasPacked });
  const location = formatStorageLocation({ slot: slot.slot });
  const canExpand = hasInterimChanges;
  const structuredBefore = !showHex
    && !hasPacked
    && isStructuredDecodedValue(slot.before.value_decoded)
    ? slot.before.value_decoded
    : null;
  const structuredAfter = !showHex
    && !hasPacked
    && isStructuredDecodedValue(slot.after.value_decoded)
    ? slot.after.value_decoded
    : null;
  const structuredFields = structuredBefore && structuredAfter
    ? deriveStructuredValueFields(structuredBefore, structuredAfter)
    : null;
  const structuredHeaderClass = identity.path?.includes('[')
    ? 'h-10 overflow-hidden'
    : storageIdentityMetadata(identity) ? 'h-8 overflow-hidden' : 'h-5 overflow-hidden';

  const revertedNotice = revertedWriteCount > 0 ? (
    <span className="inline-block mt-0.5 text-[9px] uppercase tracking-wide text-amber-600">
      {revertedWriteCount === 1 ? 'reverted write' : `${revertedWriteCount} reverted writes`}
    </span>
  ) : null;

  const variableDetail = (
    <StorageEvidenceDetail
      slot={slot}
      chainId={chainId}
      displayPath={identity.path || parentIdentity.path}
    />
  );

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
      {showPackedAsTree && !showHex && slot.struct_definition?.name && (
        <tr className={cn('hover:bg-gray-50/50', expanded && 'bg-gray-50/30', slotBorderClass)}>
          <td className={cn('px-1 py-0.5 w-5 align-top', isFirst && 'pt-1')}>
            {canExpand ? expandButton : <span className="w-4 h-4 inline-block" />}
          </td>
          <td className={cn('px-1 py-0.5 align-top', isFirst && 'pt-1')} colSpan={2}>
            <DetailPopover content={variableDetail} delay={200} maxWidth="max-w-sm">
              <StorageVariableCell identity={parentIdentity} chainId={chainId} />
            </DetailPopover>
            {revertedNotice && <div>{revertedNotice}</div>}
          </td>
          <td className={cn('hidden px-1 py-0.5 w-8 align-top sm:table-cell', isFirst && 'pt-1')}>
            <StorageLocationCell
              location={location}
              colorClass="text-xs text-gray-500 font-mono"
            />
          </td>
          {showStep && (
            <td className={cn('hidden px-1 py-0.5 text-right w-8 align-top sm:table-cell', isFirst && 'pt-1')}>
              {firstStep !== null && firstStep !== undefined && (
                <DetailPopover content={<div className="font-mono text-[10px] text-gray-700">Step: {firstStep}</div>}>
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
          isFirst={idx === 0}
          isLast={idx === displayedPackedFields.length - 1}
          hasHeader={Boolean(slot.struct_definition?.name)}
          totalFields={displayedPackedFields.length}
          chainId={chainId}
          showStep={showStep}
          // Show slot/step on first field row only if no struct header
          slotInfo={!slot.struct_definition?.name && idx === 0 ? location : undefined}
          step={!slot.struct_definition?.name && idx === 0 ? firstStep : undefined}
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

          <td
            className={cn('px-1 py-0.5 align-top w-48 whitespace-normal', isFirst && 'pt-1')}
            data-testid="slot-variable"
          >
            <div className={structuredFields ? structuredHeaderClass : undefined}>
              <DetailPopover content={variableDetail} delay={200} maxWidth="max-w-sm">
                <StorageVariableCell
                  identity={identity}
                  chainId={chainId}
                  metadataTestId="storage-variable-meta"
                />
              </DetailPopover>
            </div>
            {structuredFields && (
              <StructuredFieldNames
                fields={structuredFields.displayedFields}
                members={slot.struct_definition?.members}
                className="mt-0"
              />
            )}
            {revertedNotice && <div>{revertedNotice}</div>}
          </td>

          <td
            className={cn('px-1 py-0.5 align-top', isFirst && 'pt-1')}
            data-testid="slot-value"
          >
            {(() => {
              // Use packed field values if single packed field without struct
              const beforeDecoded = singlePackedField ? singlePackedField.before.value_decoded : slot.before.value_decoded;
              const afterDecoded = singlePackedField ? singlePackedField.after.value_decoded : slot.after.value_decoded;
              const unchanged = valuesEqual(beforeDecoded, afterDecoded);
              const afterClassName = unchanged ? 'text-gray-400' : 'text-gray-900';

              if (!showHex && isStructuredDecodedValue(beforeDecoded) && isStructuredDecodedValue(afterDecoded)) {
                return (
                  <>
                    {structuredFields && <div aria-hidden="true" className={structuredHeaderClass} />}
                    <StructuredValueDiff
                      before={beforeDecoded}
                      after={afterDecoded}
                      beforeClassName="text-gray-300"
                      afterClassName={unchanged ? 'text-gray-300' : 'text-gray-900'}
                      displayedFields={structuredFields?.displayedFields}
                    />
                  </>
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
            <StorageLocationCell
              location={location}
              colorClass="text-xs text-gray-500 font-mono"
            />
          </td>

          {showStep && (
            <td className={cn('hidden px-1 py-0.5 text-right w-8 align-top sm:table-cell', isFirst && 'pt-1')}>
              {firstStep !== null && firstStep !== undefined && (
                <DetailPopover content={<div className="font-mono text-[10px] text-gray-700">Step: {firstStep}</div>}>
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
        const interimStructuredBefore = !showHex
          && isStructuredDecodedValue(change.before.value_decoded)
          ? change.before.value_decoded
          : null;
        const interimStructuredAfter = !showHex
          && isStructuredDecodedValue(change.after.value_decoded)
          ? change.after.value_decoded
          : null;
        const interimStructuredFields = interimStructuredBefore && interimStructuredAfter
          ? deriveStructuredValueFields(
              interimStructuredBefore,
              interimStructuredAfter,
              unchanged,
            )
          : null;

        return (
          <tr key={idx} className={cn('bg-gray-100/80', !isFirstChange && 'border-t border-gray-300')}>
            <td className="pl-3 py-0.5 align-top" />
            <td className="pl-3 py-0.5 align-top" data-testid="interim-variable">
              <div className="flex items-start gap-2">
                <div className="w-8 shrink-0">
                  <div className="flex flex-col items-start gap-0.5">
                    <span className="text-[10px] text-gray-400">{idx + 1}/{slot.changes.length}</span>
                    {change.frame_outcome === 'reverted' && (
                      <span className="text-[9px] uppercase tracking-wide text-amber-600">
                        reverted
                      </span>
                    )}
                  </div>
                </div>
                {interimStructuredFields && (
                  <StructuredFieldNames
                    fields={interimStructuredFields.displayedFields}
                    members={slot.struct_definition?.members}
                    className="mt-0 min-w-0 flex-1"
                  />
                )}
              </div>
            </td>
            <td className="pl-3 py-0.5 align-top" data-testid="interim-value">
              {interimStructuredBefore && interimStructuredAfter && interimStructuredFields ? (
                <StructuredValueDiff
                  before={interimStructuredBefore}
                  after={interimStructuredAfter}
                  beforeClassName="text-gray-300"
                  afterClassName={afterClassName}
                  displayedFields={interimStructuredFields.displayedFields}
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
