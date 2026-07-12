'use client';

import { useEffect, useMemo, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { SlotHistoryTable } from '@/components/diff/DiffTable';
import { KeyedVariablePath } from '@/components/diff/KeyedVariablePath';
import { ValueDiff } from '@/components/diff/ValueDiff';
import {
  StorageTable,
  StorageTableColumns,
  StorageTableHeader,
  storageCellClass,
} from '@/components/diff/StorageTable';
import { TransactionHeader } from '@/components/transaction/TransactionHeader';
import { DataQuality } from '@/components/transaction/DataQuality';
import { CopyButton } from '@/components/ui/CopyButton';
import { Input } from '@/components/ui/Input';
import { Loading } from '@/components/ui/Loading';
import { getAddressExplorerUrl } from '@/lib/constants';
import { useTransactionStorageHistory } from '@/lib/hooks/useTransactionStorageHistory';
import {
  ContractHistoryResponse,
  SlotChangeResponse,
  StorageChangeResponse,
} from '@/lib/types';
import {
  cn,
  formatDecodedValue,
  formatSlotShort,
  truncateAddress,
  truncateHash,
} from '@/lib/utils';

type ViewMode = 'grouped' | 'timeline';

interface TransactionStorageExplorerProps {
  chain: string;
  txHash: string;
}

interface TimelineEntry {
  contract: ContractHistoryResponse;
  slot: SlotChangeResponse;
  event: StorageChangeResponse;
  ordinal: number;
}

function searchableContract(contract: ContractHistoryResponse, slot: SlotChangeResponse) {
  return [
    contract.name,
    contract.storage_address,
    ...contract.implementation_addresses,
    slot.slot,
    slot.variable_name,
    slot.variable_path,
    ...slot.resolved_paths,
  ].filter(Boolean).join(' ').toLowerCase();
}

function eventValue(event: StorageChangeResponse, side: 'before' | 'after') {
  const pair = event[side];
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

function ContractSection({
  contract,
  chain,
  forceOpen,
  defaultOpen,
  executionOrderAvailable,
  isComplete,
}: {
  contract: ContractHistoryResponse;
  chain: string;
  forceOpen: boolean;
  defaultOpen: boolean;
  executionOrderAvailable: boolean;
  isComplete: boolean;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const expanded = isOpen || forceOpen;

  useEffect(() => {
    if (defaultOpen) setIsOpen(true);
  }, [defaultOpen]);

  return (
    <section id={`owner-${contract.storage_address.slice(2)}`} className="scroll-mt-16 border-b border-gray-300">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 py-1.5 hover:bg-gray-50">
        <div className="grid min-w-0 grid-cols-[1rem_minmax(0,1fr)] grid-rows-[auto_auto] items-center gap-x-1">
          <button
            type="button"
            data-testid="contract-toggle"
            aria-expanded={expanded}
            aria-label={`${expanded ? 'Collapse' : 'Expand'} ${contract.name || 'unresolved contract'}`}
            onClick={() => setIsOpen((open) => !open)}
            className="col-span-2 row-start-1 flex min-w-0 items-center gap-1 text-left"
          >
            <span
              aria-hidden="true"
              className={cn('text-[10px] text-gray-400 transition-transform', expanded && 'rotate-90')}
            >
              ▶
            </span>
            <h2 className="truncate text-sm font-medium text-gray-900">
              {contract.name || 'Unresolved contract'}
            </h2>
          </button>
          <span
            className="col-start-2 row-start-2 flex min-w-0 items-center text-[10px] font-mono text-gray-500"
            title={contract.storage_address}
          >
            <a
              href={getAddressExplorerUrl(chain, contract.storage_address)}
              target="_blank"
              rel="noopener noreferrer"
              className="truncate hover:underline"
            >
              {truncateAddress(contract.storage_address)}
            </a>
            <CopyButton value={contract.storage_address} className="-my-1 p-1" />
          </span>
        </div>
        <span className="flex shrink-0 flex-col items-end whitespace-nowrap text-right text-[10px] text-gray-500">
          <span>
            {contract.counts.sstore_events} {contract.counts.sstore_events === 1 ? 'write' : 'writes'} · {contract.counts.slots_written} {contract.counts.slots_written === 1 ? 'slot' : 'slots'}
          </span>
          {(contract.counts.reverted_writes > 0 || !contract.layout_available) && (
            <span className="text-[9px] text-gray-400">
              {contract.counts.reverted_writes > 0 && (
                <>{contract.counts.reverted_writes} reverted {contract.counts.reverted_writes === 1 ? 'write' : 'writes'}</>
              )}
              {contract.counts.reverted_writes > 0 && !contract.layout_available && <> · </>}
              {!contract.layout_available && <>raw slots</>}
            </span>
          )}
        </span>
      </div>

      {expanded && (
        <div className="pb-3 pl-5">
          {contract.implementation_addresses.length > 0 && (
            <div className="mb-1 text-[10px] text-gray-500">
              written via {contract.implementation_addresses.map((address, index) => (
                <span key={address}>
                  {index > 0 && ', '}
                  <a
                    href={getAddressExplorerUrl(chain, address)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:underline"
                    title={address}
                  >
                    {truncateAddress(address)}
                  </a>
                </span>
              ))}
            </div>
          )}
          {Array.from(new Set(contract.errors.map(contractErrorMessage))).map((message) => (
            <div key={message} className="mb-1 text-[10px] text-amber-600">{message}</div>
          ))}
          <SlotHistoryTable
            chainId={chain}
            slots={contract.slots}
            showHex={false}
            executionOrderAvailable={executionOrderAvailable}
            isComplete={isComplete}
          />
        </div>
      )}
    </section>
  );
}

function Timeline({
  entries,
  chain,
  showContract,
}: {
  entries: TimelineEntry[];
  chain: string;
  showContract: boolean;
}) {
  if (entries.length === 0) {
    return <div className="border border-gray-300 p-8 text-center text-gray-500">No writes match the search</div>;
  }

  return (
    <StorageTable>
      <StorageTableColumns showContract={showContract} />
      <StorageTableHeader showContract={showContract} />
      <tbody>
        {entries.map(({ contract, slot, event, ordinal }) => (
          <tr
            key={`${contract.storage_address}:${slot.slot}:${event.step}:${ordinal}`}
            data-testid="timeline-event"
            className="border-b border-gray-200 text-xs hover:bg-gray-50"
          >
            {showContract && (
              <td className={storageCellClass}>
                <a
                  href={getAddressExplorerUrl(chain, contract.storage_address)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block truncate text-gray-700 hover:underline"
                  title={contract.storage_address}
                >
                  {contract.name || truncateAddress(contract.storage_address)}
                </a>
              </td>
            )}
            <td className={storageCellClass}>
              {slot.variable_path?.includes('[') ? (
                <KeyedVariablePath
                  path={slot.variable_path}
                  typeLabel={slot.value_type || slot.type_label}
                  chainId={chain}
                />
              ) : (
                <div className="truncate font-mono text-gray-900" title={slot.variable_path || slot.slot}>
                  {slot.variable_path || slot.variable_name || truncateHash(slot.slot, 7)}
                </div>
              )}
            </td>
            <td className={`${storageCellClass} min-w-0 overflow-hidden font-mono`}>
              <ValueDiff
                before={eventValue(event, 'before')}
                after={eventValue(event, 'after')}
                beforeClassName="truncate text-gray-400"
                afterClassName="truncate text-gray-900"
              />
              {event.frame_outcome === 'reverted' && (
                <div className="mt-0.5 text-[9px] uppercase tracking-wide text-amber-600">
                  reverted
                </div>
              )}
            </td>
            <td className={`${storageCellClass} font-mono text-gray-500`} title={slot.slot}>
              {formatSlotShort(slot.slot)}
            </td>
            <td className={`${storageCellClass} font-mono text-gray-400`}>
              {event.step ?? '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </StorageTable>
  );
}

export function TransactionStorageExplorer({ chain, txHash }: TransactionStorageExplorerProps) {
  const { data, isLoading, error } = useTransactionStorageHistory(chain, txHash);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [search, setSearch] = useState('');
  const viewParam = searchParams.get('view');
  const requestedView: ViewMode = viewParam === 'timeline' ? 'timeline' : 'grouped';
  const focusParam = searchParams.get('focus')?.toLowerCase() || null;

  useEffect(() => {
    if (!data || !focusParam) return;
    const focused = data.contracts.find(
      (contract) => contract.storage_address.toLowerCase() === focusParam
    );
    if (!focused) return;
    requestAnimationFrame(() => {
      document.getElementById(`owner-${focused.storage_address.slice(2)}`)?.scrollIntoView({ block: 'start' });
    });
  }, [data, focusParam]);

  const selectView = (mode: ViewMode) => {
    const next = new URLSearchParams(searchParams.toString());
    next.set('view', mode);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };

  const filteredContracts = useMemo(() => {
    if (!data) return [];
    const query = search.trim().toLowerCase();
    if (!query) return data.contracts;
    return data.contracts.map((contract) => ({
      ...contract,
      slots: contract.slots.filter((slot) => searchableContract(contract, slot).includes(query)),
    })).filter((contract) => contract.slots.length > 0);
  }, [data, search]);

  const timeline = useMemo(() => {
    if (!data) return [];
    const contracts = new Map(data.contracts.map((contract) => [contract.storage_address.toLowerCase(), contract]));
    const slots = new Map<string, SlotChangeResponse>();
    data.contracts.forEach((contract) => contract.slots.forEach((slot) => {
      slots.set(`${contract.storage_address.toLowerCase()}:${slot.slot}`, slot);
    }));
    const references = data.global_order || data.contracts.flatMap((contract) => (
      contract.slots.flatMap((slot) => slot.changes.map((event, eventIndex) => ({
        ordinal: event.step ?? Number.MAX_SAFE_INTEGER,
        step: event.step,
        storage_address: contract.storage_address,
        slot: slot.slot,
        event_index: eventIndex,
      })))
    ));
    const query = search.trim().toLowerCase();
    return references.map((reference): TimelineEntry | null => {
      const contract = contracts.get(reference.storage_address.toLowerCase());
      const slot = slots.get(`${reference.storage_address.toLowerCase()}:${reference.slot}`);
      const event = slot?.changes[reference.event_index];
      if (!contract || !slot || !event) return null;
      if (query && !searchableContract(contract, slot).includes(query)) return null;
      return { contract, slot, event, ordinal: reference.ordinal };
    }).filter((entry): entry is TimelineEntry => entry !== null)
      .sort((a, b) => (a.event.step ?? Number.MAX_SAFE_INTEGER) - (b.event.step ?? Number.MAX_SAFE_INTEGER) || a.ordinal - b.ordinal);
  }, [data, search]);

  if (isLoading) {
    return <Loading message="Analyzing transaction" subtitle="Large traces may take up to two minutes." />;
  }
  if (error) {
    return <div className="border border-gray-300 p-5 text-red">Failed to analyze transaction: {(error as Error).message}</div>;
  }
  if (!data) return null;
  if (data.trace_unavailable) {
    return <div className="border border-gray-300 p-6"><div className="mb-2 text-gray-900">Tracing unavailable</div><p className="text-sm text-gray-500">The RPC could not provide complete execution-time storage history.</p></div>;
  }

  const warnings = [
    !data.capabilities.write_history_complete && 'Write history is incomplete.',
    !data.capabilities.values_complete && 'Some event before-values are unknown.',
    !data.capabilities.rollback_classification_complete && 'Rollback classification is incomplete.',
    !data.capabilities.state_reconciliation_complete && 'Replayed values did not fully reconcile with final state.',
    !data.capabilities.execution_order_available && 'Global execution order is unavailable.',
    !data.capabilities.code_attribution_complete && 'Some implementation/code addresses are unknown.',
  ].filter(Boolean) as string[];

  const singleContract = data.contracts.length === 1 ? data.contracts[0] : null;
  const view: ViewMode = requestedView === 'timeline' && data.capabilities.execution_order_available
    ? 'timeline'
    : 'grouped';
  const showSearch = data.summary.slots_written > 15 || data.contracts.length > 3;
  return (
    <div>
      <TransactionHeader chain={chain} data={data} />
      {singleContract && !singleContract.layout_available && (
        <div className="-mt-4 mb-5 text-[10px] uppercase tracking-wide text-gray-500">Raw slots</div>
      )}

      <DataQuality warnings={warnings} />

      <div className="mb-7 flex flex-wrap items-center gap-2 border-y border-gray-300 py-3">
        {(['grouped', 'timeline'] as ViewMode[]).map((mode) => (
          <button
            key={mode}
            onClick={() => selectView(mode)}
            disabled={mode === 'timeline' && !data.capabilities.execution_order_available}
            aria-pressed={view === mode}
            className={cn(
              'px-2 py-1 text-xs capitalize',
              view === mode ? 'bg-gray-900 text-white' : 'border border-gray-300 text-gray-600',
              'disabled:cursor-not-allowed disabled:opacity-40'
            )}
          >
            {mode}
          </button>
        ))}
        {showSearch && (
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search contract, address, slot, or variable"
            className="mt-2 w-full font-mono text-xs sm:ml-auto sm:mt-0 sm:max-w-md"
          />
        )}
      </div>

      {view === 'grouped' ? (
        <div className="border-t border-gray-300">
          <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 border-b border-gray-200 px-0 py-1 text-[9px] font-medium uppercase tracking-wide text-gray-400">
            <span className="pl-5">Contract</span>
            <span className="text-right">Activity</span>
          </div>
          {filteredContracts.map((contract) => (
            <ContractSection
              key={contract.storage_address}
              contract={contract}
              chain={chain}
              forceOpen={Boolean(search.trim())}
              defaultOpen={focusParam === contract.storage_address.toLowerCase()}
              executionOrderAvailable={data.capabilities.execution_order_available}
              isComplete={data.is_complete}
            />
          ))}
          {filteredContracts.length === 0 && <div className="border border-gray-300 p-8 text-center text-gray-500">No writes match the search</div>}
        </div>
      ) : (
        <Timeline entries={timeline} chain={chain} showContract={!singleContract} />
      )}
    </div>
  );
}
