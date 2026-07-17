'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ExternalLink } from 'lucide-react';
import { SlotHistoryTable } from '@/components/diff/DiffTable';
import { KeyedVariablePath } from '@/components/diff/KeyedVariablePath';
import { StorageTable, StorageTableColumns, StorageTableHeader, storageCellClass } from '@/components/diff/StorageTable';
import { CopyableValue, isStructuredDecodedValue, StructuredValueDiff, ValueDiff } from '@/components/diff/ValueDiff';
import { CopyButton } from '@/components/ui/CopyButton';
import { getAddressExplorerUrl } from '@/lib/constants';
import { ContractHistoryResponse, SlotChangeResponse, StorageChangeResponse } from '@/lib/types';
import { cn, formatDecodedValue, getCopyValue, truncateAddress, truncateHash } from '@/lib/utils';
import { slotReferenceDisplay } from '@/components/diff/slotDisplay';
import {
  contractActivityStatus,
  contractDisplayLabel,
  contractResolutionNotice,
  contractResolutionStatus,
} from '@/lib/contract-resolution';

export interface TimelineEntry {
  contract: ContractHistoryResponse;
  slot: SlotChangeResponse;
  event: StorageChangeResponse;
  ordinal: number;
}

function eventValue(event: StorageChangeResponse, side: 'before' | 'after', showHex: boolean) {
  const pair = event[side];
  if (showHex) return pair.value_encoded ?? 'unknown';
  return pair.value_decoded === null || pair.value_decoded === undefined
    ? pair.value_encoded ?? 'unknown'
    : formatDecodedValue(pair.value_decoded);
}

function eventCopyValue(event: StorageChangeResponse, side: 'before' | 'after', showHex: boolean) {
  const pair = event[side];
  const encoded = pair.value_encoded ?? 'unknown';
  return showHex ? encoded : getCopyValue(pair.value_decoded, encoded);
}

function eventRawValue(event: StorageChangeResponse, side: 'before' | 'after', showHex: boolean) {
  const pair = event[side];
  return showHex ? pair.value_encoded : pair.value_decoded ?? pair.value_encoded;
}

function timelineStructMember(slot: SlotChangeResponse) {
  if (!slot.struct_definition || slot.packed_fields?.length !== 1) return null;
  return slot.packed_fields[0];
}

function timelineVariablePath(slot: SlotChangeResponse, memberName?: string) {
  const base = slot.variable_path || slot.variable_name;
  if (!base || !memberName || base.endsWith(`.${memberName}`)) return base;
  return `${base}.${memberName}`;
}

