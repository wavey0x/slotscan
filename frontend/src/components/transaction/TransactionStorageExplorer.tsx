'use client';

import { useMemo, useState } from 'react';
import { SlotHistoryTable } from '@/components/diff/DiffTable';
import { CopyButton } from '@/components/ui/CopyButton';
import { EtherscanLink } from '@/components/ui/EtherscanLink';
import { Input } from '@/components/ui/Input';
import { Loading } from '@/components/ui/Loading';
import { Toggle } from '@/components/ui/Toggle';
import { getAddressExplorerUrl, getBlockExplorerUrl, getTxExplorerUrl } from '@/lib/constants';
import { useTransactionStorageHistory } from '@/lib/hooks/useTransactionStorageHistory';
import {
  ContractHistoryResponse,
  SlotChangeResponse,
  StorageChangeResponse,
} from '@/lib/types';
import {
  cn,
  formatDecodedValue,
  truncateAddress,
  truncateHash,
} from '@/lib/utils';

type ViewMode = 'grouped' | 'timeline';
type Scope = 'all' | 'net_changed' | 'restored' | 'reverted';

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

const scopeLabels: Record<Scope, string> = {
  all: 'All changes',
  net_changed: 'Net effects',
  restored: 'Restored',
  reverted: 'Reverted',
};

