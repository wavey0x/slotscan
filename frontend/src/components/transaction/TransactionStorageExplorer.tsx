'use client';

import { memo, useDeferredValue, useEffect, useMemo, useState } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { TransactionHeader } from '@/components/transaction/TransactionHeader';
import { DataQuality } from '@/components/transaction/DataQuality';
import { ContractSection, Timeline, TimelineEntry } from '@/components/transaction/TransactionStorageViews';
import { Input } from '@/components/ui/Input';
import { Loading } from '@/components/ui/Loading';
import { ViewSwitch } from '@/components/ui/ViewSwitch';
import { APIError } from '@/lib/api';
import { useTransactionStorageHistory } from '@/lib/hooks/useTransactionStorageHistory';
import {
  ContractHistoryResponse,
  SlotChangeResponse,
} from '@/lib/types';
import {
  contractDisplayLabel,
  hasRetryableContractResolution,
} from '@/lib/contract-resolution';
import { cn, removeRecentInspection, saveRecentInspection } from '@/lib/utils';

type ViewMode = 'grouped' | 'timeline';
type ValueMode = 'decoded' | 'hex';

interface TransactionStorageExplorerProps {
  chain: string;
  txHash: string;
}

const MemoizedContractSection = memo(ContractSection);
const MemoizedTimeline = memo(Timeline);

function searchableContract(contract: ContractHistoryResponse, slot: SlotChangeResponse) {
  return [
    contract.name,
    contractDisplayLabel(contract),
    contract.storage_address,
    ...contract.implementation_addresses,
    slot.slot,
    slot.variable_name,
    slot.variable_path,
    ...slot.resolved_paths,
    ...(slot.packed_fields ?? []).flatMap((field) => [field.name, field.type_label]),
  ].filter(Boolean).join(' ').toLowerCase();
}

