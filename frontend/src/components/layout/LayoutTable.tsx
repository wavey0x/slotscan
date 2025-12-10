'use client';

import { useState, useMemo } from 'react';
import { StorageLayoutResponse, SlotValueResponse } from '@/lib/types';
import { Toggle } from '@/components/ui/Toggle';
import { LayoutRow } from './LayoutRow';
import { useStorage } from '@/lib/hooks/useStorage';

interface LayoutTableProps {
  chainId: string;
  address: string;
  layout: StorageLayoutResponse;
}

export function LayoutTable({
  chainId,
  address,
  layout,
}: LayoutTableProps) {
  const [showHex, setShowHex] = useState(false);

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
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          {storage?.block_number ? (
            <div className="flex flex-col text-xs">
              <span className="flex items-center gap-1.5">
                <span className="text-gray-400">Block</span>
                <span className="font-mono text-gray-700">{storage.block_number.toLocaleString()}</span>
              </span>
              <span className="text-gray-400">
                {layout.variables.length} variables
              </span>
            </div>
          ) : storageLoading ? (
            <span className="text-xs text-gray-400">Loading values...</span>
          ) : (
            <span className="text-xs text-gray-500">
              {layout.variables.length} variables
            </span>
          )}
        </div>
        <Toggle label="HEX" checked={showHex} onChange={setShowHex} />
      </div>

      <table className="w-full table-fixed">
        <colgroup>
          <col className="w-6" />
          <col className="w-[100px]" />
          <col className="w-[120px]" />
          <col className="w-10" />
          <col />
        </colgroup>
        <thead>
          <tr className="border-b border-gray-300">
            <th className="px-1 pt-2 pb-1"></th>
            <th className="text-left px-1 pt-2 pb-1 text-[10px] font-medium text-gray-500 uppercase">
              Name
            </th>
            <th className="text-left px-1 pt-2 pb-1 text-[10px] font-medium text-gray-500 uppercase">
              Type
            </th>
            <th className="text-left px-1 pt-2 pb-1 text-[10px] font-medium text-gray-500 uppercase">
              Slot
            </th>
            <th className="text-left px-1 pt-2 pb-1 text-[10px] font-medium text-gray-500 uppercase">
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
      </table>

      {layout.variables.length === 0 && (
        <div className="py-8 text-center text-gray-500 border-t border-gray-100">
          No storage variables found
        </div>
      )}
    </div>
  );
}
