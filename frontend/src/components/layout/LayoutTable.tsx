'use client';

import { useState } from 'react';
import { StorageLayoutResponse } from '@/lib/types';
import { Toggle } from '@/components/ui/Toggle';
import { LayoutRow } from './LayoutRow';

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

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="text-xs text-gray-500">
          {layout.variables.length} variables
        </div>
        <Toggle label="HEX" checked={showHex} onChange={setShowHex} />
      </div>

      <table className="w-full">
        <thead>
          <tr className="border-b border-gray-300">
            <th className="w-5 px-1 pt-2 pb-1"></th>
            <th className="text-left px-1 pt-2 pb-1 text-[10px] font-medium text-gray-500 uppercase">
              Name
            </th>
            <th className="text-left px-1 pt-2 pb-1 text-[10px] font-medium text-gray-500 uppercase">
              Type
            </th>
            <th className="text-left px-1 pt-2 pb-1 text-[10px] font-medium text-gray-500 uppercase w-16">
              Slot
            </th>
            <th className="text-left px-1 pt-2 pb-1 text-[10px] font-medium text-gray-500 uppercase w-12">
              Offset
            </th>
            <th className="text-left px-1 pt-2 pb-1 text-[10px] font-medium text-gray-500 uppercase w-12">
              Bytes
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
