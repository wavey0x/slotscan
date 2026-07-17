'use client';

import { useMemo } from 'react';
import { SlotChangeResponse } from '@/lib/types';
import { SlotRow } from './SlotRow';
import { StorageTable, StorageTableColumns, StorageTableHeader } from './StorageTable';

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
      <StorageTable>
        <StorageTableColumns showExpand showStep={executionOrderAvailable} />
        <StorageTableHeader showExpand showStep={executionOrderAvailable} />
        <tbody>
          {sortedSlots.map((slot, index) => (
            <SlotRow
              key={`${slot.namespace}:${slot.slot}`}
              slot={slot}
              showHex={showHex}
              chainId={chainId}
              showStep={executionOrderAvailable}
              isFirst={index === 0}
            />
          ))}
        </tbody>
      </StorageTable>

      {!isComplete && (
        <div className="mt-2 text-xs text-gray-500">
          The trace or projection is incomplete; some write history may be absent.
        </div>
      )}
    </div>
  );
}
