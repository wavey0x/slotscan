'use client';

import { useEffect, useState } from 'react';
import { SlotHistoryTable } from '@/components/diff/DiffTable';
import { KeyedVariablePath } from '@/components/diff/KeyedVariablePath';
import { StorageTable, StorageTableColumns, StorageTableHeader, storageCellClass } from '@/components/diff/StorageTable';
import { ValueDiff } from '@/components/diff/ValueDiff';
import { CopyButton } from '@/components/ui/CopyButton';
import { getAddressExplorerUrl } from '@/lib/constants';
import { ContractHistoryResponse, SlotChangeResponse, StorageChangeResponse } from '@/lib/types';
import { cn, formatDecodedValue, truncateAddress, truncateHash } from '@/lib/utils';
import { slotReferenceDisplay } from '@/components/diff/slotDisplay';

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

function contractErrorMessage(message: string): string {
  if (message.toLowerCase().includes('historical resolution')) {
    return 'Variable resolution is incomplete; raw slot history is shown.';
  }
  if (message.toLowerCase().includes('layout')) {
    return 'The storage layout is incomplete; unresolved slots are shown raw.';
  }
  return 'Some storage evidence could not be resolved; raw slot history is shown.';
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
            aria-label={`${expanded ? 'Collapse' : 'Expand'} ${contract.name || 'unresolved contract'}`}
            onClick={() => setIsOpen((open) => !open)}
            className="col-span-2 row-start-1 flex min-w-0 items-center gap-1 text-left"
          >
            <span aria-hidden="true" className={cn('text-[10px] text-gray-400 transition-transform', expanded && 'rotate-90')}>▶</span>
            <h2 className="truncate text-sm font-medium text-gray-900">{contract.name || 'Unresolved contract'}</h2>
          </button>
          <span className="col-start-2 row-start-2 flex min-w-0 items-center font-mono text-[10px] text-gray-500" title={contract.storage_address}>
            <a href={getAddressExplorerUrl(chain, contract.storage_address)} target="_blank" rel="noopener noreferrer" className="truncate hover:underline">
              {truncateAddress(contract.storage_address)}
            </a>
            <CopyButton value={contract.storage_address} label="Copy contract address" className="-my-1 p-1" />
          </span>
        </div>
        <span className="flex shrink-0 flex-col items-end whitespace-nowrap text-right text-[10px] text-gray-500">
          <span>{contract.counts.sstore_events} {contract.counts.sstore_events === 1 ? 'write' : 'writes'} · {contract.counts.slots_written} {contract.counts.slots_written === 1 ? 'slot' : 'slots'}</span>
          {(contract.counts.reverted_writes > 0 || !contract.layout_available) && (
            <span className="text-[9px] text-gray-400">
              {contract.counts.reverted_writes > 0 && <>{contract.counts.reverted_writes} reverted {contract.counts.reverted_writes === 1 ? 'write' : 'writes'}</>}
              {contract.counts.reverted_writes > 0 && !contract.layout_available && <> · </>}
              {!contract.layout_available && <>raw slots</>}
            </span>
          )}
        </span>
      </div>

      {expanded && (
        <div id={detailId} className="min-w-0 pb-3 pl-5">
          {contract.implementation_addresses.length > 0 && (
            <div className="mb-1 text-[10px] text-gray-500">
              written via {contract.implementation_addresses.map((address, index) => (
                <span key={address}>
                  {index > 0 && ', '}
                  <a href={getAddressExplorerUrl(chain, address)} target="_blank" rel="noopener noreferrer" className="hover:underline" title={address}>{truncateAddress(address)}</a>
                </span>
              ))}
            </div>
          )}
          {Array.from(new Set(contract.errors.map(contractErrorMessage))).map((message) => <div key={message} className="mb-1 text-[10px] text-amber-600">{message}</div>)}
          <SlotHistoryTable chainId={chain} slots={contract.slots} showHex={showHex} executionOrderAvailable={executionOrderAvailable} isComplete={isComplete} />
        </div>
      )}
    </section>
  );
}

export function Timeline({ entries, chain, showContract, showHex }: { entries: TimelineEntry[]; chain: string; showContract: boolean; showHex: boolean }) {
  if (entries.length === 0) return <div className="border border-gray-300 p-8 text-center text-gray-500">No writes match the search</div>;

  return (
    <StorageTable>
      <StorageTableColumns showContract={showContract} />
      <StorageTableHeader showContract={showContract} />
      <tbody>
        {entries.map(({ contract, slot, event, ordinal }) => (
          <tr key={`${contract.storage_address}:${slot.slot}:${event.step}:${ordinal}`} data-testid="timeline-event" className="border-b border-gray-200 text-xs hover:bg-gray-50">
            {showContract && (
              <td className={storageCellClass}>
                <a href={getAddressExplorerUrl(chain, contract.storage_address)} target="_blank" rel="noopener noreferrer" className="block truncate text-gray-700 hover:underline" title={contract.storage_address}>
                  {contract.name || truncateAddress(contract.storage_address)}
                </a>
              </td>
            )}
            <td className={storageCellClass}>
              {slot.variable_path?.includes('[') ? (
                <KeyedVariablePath path={slot.variable_path} typeLabel={slot.value_type || slot.type_label} chainId={chain} />
              ) : (
                <div className="truncate font-mono text-gray-900" title={slot.variable_path || slot.slot}>{slot.variable_path || slot.variable_name || truncateHash(slot.slot, 7)}</div>
              )}
            </td>
            <td className={`${storageCellClass} min-w-0 overflow-hidden font-mono`}>
              <ValueDiff before={eventValue(event, 'before', showHex)} after={eventValue(event, 'after', showHex)} beforeClassName="truncate text-gray-400" afterClassName="truncate text-gray-900" />
              {event.frame_outcome === 'reverted' && <div className="mt-0.5 text-[9px] uppercase tracking-wide text-amber-600">reverted</div>}
            </td>
            <td className={`${storageCellClass} min-w-0 font-mono text-gray-500`} title={slot.slot}>
              <span data-testid="slot-reference" className="block truncate">{slotReferenceDisplay(slot.slot, false)}</span>
            </td>
            <td className={`${storageCellClass} overflow-hidden whitespace-nowrap font-mono text-gray-400`} data-testid="step-reference">
              {event.step ?? '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </StorageTable>
  );
}