function slotMatchesScope(slot: SlotChangeResponse, scope: Scope, showNoops: boolean) {
  if (!showNoops && slot.classification === 'noop_only') return false;
  if (scope === 'all') return true;
  if (scope === 'net_changed') return slot.classification === 'net_changed';
  if (scope === 'restored') return slot.classification === 'restored';
  return slot.classification === 'reverted_only'
    || slot.changes.some((event) => event.frame_outcome === 'reverted');
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

function eventValue(event: StorageChangeResponse, side: 'before' | 'after', showHex: boolean) {
  const pair = event[side];
  if (showHex) return pair.value_encoded ?? 'unknown';
  return pair.value_decoded === null || pair.value_decoded === undefined
    ? pair.value_encoded ?? 'unknown'
    : formatDecodedValue(pair.value_decoded);
}

function ContractIndex({ contracts }: { contracts: ContractHistoryResponse[] }) {
  if (contracts.length < 2) return null;
  return (
    <nav className="sticky top-0 z-10 mb-6 border border-gray-300 bg-white/95 backdrop-blur" aria-label="Storage owners">
      <div className="flex gap-1 overflow-x-auto p-2">
        {contracts.map((contract) => (
          <a
            key={contract.storage_address}
            href={`#owner-${contract.storage_address.slice(2)}`}
            className="min-w-40 border border-transparent px-2 py-1.5 hover:border-gray-300"
          >
            <div className="truncate text-xs font-medium text-gray-900">
              {contract.name || truncateAddress(contract.storage_address)}
            </div>
            <div className="mt-0.5 text-[10px] text-gray-500">
              {contract.counts.slots_written} slots · {contract.counts.sstore_events} writes
            </div>
          </a>
        ))}
      </div>
    </nav>
  );
}

function Timeline({ entries, chain, showHex }: { entries: TimelineEntry[]; chain: string; showHex: boolean }) {
  if (entries.length === 0) {
    return <div className="border border-gray-300 p-8 text-center text-gray-500">No events match the current filters</div>;
  }

  return (
    <div className="border-t border-gray-300">
      {entries.map(({ contract, slot, event, ordinal }) => (
        <div
          key={`${contract.storage_address}:${slot.slot}:${event.step}:${ordinal}`}
          data-testid="timeline-event"
          className="grid grid-cols-[4rem_minmax(8rem,12rem)_minmax(10rem,1fr)_minmax(12rem,1.4fr)] gap-3 border-b border-gray-200 py-2 text-xs"
        >
          <div className="font-mono text-gray-400">{event.step ?? '—'}</div>
          <a
            href={getAddressExplorerUrl(chain, contract.storage_address)}
            target="_blank"
            rel="noopener noreferrer"
            className="truncate text-gray-700 hover:underline"
          >
            {contract.name || truncateAddress(contract.storage_address)}
          </a>
          <div className="truncate font-mono text-gray-900" title={slot.variable_path || slot.slot}>
            {slot.variable_path || slot.variable_name || truncateHash(slot.slot, 7)}
          </div>
          <div className="min-w-0 font-mono">
            <span className="break-all text-gray-400">{eventValue(event, 'before', showHex)}</span>
            <span className="mx-1 text-gray-400">→</span>
            <span className="break-all text-gray-900">{eventValue(event, 'after', showHex)}</span>
            {(event.frame_outcome === 'reverted' || event.changed_value === false) && (
              <span className={cn(
                'ml-2 text-[9px] uppercase tracking-wide',
                event.frame_outcome === 'reverted' ? 'text-amber-600' : 'text-gray-400'
              )}>
                {event.frame_outcome === 'reverted' ? 'reverted' : 'no-op'}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

export function TransactionStorageExplorer({ chain, txHash }: TransactionStorageExplorerProps) {
  const { data, isLoading, error } = useTransactionStorageHistory(chain, txHash);
  const [view, setView] = useState<ViewMode>('grouped');
  const [scope, setScope] = useState<Scope>('all');
  // Forensic mode defaults to the complete write inventory. Users can hide
  // no-op-only slots when they want a lower-noise operational view.
  const [showNoops, setShowNoops] = useState(true);
  const [showHex, setShowHex] = useState(false);
  const [search, setSearch] = useState('');

  const filteredContracts = useMemo(() => {
    if (!data) return [];
    const query = search.trim().toLowerCase();
    return data.contracts.map((contract) => ({
      ...contract,
      slots: contract.slots.filter((slot) => (
        slotMatchesScope(slot, scope, showNoops)
        && (!query || searchableContract(contract, slot).includes(query))
      )),
    })).filter((contract) => contract.slots.length > 0);
  }, [data, scope, showNoops, search]);

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
      if (!slotMatchesScope(slot, scope, showNoops)) return null;
      if (!showNoops && event.changed_value === false) return null;
      if (query && !searchableContract(contract, slot).includes(query)) return null;
      return { contract, slot, event, ordinal: reference.ordinal };
    }).filter((entry): entry is TimelineEntry => entry !== null)
      .sort((a, b) => (a.event.step ?? Number.MAX_SAFE_INTEGER) - (b.event.step ?? Number.MAX_SAFE_INTEGER) || a.ordinal - b.ordinal);
  }, [data, scope, showNoops, search]);

  if (isLoading) {
    return <Loading messages={['Loading transaction trace', 'Replaying storage writes', 'Resolving storage owners', 'Decoding slot histories']} subtitle="Large transactions can take up to two minutes" />;
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

  const summary = data.summary;
  const summaryItems = [
    ['Owners', summary.storage_owners],
    ['Slots', summary.slots_written],
    ['SSTOREs', summary.sstore_events],
    ['Net', summary.net_changed_slots],
    ['Restored', summary.restored_slots],
    ['Reverted', summary.reverted_writes],
    ['No-op', summary.noop_writes],
    ['Resolved', `${summary.resolved_slots}/${summary.slots_written}`],
  ];

  return (
    <div>
      <header className="mb-6">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-medium text-gray-900">Transaction storage history</h1>
          <span className={cn('text-[10px] uppercase tracking-wide', data.status === 'success' ? 'text-emerald-700' : 'text-amber-600')}>{data.status}</span>
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-sm leading-snug">
          <dt className="text-gray-500">Txn:</dt>
          <dd className="flex items-center gap-1 font-mono"><span>{truncateHash(data.tx_hash, 12)}</span><CopyButton value={data.tx_hash} /><EtherscanLink href={getTxExplorerUrl(chain, data.tx_hash)} title="View transaction" /></dd>
          <dt className="text-gray-500">Block:</dt>
          <dd className="flex items-center gap-1 font-mono"><span>{data.block_number.toLocaleString()}</span><EtherscanLink href={getBlockExplorerUrl(chain, data.block_number)} title="View block" /></dd>
          {data.from_address && <><dt className="text-gray-500">From:</dt><dd><a className="font-mono hover:underline" href={getAddressExplorerUrl(chain, data.from_address)} target="_blank" rel="noopener noreferrer">{truncateAddress(data.from_address)}</a></dd></>}
          {(data.to_address || data.created_contract) && <><dt className="text-gray-500">To:</dt><dd><a className="font-mono hover:underline" href={getAddressExplorerUrl(chain, data.to_address || data.created_contract!)} target="_blank" rel="noopener noreferrer">{truncateAddress(data.to_address || data.created_contract!)}</a></dd></>}
        </dl>
      </header>

      <div className="mb-6 grid grid-cols-4 border-l border-t border-gray-300 sm:grid-cols-8">
        {summaryItems.map(([label, value]) => <div key={label} className="border-b border-r border-gray-300 p-2"><div className="text-[9px] uppercase tracking-wide text-gray-400">{label}</div><div className="font-mono text-sm text-gray-900">{value}</div></div>)}
      </div>

      {warnings.length > 0 && <div className="mb-5 border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">{warnings.join(' ')}</div>}

      <div className="mb-6 space-y-3 border-y border-gray-300 py-3">
        <div className="flex flex-wrap items-center gap-2">
          {(['grouped', 'timeline'] as ViewMode[]).map((mode) => <button key={mode} onClick={() => setView(mode)} disabled={mode === 'timeline' && !data.capabilities.execution_order_available} className={cn('px-2 py-1 text-xs capitalize', view === mode ? 'bg-gray-900 text-white' : 'border border-gray-300 text-gray-600', 'disabled:cursor-not-allowed disabled:opacity-40')}>{mode}</button>)}
          <span className="mx-1 h-4 border-l border-gray-300" />
          {(Object.keys(scopeLabels) as Scope[]).map((item) => <button key={item} onClick={() => setScope(item)} className={cn('px-2 py-1 text-xs', scope === item ? 'bg-gray-200 text-gray-900' : 'text-gray-500 hover:text-gray-900')}>{scopeLabels[item]}</button>)}
          <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs text-gray-500"><input type="checkbox" checked={showNoops} onChange={(event) => setShowNoops(event.target.checked)} />No-op writes</label>
          <Toggle label="HEX" checked={showHex} onChange={setShowHex} />
        </div>
        <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filter contract, address, slot, or variable path" className="w-full font-mono text-xs" />
      </div>

      {view === 'grouped' ? (
        <>
          <ContractIndex contracts={filteredContracts} />
          <div className="space-y-10">
            {filteredContracts.map((contract) => (
              <section key={contract.storage_address} id={`owner-${contract.storage_address.slice(2)}`} className="scroll-mt-16">
                <header className="mb-3 border-b border-gray-300 pb-2">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <h2 className="font-medium text-gray-900">{contract.name || 'Unresolved contract'}</h2>
                    <a href={getAddressExplorerUrl(chain, contract.storage_address)} target="_blank" rel="noopener noreferrer" className="font-mono text-xs text-gray-500 hover:underline">{truncateAddress(contract.storage_address)}</a>
                    {contract.is_proxy && <span className="text-[9px] uppercase tracking-wide text-blue-600">proxy</span>}
                    {!contract.layout_available && <span className="text-[9px] uppercase tracking-wide text-gray-400">raw slots</span>}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-4 text-[10px] text-gray-500">
                    <span>{contract.counts.slots_written} slots</span><span>{contract.counts.sstore_events} writes</span><span>{contract.counts.net_changed_slots} net</span><span>{contract.counts.restored_slots} restored</span><span>{contract.counts.reverted_writes} reverted</span><span>{contract.resolution.resolved}/{contract.resolution.total} resolved</span>
                  </div>
                  {contract.implementation_addresses.length > 0 && <div className="mt-1 text-[10px] text-gray-500">written via {contract.implementation_addresses.map(truncateAddress).join(', ')}</div>}
                  {contract.errors.map((message) => <div key={message} className="mt-1 text-[10px] text-amber-600">{message}; showing raw history</div>)}
                </header>
                <SlotHistoryTable chainId={chain} slots={contract.slots} showHex={showHex} executionOrderAvailable={data.capabilities.execution_order_available} isComplete={data.is_complete} />
              </section>
            ))}
            {filteredContracts.length === 0 && <div className="border border-gray-300 p-8 text-center text-gray-500">No storage histories match the current filters</div>}
          </div>
        </>
      ) : <Timeline entries={timeline} chain={chain} showHex={showHex} />}
    </div>
  );
}
