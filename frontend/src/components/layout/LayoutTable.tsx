'use client';

import { useMemo } from 'react';
import { StorageLayoutResponse, SlotValueResponse } from '@/lib/types';
import { LayoutRow } from './LayoutRow';
import { useStorage } from '@/lib/hooks/useStorage';
import { DataTable, dataTableHeadCellClass } from '@/components/ui/DataTable';

interface LayoutTableProps {
  chainId: string;
  address: string;
  layout: StorageLayoutResponse;
  showHex: boolean;
}

export function LayoutTable({
  chainId,
  address,
  layout,
  showHex,
}: LayoutTableProps) {
  // Fetch storage values at latest block
  const { data: storage, isLoading: storageLoading } = useStorage(chainId, address, 'latest');

  // Create a map of slot number to value for quick lookup
  const slotValues = useMemo(() => {
    const map: Record<number, SlotValueResponse> = {};
    if (storage?.slots) {
      for (const slot of storage.slots) {
        // Parse slot hex string to number for matching
        const slotNum = parseInt(slot.slot, 16);
        map[slotNum] = slot;
      }
    }
    return map;
  }, [storage?.slots]);

  return (
    <div>
      <DataTable minWidth="40rem">
        <colgroup>
          <col className="w-6" />
          <col className="w-[100px]" />
          <col className="w-[120px]" />
          <col className="w-[72px]" />
          <col />
        </colgroup>
        <thead>
          <tr className="border-b border-gray-300">
            <th className="px-2 py-1.5"></th>
            <th className={dataTableHeadCellClass}>
              Name
            </th>
            <th className={dataTableHeadCellClass}>
              Type
            </th>
            <th className={dataTableHeadCellClass}>
              Slot
            </th>
            <th className={dataTableHeadCellClass}>
              Value
            </th>
          </tr>
        </thead>
        <tbody>
          {layout.variables.map((variable, index) => (
            <LayoutRow
              key={index}
              variable={variable}
              types={layout.types}
              chainId={chainId}
              address={address}
              showHex={showHex}
              slotValue={slotValues[variable.slot]}
              storageLoading={storageLoading}
            />
          ))}
        </tbody>
      </DataTable>

      {layout.variables.length === 0 && (
        <div className="py-8 text-center text-gray-500 border-t border-gray-100">
          No storage variables found
        </div>
      )}
    </div>
  );
}
