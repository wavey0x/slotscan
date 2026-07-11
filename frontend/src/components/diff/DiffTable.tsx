'use client';

import { useMemo } from 'react';
import { SlotChangeResponse } from '@/lib/types';
import { useTxDiff } from '@/lib/hooks/useTxDiff';
import { Loading } from '@/components/ui/Loading';
import { SlotRow } from './SlotRow';

interface DiffTableProps {
  chainId: string;
  address: string;
  txHash: string;
  showHex: boolean;
}

interface SlotHistoryTableProps {
  chainId: string;
  slots: SlotChangeResponse[];
  showHex: boolean;
  executionOrderAvailable: boolean;
  isComplete?: boolean;
}

export function SlotHistoryTable({
  chainId,
  slots,
  showHex,
  executionOrderAvailable,
  isComplete = true,
}: SlotHistoryTableProps) {
  const sortedSlots = useMemo(() => {
    return [...slots].sort((a, b) => {
      const stepA = a.changes.length > 0 ? (a.changes[0].step ?? Infinity) : Infinity;
      const stepB = b.changes.length > 0 ? (b.changes[0].step ?? Infinity) : Infinity;
      if (stepA !== stepB) return stepA - stepB;
      return a.slot.localeCompare(b.slot);
    });
  }, [slots]);

  if (sortedSlots.length === 0) {
    return (
      <div className="text-gray-500 p-8 text-center border border-gray-300">
        No storage histories match the current filters
      </div>
    );
  }

  return (
    <div>
      <table className="w-full table-fixed">
        <colgroup>
          <col className="w-5" />
          <col className="w-[38%]" />
          <col />
          <col className="w-14" />
          {executionOrderAvailable && <col className="w-14" />}
        </colgroup>
        <thead>
          <tr className="border-b border-gray-200">
            <th className="w-5 px-1 py-1"></th>
            <th className="px-1 py-1 text-left text-[9px] font-medium uppercase tracking-wide text-gray-400">Variable</th>
            <th className="px-1 py-1 text-left text-[9px] font-medium uppercase tracking-wide text-gray-400">Value diff</th>
            <th className="px-1 py-1 text-left text-[9px] font-medium uppercase tracking-wide text-gray-400">Slot</th>
            {executionOrderAvailable && (
              <th className="px-1 py-1 text-right text-[9px] font-medium uppercase tracking-wide text-gray-400">
                Step
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {sortedSlots.map((slot, index) => (
            <SlotRow
              key={`${slot.namespace}:${slot.slot}`}
              slot={slot}
              showHex={showHex}
              chainId={chainId}
              showStep={executionOrderAvailable}
              isFirst={index === 0}
              isLast={index === sortedSlots.length - 1}
            />
          ))}
        </tbody>
      </table>

      {!isComplete && (
        <div className="mt-2 text-xs text-gray-500">
          The trace or projection is incomplete; some write history may be absent.
        </div>
      )}
    </div>
  );
}

export function DiffTable({ chainId, address, txHash, showHex }: DiffTableProps) {
  const { data, isLoading, error } = useTxDiff(chainId, address, txHash);

  if (isLoading) {
    return (
      <Loading
        messages={[
          'Fetching transaction',
          'Tracing execution',
          'Extracting SSTOREs',
          'Matching storage slots',
          'Decoding values',
        ]}
        subtitle="This may take up to 2 minutes"
      />
    );
  }

  if (error) {
    return (
      <div className="text-red p-4 border border-gray-300">
        Failed to load transaction: {(error as Error).message}
      </div>
    );
  }

  if (data?.trace_unavailable) {
    return (
      <div className="p-6 border border-gray-300">
        <div className="text-gray-900 mb-2">Tracing unavailable</div>
        <p className="text-sm text-gray-500">
          The RPC node does not support debug_traceTransaction.
          Storage changes cannot be displayed.
        </p>
      </div>
    );
  }

  if (!data || data.slots.length === 0) {
    return (
      <div className="text-gray-500 p-8 text-center border border-gray-300">
        No storage changes in this transaction
      </div>
    );
  }

  return (
    <SlotHistoryTable
      chainId={chainId}
      slots={data.slots}
      showHex={showHex}
      executionOrderAvailable={data.execution_order_available}
      isComplete={data.is_complete}
    />
  );
}
