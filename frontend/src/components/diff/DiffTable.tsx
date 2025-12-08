'use client';

import { useState, useMemo } from 'react';
import { SlotChangeResponse } from '@/lib/types';
import { useTxDiff } from '@/lib/hooks/useTxDiff';
import { Loading } from '@/components/ui/Loading';
import { Toggle } from '@/components/ui/Toggle';
import { SlotRow } from './SlotRow';
import Link from 'next/link';

interface DiffTableProps {
  chainId: string;
  address: string;
  txHash: string;
}

export function DiffTable({ chainId, address, txHash }: DiffTableProps) {
  const { data, isLoading, error } = useTxDiff(chainId, address, txHash);
  const [showHex, setShowHex] = useState(false);

  // Sort slots by program counter (PC) - must be called before early returns
  const sortedSlots = useMemo(() => {
    if (!data?.slots) return [];
    return [...data.slots].sort((a: SlotChangeResponse, b: SlotChangeResponse) => {
      const pcA = a.changes.length > 0 ? (a.changes[0].pc ?? Infinity) : Infinity;
      const pcB = b.changes.length > 0 ? (b.changes[0].pc ?? Infinity) : Infinity;
      return pcA - pcB;
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

      <div className="border border-gray-200 overflow-x-auto">
        <table className="w-full min-w-[500px]">
          <thead className="bg-gray-50">
            <tr>
              <th className="w-6 px-1 py-1"></th>
              <th className="text-left px-1 py-1 text-[10px] font-medium text-gray-500 uppercase min-w-[180px]">Variable</th>
              <th className="text-left px-1 py-1 text-[10px] font-medium text-gray-500 uppercase">Value</th>
              <th className="text-left px-1 py-1 text-[10px] font-medium text-gray-500 uppercase w-10">Slot</th>
              <th className="text-right px-1 py-1 text-[10px] font-medium text-gray-500 uppercase">PC</th>
            </tr>
          </thead>
          <tbody>
            {sortedSlots.map((slot, index) => (
              <SlotRow
                key={index}
                slot={slot}
                showHex={showHex}
                chainId={chainId}
              />
            ))}
          </tbody>
        </table>
      </div>

      {!data.is_complete && (
        <div className="mt-2 text-xs text-gray-500">
          Truncated: showing first {data.slots.length} slots
        </div>
      )}

      <div className="mt-6 text-center">
        <Link
          href={`/${chainId}/${address}?block=${data.block_number}`}
          className="text-sm text-gray-500 hover:text-gray-900"
        >
          View full storage at block {data.block_number.toLocaleString()} &rarr;
        </Link>
      </div>
    </div>
  );
}
