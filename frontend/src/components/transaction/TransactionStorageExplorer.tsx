'use client';

import { useEffect, useMemo, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { TransactionHeader } from '@/components/transaction/TransactionHeader';
import { DataQuality } from '@/components/transaction/DataQuality';
import { ContractSection, Timeline, TimelineEntry } from '@/components/transaction/TransactionStorageViews';
import { Input } from '@/components/ui/Input';
import { Loading } from '@/components/ui/Loading';
import { ViewSwitch } from '@/components/ui/ViewSwitch';
import { useTransactionStorageHistory } from '@/lib/hooks/useTransactionStorageHistory';
import {
  ContractHistoryResponse,
  SlotChangeResponse,
} from '@/lib/types';

type ViewMode = 'grouped' | 'timeline';

interface TransactionStorageExplorerProps {
  chain: string;
  txHash: string;
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

      <div className="mb-5 flex flex-wrap items-center gap-2 border-b border-gray-300 pb-3">
        <ViewSwitch
          label="View"
          showLabel={false}
          value={view}
          options={[
            { value: 'grouped', label: 'Grouped' },
            { value: 'timeline', label: 'Timeline', disabled: !data.capabilities.execution_order_available },
          ]}
          onChange={selectView}
        />
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
        <div>
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
