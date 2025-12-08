'use client';

import { useStorage } from '@/lib/hooks/useStorage';
import { Loading } from '@/components/ui/Loading';
import { SlotValueResponse } from '@/lib/types';
import { ValueDisplay } from './ValueDisplay';

interface StorageTreeProps {
  chainId: string;
  address: string;
  blockNumber: number;
}

export function StorageTree({ chainId, address, blockNumber }: StorageTreeProps) {
  const { data, isLoading, error } = useStorage(chainId, address, blockNumber);

  if (isLoading) {
    return <Loading message="Reading storage" />;
  }

  if (error) {
    return (
      <div className="text-red p-4 border border-gray-300">
        Failed to load storage: {(error as Error).message}
      </div>
    );
  }

  if (!data || data.slots.length === 0) {
    return (
      <div className="text-gray-500 p-8 text-center border border-gray-300">
        No storage values found
      </div>
    );
  }

  return (
    <div className="border border-gray-300">
      <div className="bg-gray-100 px-4 py-2 border-b border-gray-300 flex items-center justify-between">
        <span className="text-xs text-gray-700">
          {data.slots.length} slot{data.slots.length !== 1 ? 's' : ''} · block {blockNumber.toLocaleString()}
        </span>
        {data.is_verified ? (
          <span className="text-xs text-green">Layout available</span>
        ) : (
          <span className="text-xs text-gray-500">Raw slots</span>
        )}
      </div>
      <div className="divide-y divide-gray-300">
        {data.slots.map((slot) => (
          <SlotRow key={slot.slot} slot={slot} />
        ))}
      </div>
      {!data.is_complete && (
        <div className="bg-gray-100 px-4 py-2 text-xs text-gray-700 border-t border-gray-300">
          Truncated · showing first {data.slots.length} slots
        </div>
      )}
    </div>
  );
}

function SlotRow({ slot }: { slot: SlotValueResponse }) {
  return (
    <div className="px-4 py-3 hover:bg-gray-100">
      <div className="flex items-start gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-900">
              {slot.variable_path || slot.variable_name || `Slot ${parseInt(slot.slot, 16)}`}
            </span>
            {slot.type_label && (
              <span className="text-xs text-gray-500">{slot.type_label}</span>
            )}
          </div>
          <div className="text-xs text-gray-500 mt-0.5">
            {slot.slot}
          </div>
        </div>
        <div className="text-right">
          <ValueDisplay
            value={slot.display_value || String(slot.decoded_value) || slot.raw_value}
            rawValue={slot.raw_value}
            typeLabel={slot.type_label}
          />
        </div>
      </div>
    </div>
  );
}