export function ContractSection({
  contract,
  chain,
  forceOpen,
  defaultOpen,
  executionOrderAvailable,
  isComplete,
  showHex,
}: {
  contract: ContractHistoryResponse;
  chain: string;
  forceOpen: boolean;
  defaultOpen: boolean;
  executionOrderAvailable: boolean;
  isComplete: boolean;
  showHex: boolean;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const expanded = isOpen || forceOpen;
  const detailId = `owner-storage-${contract.storage_address.slice(2)}`;
  const displayLabel = contractDisplayLabel(contract);
  const activityStatus = contractActivityStatus(contract);
  const resolutionNotice = contractResolutionNotice(contract);
  const resolutionStatus = contractResolutionStatus(contract);

  useEffect(() => {
    if (defaultOpen) setIsOpen(true);
  }, [defaultOpen]);

  return (
    <section id={`owner-${contract.storage_address.slice(2)}`} className="min-w-0 scroll-mt-16 border-b border-gray-300">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 py-1.5 hover:bg-gray-50">
        <div className="grid min-w-0 grid-cols-[1rem_minmax(0,1fr)] grid-rows-[auto_auto] items-center gap-x-1">
          <button
            type="button"
            data-testid="contract-toggle"
            aria-expanded={expanded}
            aria-controls={detailId}
            aria-label={`${expanded ? 'Collapse' : 'Expand'} ${displayLabel}`}
            onClick={() => setIsOpen((open) => !open)}
            className="col-span-2 row-start-1 flex min-w-0 items-center gap-1 text-left"
          >
            <span aria-hidden="true" className={cn('text-[10px] text-gray-400 transition-transform', expanded && 'rotate-90')}>▶</span>
            <h2 className="truncate text-sm font-medium text-gray-900">{displayLabel}</h2>
          </button>
          <span className="col-start-2 row-start-2 flex min-w-0 items-center font-mono text-[10px] text-gray-500" title={contract.storage_address}>
            <Link href={`/${chain}/${contract.storage_address}`} className="truncate hover:underline">
              {truncateAddress(contract.storage_address)}
            </Link>
            <CopyButton value={contract.storage_address} label="Copy contract address" className="-my-1 p-1" />
            <a
              href={getAddressExplorerUrl(chain, contract.storage_address)}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="View contract on Etherscan"
              title="View contract on Etherscan"
              className="touch-hitbox -my-1 inline-flex h-5 w-5 shrink-0 items-center justify-center text-gray-400 transition-colors hover:text-gray-900 focus-visible:text-gray-900 focus-visible:outline-none"
            >
              <ExternalLink size={12} strokeWidth={1.25} />
            </a>
          </span>
        </div>
        <span className="flex shrink-0 flex-col items-end whitespace-nowrap text-right text-[10px] text-gray-500">
          <span>{contract.counts.sstore_events} {contract.counts.sstore_events === 1 ? 'write' : 'writes'} · {contract.counts.slots_written} {contract.counts.slots_written === 1 ? 'slot' : 'slots'}</span>
          {(contract.counts.reverted_writes > 0 || activityStatus) && (
            <span className="text-[9px] text-gray-400">
              {contract.counts.reverted_writes > 0 && <>{contract.counts.reverted_writes} reverted {contract.counts.reverted_writes === 1 ? 'write' : 'writes'}</>}
              {contract.counts.reverted_writes > 0 && activityStatus && <> · </>}
              {activityStatus}
            </span>
          )}
        </span>
      </div>

      {expanded && (
        <div id={detailId} className="min-w-0 pb-3 pl-5">
          {contract.implementation_addresses.length > 0 && (
            <div className="mb-1 text-[10px] text-gray-500">
              written via {contract.implementation_addresses.map((address, index) => (
                <span key={address} className="inline-flex items-center gap-0.5">
                  {index > 0 && ', '}
                  <a href={getAddressExplorerUrl(chain, address)} target="_blank" rel="noopener noreferrer" className="hover:underline" title={address}>{truncateAddress(address)}</a>
                  <CopyButton value={address} label={`Copy implementation address ${truncateAddress(address)}`} className="-my-1" />
                </span>
              ))}
            </div>
          )}
          {resolutionNotice && (
            <div className={cn(
              'mb-1 text-[10px]',
              resolutionStatus === 'timed_out' || resolutionStatus === 'failed'
                ? 'text-amber-600'
                : 'text-gray-500',
            )}>
              {resolutionNotice}
            </div>
          )}
          <SlotHistoryTable chainId={chain} slots={contract.slots} showHex={showHex} executionOrderAvailable={executionOrderAvailable} isComplete={isComplete} />
        </div>
      )}
    </section>
  );
}

export function Timeline({ entries, chain, showContract, showHex }: { entries: TimelineEntry[]; chain: string; showContract: boolean; showHex: boolean }) {
  if (entries.length === 0) return <div className="border border-gray-300 p-8 text-center text-gray-500">No writes match the search</div>;

  return (
    <StorageTable minWidth="56rem">
      <StorageTableColumns showContract={showContract} />
      <StorageTableHeader showContract={showContract} />
      <tbody>
        {entries.map(({ contract, slot, event, ordinal }) => {
          const structMember = timelineStructMember(slot);
          const variablePath = timelineVariablePath(slot, structMember?.name);
          const unchanged = event.effect === 'noop';

          return (
            <tr key={`${contract.storage_address}:${slot.slot}:${event.step}:${ordinal}`} data-testid="timeline-event" className="border-b border-gray-200 text-xs hover:bg-gray-50">
              {showContract && (
                <td className={`${storageCellClass} hidden sm:table-cell`}>
                  <a href={getAddressExplorerUrl(chain, contract.storage_address)} target="_blank" rel="noopener noreferrer" className="block truncate text-gray-700 hover:underline" title={contract.storage_address}>
                    {contractDisplayLabel(contract)}
                  </a>
                </td>
              )}
              <td className={storageCellClass}>
                {showContract && (
                  <a href={getAddressExplorerUrl(chain, contract.storage_address)} target="_blank" rel="noopener noreferrer" className="block truncate text-[10px] text-gray-500 hover:underline sm:hidden" title={contract.storage_address}>
                    {contractDisplayLabel(contract)}
                  </a>
                )}
                {variablePath?.includes('[') ? (
                  <KeyedVariablePath path={variablePath} typeLabel={structMember?.type_label || slot.value_type || slot.type_label} chainId={chain} />
                ) : (
                  <div className="truncate font-mono text-gray-900" title={variablePath || slot.slot}>{variablePath || truncateHash(slot.slot, 7)}</div>
                )}
              </td>
              <td className={`${storageCellClass} min-w-0 overflow-hidden font-mono`} data-testid="timeline-value">
                {!showHex
                  && isStructuredDecodedValue(event.before.value_decoded)
                  && isStructuredDecodedValue(event.after.value_decoded) ? (
                  <StructuredValueDiff
                    before={event.before.value_decoded}
                    after={event.after.value_decoded}
                    showFieldNames={!structMember}
                    showUnchanged={event.effect === 'noop'}
                  />
                ) : (
                  <ValueDiff
                    unchanged={unchanged}
                    before={(
                      <CopyableValue
                        value={eventRawValue(event, 'before', showHex)}
                        display={eventValue(event, 'before', showHex)}
                        copyValue={eventCopyValue(event, 'before', showHex)}
                        label="Copy previous value"
                      />
                    )}
                    after={(
                      <CopyableValue
                        value={eventRawValue(event, 'after', showHex)}
                        display={eventValue(event, 'after', showHex)}
                        copyValue={eventCopyValue(event, 'after', showHex)}
                        label={unchanged ? 'Copy value' : 'Copy new value'}
                      />
                    )}
                    beforeClassName="text-gray-400"
                    afterClassName={unchanged ? 'text-gray-400' : 'text-gray-900'}
                  />
                )}
                {event.frame_outcome === 'reverted' && <div className="mt-0.5 text-[9px] uppercase tracking-wide text-amber-600">reverted</div>}
              </td>
              <td className={`${storageCellClass} hidden min-w-0 font-mono text-gray-500 sm:table-cell`} title={slot.slot}>
                <span data-testid="slot-reference" className="block truncate">{slotReferenceDisplay(slot.slot, false)}</span>
              </td>
              <td className={`${storageCellClass} hidden overflow-hidden whitespace-nowrap font-mono text-gray-400 sm:table-cell`} data-testid="step-reference">
                {event.step ?? '—'}
              </td>
            </tr>
          );
        })}
      </tbody>
    </StorageTable>
  );
}
