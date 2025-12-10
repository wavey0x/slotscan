'use client';

import { useState } from 'react';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import { HoverCell } from '@/components/ui/HoverCell';
import { StorageTypeResponse, ComputedSlotLookup } from '@/lib/types';
import { fetchSlotValue } from '@/lib/api';
import {
  computeMappingSlot,
  computeNestedMappingSlot,
  slotToHex,
  getKeyTypeHint,
  validateKey,
} from '@/lib/slot-utils';
import { cn } from '@/lib/utils';

interface MappingKeyInputProps {
  baseSlot: number;
  keyTypes: { type: string; label: string }[];
  valueType?: StorageTypeResponse;
  chainId: string;
  address: string;
  block: number | 'latest';
  lookups: ComputedSlotLookup[];
  onLookup: (lookup: ComputedSlotLookup) => void;
}

function formatDecodedValue(value: unknown): string {
  if (value === null || value === undefined) return '-';
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

function truncateSlot(slot: string): string {
  if (slot.length <= 18) return slot;
  return slot.substring(0, 10) + '...' + slot.substring(slot.length - 6);
}

export function MappingKeyInput({
  baseSlot,
  keyTypes,
  valueType,
  chainId,
  address,
  block,
  lookups,
  onLookup,
}: MappingKeyInputProps) {
  const [keys, setKeys] = useState<string[]>(keyTypes.map(() => ''));
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleKeyChange = (index: number, value: string) => {
    const newKeys = [...keys];
    newKeys[index] = value;
    setKeys(newKeys);
    setError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Validate all keys
    for (let i = 0; i < keys.length; i++) {
      const validationError = validateKey(keys[i], keyTypes[i].type);
      if (validationError) {
        setError(`Key ${i + 1}: ${validationError}`);
        return;
      }
    }

    // Check block
    if (block === 'latest') {
      setError('Enter a block number first');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      // Compute the slot
      let computedSlot: bigint;

      if (keys.length === 1) {
        computedSlot = computeMappingSlot(
          BigInt(baseSlot),
          keys[0],
          keyTypes[0].type
        );
      } else {
        computedSlot = computeNestedMappingSlot(
          BigInt(baseSlot),
          keys.map((value, i) => ({ value, type: keyTypes[i].type }))
        );
      }

      const slotHex = slotToHex(computedSlot);

      // Fetch the value
      const result = await fetchSlotValue(chainId, address, slotHex, block);

      // Add to lookups
      onLookup({
        keys: [...keys],
        computedSlot: slotHex,
        rawValue: result.value_encoded,
        decodedValue: result.value_decoded,
      });

      // Clear inputs after successful lookup
      setKeys(keyTypes.map(() => ''));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Lookup failed');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      {/* Input form */}
      <form onSubmit={handleSubmit} className="flex items-center gap-2 flex-wrap">
        {keyTypes.map((keyType, index) => (
          <div key={index} className="flex items-center gap-2">
            {index > 0 && (
              <span className="text-gray-400 text-xs font-mono">→</span>
            )}
            <div className="flex flex-col">
              <Input
                type="text"
                value={keys[index]}
                onChange={(e) => handleKeyChange(index, e.target.value)}
                placeholder={getKeyTypeHint(keyType.type)}
                className="w-64 h-7 text-xs font-mono"
                disabled={isLoading}
              />
              {keyTypes.length > 1 && (
                <span className="text-[10px] text-gray-400 mt-0.5">
                  {keyType.label}
                </span>
              )}
            </div>
          </div>
        ))}
        <Button
          type="submit"
          variant="secondary"
          size="sm"
          className="h-7 text-xs"
          disabled={isLoading || keys.some((k) => !k.trim())}
        >
          {isLoading ? 'Loading...' : 'Lookup'}
        </Button>
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
                <th className="text-left py-1.5 px-1 text-gray-500 font-medium">
                  Key{keyTypes.length > 1 ? 's' : ''}
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
                  lookup.decodedValue === '0';

                return (
                  <tr key={idx} className="border-b border-gray-100">
                    <td className="py-1.5 px-1">
                      <span className="font-mono text-gray-700">
                        {lookup.keys?.join(' → ')}
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
                        display={formatDecodedValue(lookup.decodedValue)}
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