export function TransactionStorageExplorer({ chain, txHash }: TransactionStorageExplorerProps) {
  const {
    data,
    isLoading,
    isFetching,
    error,
    refetch,
    resolutionAutoRetryFinished,
  } = useTransactionStorageHistory(chain, txHash);
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [search, setSearch] = useState('');
  const viewParam = searchParams.get('view');
  const urlView: ViewMode = viewParam === 'timeline' ? 'timeline' : 'grouped';
  const urlValueMode: ValueMode = searchParams.get('values') === 'hex' ? 'hex' : 'decoded';
  const [requestedView, setRequestedView] = useState<ViewMode>(urlView);
  const [pendingView, setPendingView] = useState<ViewMode | null>(null);
  const [valueMode, setValueMode] = useState<ValueMode>(urlValueMode);
  const deferredSearch = useDeferredValue(search);
  const view: ViewMode = requestedView === 'timeline' && data?.capabilities.execution_order_available
    ? 'timeline'
    : 'grouped';
  const selectedView = pendingView ?? view;
  const deferredView = useDeferredValue(view);
  const deferredValueMode = useDeferredValue(valueMode);
  const isViewPending = pendingView !== null || view !== deferredView;
  const showHex = deferredValueMode === 'hex';
  const loadedTxHash = data?.tx_hash;
  const transactionNotFound = error instanceof APIError && error.code === 'NOT_FOUND';
  const focusParam = searchParams.get('focus')?.toLowerCase() || null;

  useEffect(() => {
    setRequestedView(urlView);
    setValueMode(urlValueMode);
  }, [urlValueMode, urlView]);

  useEffect(() => {
    if (!pendingView) return;

    let renderFrame: number | null = null;
    const paintFrame = window.requestAnimationFrame(() => {
      renderFrame = window.requestAnimationFrame(() => {
        setRequestedView(pendingView);
        setPendingView(null);
        const next = new URLSearchParams(window.location.search);
        next.set('view', pendingView);
        window.history.replaceState(null, '', `${pathname}?${next.toString()}`);
      });
    });

    return () => {
      window.cancelAnimationFrame(paintFrame);
      if (renderFrame !== null) window.cancelAnimationFrame(renderFrame);
    };
  }, [pathname, pendingView]);

  useEffect(() => {
    if (!loadedTxHash) return;
    saveRecentInspection({
      chain,
      kind: 'transaction',
      value: loadedTxHash,
    });
  }, [chain, loadedTxHash]);

  useEffect(() => {
    if (!transactionNotFound) return;
    removeRecentInspection({
      chain,
      kind: 'transaction',
      value: txHash,
    });
  }, [chain, transactionNotFound, txHash]);

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
    if (mode === view) {
      setPendingView(null);
      return;
    }
    setPendingView(mode);
  };

  const selectValueMode = (mode: ValueMode) => {
    setValueMode(mode);
    const next = new URLSearchParams(window.location.search);
    if (mode === 'hex') next.set('values', 'hex');
    else next.delete('values');
    const query = next.toString();
    window.history.replaceState(null, '', query ? `${pathname}?${query}` : pathname);
  };

  const filteredContracts = useMemo(() => {
    if (!data || deferredView !== 'grouped') return [];
    const query = deferredSearch.trim().toLowerCase();
    if (!query) return data.contracts;
    return data.contracts.map((contract) => ({
      ...contract,
      slots: contract.slots.filter((slot) => searchableContract(contract, slot).includes(query)),
    })).filter((contract) => contract.slots.length > 0);
  }, [data, deferredSearch, deferredView]);

  const timelineEntries = useMemo(() => {
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
    return references.map((reference): TimelineEntry | null => {
      const contract = contracts.get(reference.storage_address.toLowerCase());
      const slot = slots.get(`${reference.storage_address.toLowerCase()}:${reference.slot}`);
      const event = slot?.changes[reference.event_index];
      if (!contract || !slot || !event) return null;
      return { contract, slot, event, ordinal: reference.ordinal };
    }).filter((entry): entry is TimelineEntry => entry !== null)
      .sort((a, b) => (a.event.step ?? Number.MAX_SAFE_INTEGER) - (b.event.step ?? Number.MAX_SAFE_INTEGER) || a.ordinal - b.ordinal);
  }, [data]);

  const timeline = useMemo(() => {
    if (deferredView !== 'timeline') return [];
    const query = deferredSearch.trim().toLowerCase();
    if (!query) return timelineEntries;
    return timelineEntries.filter(({ contract, slot }) => searchableContract(contract, slot).includes(query));
  }, [deferredSearch, deferredView, timelineEntries]);

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
    data.degraded_reason === 'trace_limit'
      && 'Execution history exceeded a safety limit; proven net storage changes are shown.',
    data.degraded_reason === 'tracer_unavailable'
      && 'Execution tracing is unavailable; proven net storage changes are shown.',
    !data.capabilities.write_history_complete && 'Write history is incomplete.',
    !data.capabilities.values_complete && 'Some event before-values are unknown.',
    !data.capabilities.rollback_classification_complete && 'Rollback classification is incomplete.',
    !data.capabilities.state_reconciliation_complete && 'Replayed values did not fully reconcile with final state.',
    !data.capabilities.execution_order_available && 'Global execution order is unavailable.',
    !data.capabilities.code_attribution_complete
      && 'Effective code attribution is unavailable; raw slots are shown.',
  ].filter(Boolean) as string[];
  const retryableResolution = hasRetryableContractResolution(data.contracts);

  const singleContract = data.contracts.length === 1 ? data.contracts[0] : null;
  const showSearch = data.summary.slots_written > 15 || data.contracts.length > 3;
  return (
    <div className="w-full" data-testid="transaction-report">
      <TransactionHeader
        chain={chain}
        data={data}
        resolutionRetry={retryableResolution && resolutionAutoRetryFinished ? {
          onClick: () => { void refetch(); },
          pending: isFetching,
        } : undefined}
      />
      {singleContract && !singleContract.layout_available && (
        <div className="-mt-4 mb-5 text-[10px] uppercase tracking-wide text-gray-500">Raw slots</div>
      )}

      <DataQuality warnings={warnings} />

      <div
        className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-gray-300 pb-3"
        data-testid="transaction-controls"
      >
        <div className="flex shrink-0 items-center gap-2" data-testid="transaction-view-controls">
          <ViewSwitch
            label="View"
            showLabel={false}
            value={selectedView}
            options={[
              { value: 'grouped', label: 'Grouped' },
              { value: 'timeline', label: 'Timeline', disabled: !data.capabilities.execution_order_available },
            ]}
            onChange={selectView}
          />
          <ViewSwitch
            label="Values"
            showLabel={false}
            value={valueMode}
            options={[
              { value: 'decoded', label: 'Decoded' },
              { value: 'hex', label: 'Hex' },
            ]}
            onChange={selectValueMode}
          />
        </div>
        {showSearch && (
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search contract, address, slot, or variable"
            className="h-7 min-w-0 shrink grow basis-72 px-2 py-0 font-mono text-xs"
          />
        )}
      </div>

      <div className="relative">
        {isViewPending && (
          <>
            <span
              className="sr-only"
              data-testid="view-loading-status"
              role="status"
            >
              Loading {selectedView} view
            </span>
            <div
              className="view-loading-glimmer pointer-events-none z-10"
              data-testid="view-loading-glimmer"
              aria-hidden="true"
            />
          </>
        )}
        <div
          className={cn(
            'min-w-0',
            isViewPending && 'pointer-events-none select-none opacity-40',
          )}
          data-testid="transaction-results"
          aria-busy={isViewPending}
          aria-hidden={isViewPending}
        >
          {deferredView === 'grouped' ? (
            <div>
              {filteredContracts.map((contract) => (
                <MemoizedContractSection
                  key={contract.storage_address}
                  contract={contract}
                  chain={chain}
                  forceOpen={Boolean(deferredSearch.trim())}
                  defaultOpen={focusParam === contract.storage_address.toLowerCase()}
                  executionOrderAvailable={data.capabilities.execution_order_available}
                  isComplete={data.is_complete}
                  showHex={showHex}
                />
              ))}
              {filteredContracts.length === 0 && <div className="border border-gray-300 p-8 text-center text-gray-500">No writes match the search</div>}
            </div>
          ) : (
            <MemoizedTimeline entries={timeline} chain={chain} showContract={!singleContract} showHex={showHex} />
          )}
        </div>
      </div>
    </div>
  );
}
