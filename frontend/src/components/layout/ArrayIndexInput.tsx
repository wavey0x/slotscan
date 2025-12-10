'use client';

import { useState } from 'react';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import { HoverCell } from '@/components/ui/HoverCell';
import { StorageTypeResponse, ComputedSlotLookup } from '@/lib/types';
import { fetchSlotValue } from '@/lib/api';
import {
  computeDynamicArraySlot,
  computeStaticArraySlot,
  slotToHex,
} from '@/lib/slot-utils';
import { cn } from '@/lib/utils';

interface ArrayIndexInputProps {
  baseSlot: number;
  elementType?: StorageTypeResponse;
  isDynamic: boolean;
  arrayLength?: number;
  chainId: string;
  address: string;
  lookups: ComputedSlotLookup[];
  onLookup: (lookup: ComputedSlotLookup) => void;
}

function formatDecodedValue(value: unknown, rawValue?: string): string {
  if (value !== null && value !== undefined) {
    if (typeof value === 'boolean') return value ? 'true' : 'false';
    if (typeof value === 'bigint') return value.toString();
    if (typeof value === 'number') return value.toLocaleString();
    if (typeof value === 'string') {
      if (value === '0x0000000000000000000000000000000000000000') return '0x0...0';
      return value;
    }
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }
  // Fall back to raw value interpretation
  if (rawValue) {
    // Check if all zeros
    if (rawValue === '0x' + '0'.repeat(64)) return '0';
    // Try to interpret as uint256
    try {
      const bigVal = BigInt(rawValue);
      return bigVal.toString();
    } catch {
      return rawValue;
    }
  }
  return '-';
}

function truncateSlot(slot: string): string {
  if (slot.length <= 18) return slot;
  return slot.substring(0, 10) + '...' + slot.substring(slot.length - 6);
}

export function ArrayIndexInput({
  baseSlot,
  elementType,
  isDynamic,
  arrayLength,
  chainId,
  address,
  lookups,
  onLookup,
}: ArrayIndexInputProps) {
  const [indexInput, setIndexInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Calculate element slots based on element type
  const elementSlots = elementType?.num_bytes
    ? Math.ceil(elementType.num_bytes / 32)
    : 1;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const index = parseInt(indexInput, 10);
    if (isNaN(index) || index < 0) {
      setError('Invalid index');
      return;
    }

    // Validate against array length for static arrays
    if (!isDynamic && arrayLength !== undefined && index >= arrayLength) {
      setError(`Index out of bounds (max: ${arrayLength - 1})`);
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      // Compute the slot for the array element
      let computedSlot: bigint;

      if (isDynamic) {
        // Dynamic array: keccak256(baseSlot) + index * elementSlots
        computedSlot = computeDynamicArraySlot(
          BigInt(baseSlot),
          index,
          elementSlots
        );
      } else {
        // Static array: baseSlot + index * elementSlots
        computedSlot = computeStaticArraySlot(
          BigInt(baseSlot),
          index,
          elementSlots
        );
      }

      const slotHex = slotToHex(computedSlot);

      // Fetch the value at latest block
      const result = await fetchSlotValue(chainId, address, slotHex, 'latest');

      // Add to lookups
      onLookup({
        index,
        computedSlot: slotHex,
        rawValue: result.value_encoded,
        decodedValue: result.value_decoded,
      });

      // Clear input after successful lookup
      setIndexInput('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Lookup failed');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      {/* Input form */}
      <form onSubmit={handleSubmit} className="flex items-center gap-2">
        <Input
          type="number"
          min={0}
          max={!isDynamic && arrayLength ? arrayLength - 1 : undefined}
          value={indexInput}
          onChange={(e) => {
            setIndexInput(e.target.value);
            setError(null);
          }}
          placeholder={
            !isDynamic && arrayLength
              ? `Enter index (0-${arrayLength - 1})`
              : 'Enter array index'
          }
          className="w-48 h-7 text-xs font-mono"
          disabled={isLoading}
        />
        <Button
          type="submit"
          variant="secondary"
          size="sm"
          className="h-7 text-xs"
          disabled={isLoading || !indexInput}
        >
          {isLoading ? 'Loading...' : 'Lookup'}
        </Button>
        <span className="text-[10px] text-gray-400 ml-2">
          {isDynamic ? 'dynamic array' : `${arrayLength} elements`}
          {elementType?.label && ` of ${elementType.label}`}
        </span>
      </form>

      {error && <p className="text-red text-xs">{error}</p>}

      {/* Lookup results */}
      {lookups.length > 0 && (
        <div className="mt-4">
          <div className="text-[10px] uppercase tracking-wide text-gray-500 font-medium mb-2">
            Lookup History
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-1.5 px-1 text-gray-500 font-medium w-20">
                  Index
                </th>
                <th className="text-left py-1.5 px-1 text-gray-500 font-medium">
                  Slot
                </th>
                <th className="text-left py-1.5 px-1 text-gray-500 font-medium">
                  Value
                </th>
              </tr>
            </thead>
            <tbody>
              {lookups.map((lookup, idx) => {
                const isZero =
                  lookup.rawValue === '0x' + '0'.repeat(64) ||
                  lookup.decodedValue === 0 ||
                  lookup.decodedValue === '0' ||
                  lookup.decodedValue === '0x0000000000000000000000000000000000000000';

                return (
                  <tr key={idx} className="border-b border-gray-100">
                    <td className="py-1.5 px-1">
                      <span className="font-mono text-gray-700">
                        [{lookup.index}]
                      </span>
                    </td>
                    <td className="py-1.5 px-1">
                      <HoverCell
                        display={truncateSlot(lookup.computedSlot)}
                        value={lookup.computedSlot}
                        colorClass="font-mono text-gray-500"
                      />
                    </td>
                    <td className="py-1.5 px-1">
                      <HoverCell
                        display={formatDecodedValue(lookup.decodedValue, lookup.rawValue)}
                        value={lookup.rawValue}
                        chainId={chainId}
                        colorClass={cn(
                          'font-mono',
                          isZero ? 'text-gray-300' : 'text-gray-900'
                        )}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
