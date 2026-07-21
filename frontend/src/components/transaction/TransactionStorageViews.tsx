'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ExternalLink } from 'lucide-react';
import { SlotHistoryTable } from '@/components/diff/DiffTable';
import { StorageTable, StorageTableColumns, StorageTableHeader, storageCellClass } from '@/components/diff/StorageTable';
import { StorageVariableCell } from '@/components/diff/StorageVariableCell';
import { deriveStructuredValueFields, isStructuredDecodedValue, StructuredFieldNames, StructuredValueDiff } from '@/components/diff/ValueDiff';
import { deriveStorageIdentity, storageIdentityMetadata } from '@/components/diff/storageIdentity';
import { StorageValueDiff } from '@/components/diff/StorageValueDiff';
import { CopyButton } from '@/components/ui/CopyButton';
import { StorageLocationCell } from '@/components/ui/StorageLocationCell';
import { TimelineVariableDisclosure } from '@/components/transaction/TimelineVariableDisclosure';
import { getAddressExplorerUrl } from '@/lib/constants';
import { formatStorageLocation } from '@/lib/storage-location';
import { ContractHistoryResponse, SlotChangeResponse, StorageChangeResponse } from '@/lib/types';
import { cn, truncateAddress } from '@/lib/utils';
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

function timelineStructMember(slot: SlotChangeResponse, changedFields: string[]) {
  if (!slot.struct_definition) return null;

  const packedFields = slot.packed_fields ?? [];
  if (packedFields.length === 1) return packedFields[0];
  if (changedFields.length !== 1) return null;

  const changedField = changedFields[0];
  return packedFields.find((field) => field.name === changedField)
    ?? slot.struct_definition.members.find((field) => field.name === changedField)
    ?? null;
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
            <h2 className="truncate text-sm font-normal text-gray-900">{displayLabel}</h2>
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
          {contract.layout_provenance === 'bytecode_equivalent'
            && contract.layout_source_address && (
            <div className="mb-1 text-[10px] text-gray-500">
              Layout from verified bytecode-equivalent{' '}
              <span className="inline-flex items-center gap-0.5">
                <a
                  href={getAddressExplorerUrl(chain, contract.layout_source_address)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:underline"
                  title={contract.layout_source_address}
                >
                  {truncateAddress(contract.layout_source_address)}
                </a>
                <CopyButton
                  value={contract.layout_source_address}
                  label="Copy layout source address"
                  className="-my-1"
                />
              </span>
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
    <StorageTable
      containerClassName="-mx-4 w-auto max-w-none sm:mx-0 sm:w-full sm:max-w-full"
      minWidth="56rem"
      mobileMinWidth="calc(100% + 9rem)"
    >
      <StorageTableColumns showContract={showContract} showSlotOnMobile mobileScrollable />
      <StorageTableHeader showContract={showContract} showSlotOnMobile mobileScrollable />
      <tbody>
        {entries.map(({ contract, slot, event, ordinal }) => {
          const structuredBefore = isStructuredDecodedValue(event.before.value_decoded)
            ? event.before.value_decoded
            : null;
          const structuredAfter = isStructuredDecodedValue(event.after.value_decoded)
            ? event.after.value_decoded
            : null;
          const structuredFields = structuredBefore && structuredAfter
            ? deriveStructuredValueFields(
                structuredBefore,
                structuredAfter,
                event.effect === 'noop',
              )
            : null;
          const structMember = timelineStructMember(slot, structuredFields?.changedFields ?? []);
          const structuredFieldNames = structuredFields?.displayedFields ?? [];
          const unchanged = event.effect === 'noop';
          const hasStructuredChildren = !structMember && structuredFieldNames.length > 0;
          const identity = deriveStorageIdentity(slot, structMember, {
            packed: Boolean(!structMember && slot.packed_fields?.length),
          });
          const identityMetadata = storageIdentityMetadata(identity);
          const structuredHeaderClass = identity.path?.includes('[')
            ? 'h-10 overflow-hidden'
            : identityMetadata ? 'h-8 overflow-hidden' : 'h-5 overflow-hidden';
          const location = formatStorageLocation({ slot: slot.slot });

          return (
            <tr key={`${contract.storage_address}:${slot.slot}:${event.step}:${ordinal}`} data-testid="timeline-event" className="border-b border-gray-200 text-xs hover:bg-gray-50">
              {showContract && (
                <td className={`${storageCellClass} min-w-0 overflow-hidden`} data-testid="timeline-contract">
                  <a href={getAddressExplorerUrl(chain, contract.storage_address)} target="_blank" rel="noopener noreferrer" className="block truncate text-gray-500 hover:underline" title={contract.storage_address}>
                    {contractDisplayLabel(contract)}
                  </a>
                  <span className="flex min-w-0 items-center text-[10px] text-gray-500">
                    <Link href={`/${chain}/${contract.storage_address}`} className="truncate hover:underline" title={contract.storage_address}>
                      {truncateAddress(contract.storage_address)}
                    </Link>
                    <CopyButton value={contract.storage_address} label="Copy contract address" className="-my-1 p-1" />
                  </span>
                </td>
              )}
              <td className={`${storageCellClass} min-w-0 overflow-hidden`} data-testid="timeline-variable">
                <div
                  className={hasStructuredChildren ? structuredHeaderClass : undefined}
                  data-testid={hasStructuredChildren ? 'timeline-structured-header-frame' : undefined}
                >
                  <TimelineVariableDisclosure
                    contract={contract}
                    chain={chain}
                    variable={identity.detail}
                    typeLabel={identityMetadata}
                    isRawSlot={identity.isRaw}
                  >
                    <StorageVariableCell
                      identity={identity}
                      chainId={chain}
                      testId={hasStructuredChildren ? 'timeline-structured-header' : undefined}
                      metadataTestId="timeline-variable-meta"
                    />
                  </TimelineVariableDisclosure>
                </div>
                {hasStructuredChildren && (
                  <StructuredFieldNames
                    fields={structuredFieldNames}
                    members={slot.struct_definition?.members}
                    className="mt-0"
                  />
                )}
              </td>
              <td className={`${storageCellClass} min-w-0 overflow-hidden font-mono`} data-testid="timeline-value">
                {!showHex && structuredBefore && structuredAfter && structuredFields ? (
                  <>
                    {hasStructuredChildren && <div aria-hidden="true" className={structuredHeaderClass} />}
                    <StructuredValueDiff
                      before={structuredBefore}
                      after={structuredAfter}
                      displayedFields={structuredFields.displayedFields}
                    />
                  </>
                ) : (
                  <StorageValueDiff
                    before={event.before}
                    after={event.after}
                    showHex={showHex}
                    chainId={chain}
                    unchanged={unchanged}
                  />
                )}
                {event.frame_outcome === 'reverted' && <div className="mt-0.5 text-[9px] uppercase tracking-wide text-amber-600">reverted</div>}
              </td>
              <td className={`${storageCellClass} min-w-0 px-1 font-mono text-gray-500 sm:px-2`}>
                <div data-testid="slot-reference" className="min-w-0 truncate">
                  <StorageLocationCell
                    location={location}
                    colorClass="text-gray-500"
                  />
                </div>
              </td>
              <td className={`${storageCellClass} overflow-hidden whitespace-nowrap font-mono text-gray-400`} data-testid="step-reference">
                {event.step ?? '—'}
              </td>
            </tr>
          );
        })}
      </tbody>
    </StorageTable>
  );
}
