'use client';

import { useState } from 'react';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import { StorageTypeResponse, ComputedSlotLookup } from '@/lib/types';
import { fetchSlotValue } from '@/lib/api';
import {
  computeDynamicArraySlot,
  computeStaticArraySlot,
  slotToHex,
} from '@/lib/slot-utils';
import { LookupResultsTable } from './LookupResultsTable';

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

      <LookupResultsTable
        lookups={lookups}
        chainId={chainId}
        keyLabel="Index"
        renderKey={(lookup) => `[${lookup.index}]`}
      />
    </div>
  );
}
