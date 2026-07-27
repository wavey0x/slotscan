'use client';

import { useState } from 'react';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import {
  StorageQueryLookup,
  StorageViewResponse,
  StorageViewType,
} from '@/lib/types';
import { queryStorage } from '@/lib/api';
import { LookupResultsTable } from './LookupResultsTable';

interface ArrayIndexInputProps {
  declarationId: string;
  arrayLength: string | null;
  chainId: string;
  address: string;
  blockRef: StorageViewResponse['block_ref'];
  layoutId: string;
  resultType?: StorageViewType;
  lookups: StorageQueryLookup[];
  onLookup: (lookup: StorageQueryLookup) => void;
}

export function ArrayIndexInput({
  declarationId,
  arrayLength,
  chainId,
  address,
  blockRef,
  layoutId,
  resultType,
  lookups,
  onLookup,
}: ArrayIndexInputProps) {
  const [indexInput, setIndexInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!/^(?:0x[0-9a-fA-F]+|\d+)$/.test(indexInput)) {
      setError('Enter a non-negative decimal or hexadecimal index');
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const result = await queryStorage({
        chain_id: chainId,
        address,
        block_ref: blockRef,
        layout_id: layoutId,
        access: {
          declaration_id: declarationId,
          steps: [{ kind: 'array_index', value: indexInput }],
        },
      });
      onLookup({
        index: indexInput,
        slot: result.location.slot,
        rawValue: result.value_encoded,
        decodedValue: result.value_decoded,
        storage: result.storage,
      });
      setIndexInput('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Lookup failed');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <form onSubmit={handleSubmit} className="flex items-center gap-2">
        <Input
          type="text"
          inputMode="numeric"
          value={indexInput}
          onChange={(event) => {
            setIndexInput(event.target.value);
            setError(null);
          }}
          aria-label="Array index"
          placeholder={arrayLength ? `Enter index (length ${arrayLength})` : 'Enter array index'}
          className="h-7 w-52 font-mono text-xs"
          disabled={isLoading}
        />
        <Button
          type="submit"
          variant="secondary"
          size="sm"
          className="h-7 text-xs"
          disabled={isLoading || !indexInput}
        >
          {isLoading ? 'Loading…' : 'Lookup'}
        </Button>
      </form>

      {error && <p className="text-xs text-red">{error}</p>}

      <LookupResultsTable
        lookups={lookups}
        chainId={chainId}
        keyLabel="Index"
        resultType={resultType}
        renderKey={(lookup) => `[${lookup.index}]`}
      />
    </div>
  );
}
