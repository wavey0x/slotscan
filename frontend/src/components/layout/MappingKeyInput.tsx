'use client';

import { useState } from 'react';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import { StorageTypeResponse, ComputedSlotLookup } from '@/lib/types';
import { fetchSlotValue } from '@/lib/api';
import {
  computeMappingSlot,
  computeNestedMappingSlot,
  slotToHex,
  getKeyTypeHint,
  validateKey,
} from '@/lib/slot-utils';
import { LookupResultsTable } from './LookupResultsTable';

interface MappingKeyInputProps {
  baseSlot: number;
  keyTypes: { type: string; label: string }[];
  valueType?: StorageTypeResponse;
  chainId: string;
  address: string;
  lookups: ComputedSlotLookup[];
  onLookup: (lookup: ComputedSlotLookup) => void;
}

export function MappingKeyInput({
  baseSlot,
  keyTypes,
  valueType,
  chainId,
  address,
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

      // Fetch the value at latest block
      const result = await fetchSlotValue(chainId, address, slotHex, 'latest');

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

      <LookupResultsTable
        lookups={lookups}
        chainId={chainId}
        keyLabel={keyTypes.length > 1 ? 'Keys' : 'Key'}
        renderKey={(lookup) => (
          <span className="flex flex-col gap-0.5">
            {(lookup.keys ?? []).map((key, index) => <span key={`${key}:${index}`}>[{key}]</span>)}
          </span>
        )}
      />
    </div>
  );
}
