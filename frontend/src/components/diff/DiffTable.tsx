'use client';

import { useState, useMemo } from 'react';
import { SlotChangeResponse } from '@/lib/types';
import { useTxDiff } from '@/lib/hooks/useTxDiff';
import { Loading } from '@/components/ui/Loading';
import { Toggle } from '@/components/ui/Toggle';
import { SlotRow } from './SlotRow';

interface DiffTableProps {
  chainId: string;
  address: string;
  txHash: string;
}

export function DiffTable({ chainId, address, txHash }: DiffTableProps) {
  const { data, isLoading, error } = useTxDiff(chainId, address, txHash);
  const [showHex, setShowHex] = useState(false);

  // Sort slots by step (execution order) - must be called before early returns
  const sortedSlots = useMemo(() => {
    if (!data?.slots) return [];
    return [...data.slots].sort((a: SlotChangeResponse, b: SlotChangeResponse) => {
      const stepA = a.changes.length > 0 ? a.changes[0].step : Infinity;
      const stepB = b.changes.length > 0 ? b.changes[0].step : Infinity;
      return stepA - stepB;
    });
  }, [data?.slots]);

  if (isLoading) {
    return <Loading />;
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
    <div>
      <div className="flex items-center justify-end mb-4">
        <Toggle
          label="HEX"
          checked={showHex}
          onChange={setShowHex}
        />
      </div>

      <table className="w-full">
        <thead>
          <tr className="border-b border-gray-300">
            <th className="w-5 px-1 pt-2 pb-1"></th>
            <th className="text-left px-1 pt-2 pb-1 text-[10px] font-medium text-gray-500 uppercase w-48">Variable</th>
            <th className="text-left px-1 pt-2 pb-1 text-[10px] font-medium text-gray-500 uppercase">Value</th>
            <th className="text-left px-1 pt-2 pb-1 text-[10px] font-medium text-gray-500 uppercase w-8">Slot</th>
            {data?.execution_order_available && (
              <th className="text-right px-1 pt-2 pb-1 text-[10px] font-medium text-gray-500 uppercase w-10">
                Step
              </th>
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {sortedSlots.map((slot, index) => (
            <SlotRow
              key={index}
              slot={slot}
              showHex={showHex}
              chainId={chainId}
              showStep={data?.execution_order_available ?? false}
              isFirst={index === 0}
            />
          ))}
        </tbody>
      </table>

      {!data.is_complete && (
        <div className="mt-2 text-xs text-gray-500">
          Truncated: showing first {data.slots.length} slots
        </div>
      )}
    </div>
  );
}
