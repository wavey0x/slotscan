'use client';

import { useState } from 'react';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import {
  StorageQueryLookup,
  StorageViewResponse,
} from '@/lib/types';
import { queryStorage } from '@/lib/api';
import { LookupResultsTable } from './LookupResultsTable';

interface MappingKeyInputProps {
  declarationId: string;
  keyTypes: { type: string; label: string }[];
  chainId: string;
  address: string;
  blockRef: StorageViewResponse['block_ref'];
  layoutId: string;
  lookups: StorageQueryLookup[];
  onLookup: (lookup: StorageQueryLookup) => void;
}

function keyHint(type: string): string {
  const normalized = type.toLowerCase();
  if (normalized.includes('address')) return '0x… address';
  if (normalized.includes('bool')) return 'true or false';
  if (normalized.includes('bytes')) return '0x… bytes';
  if (normalized.includes('int')) return 'integer';
  return 'mapping key';
}

function syntaxError(value: string, type: string): string | null {
  const normalized = type.toLowerCase();
  if (!value.trim()) return 'A value is required';
  if (normalized.includes('address') && !/^0x[0-9a-fA-F]{40}$/.test(value)) {
    return 'Enter a 20-byte hexadecimal address';
  }
  if (normalized.includes('bool') && !/^(true|false|0|1)$/i.test(value)) {
    return 'Enter true, false, 0, or 1';
  }
  if (
    (normalized.includes('uint') || normalized.includes('int'))
    && !/^-?(?:0x[0-9a-fA-F]+|\d+)$/.test(value)
  ) {
    return 'Enter a decimal or hexadecimal integer';
  }
  return null;
}

export function MappingKeyInput({
  declarationId,
  keyTypes,
  chainId,
  address,
  blockRef,
  layoutId,
  lookups,
  onLookup,
}: MappingKeyInputProps) {
  const [keys, setKeys] = useState<string[]>(keyTypes.map(() => ''));
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    for (let index = 0; index < keys.length; index += 1) {
      const validationError = syntaxError(keys[index], keyTypes[index].type);
      if (validationError) {
        setError(`Key ${index + 1}: ${validationError}`);
        return;
      }
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
          steps: keys.map((value) => ({ kind: 'mapping_key', value })),
        },
      });
      onLookup({
        keys: [...keys],
        slot: result.location.slot,
        rawValue: result.value_encoded,
        decodedValue: result.value_decoded,
      });
      setKeys(keyTypes.map(() => ''));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Lookup failed');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <form onSubmit={handleSubmit} className="flex flex-wrap items-center gap-2">
        {keyTypes.map((keyType, index) => (
          <div key={`${keyType.type}:${index}`} className="flex items-center gap-2">
            {index > 0 && <span className="font-mono text-xs text-gray-400">→</span>}
            <div className="flex flex-col">
              <Input
                type="text"
                value={keys[index]}
                onChange={(event) => {
                  const next = [...keys];
                  next[index] = event.target.value;
                  setKeys(next);
                  setError(null);
                }}
                placeholder={keyHint(keyType.type)}
                className="h-7 w-64 font-mono text-xs"
                disabled={isLoading}
              />
              {keyTypes.length > 1 && (
                <span className="mt-0.5 text-[10px] text-gray-400">{keyType.label}</span>
              )}
            </div>
          </div>
        ))}
        <Button
          type="submit"
          variant="secondary"
          size="sm"
          className="h-7 text-xs"
          disabled={isLoading || keys.length === 0 || keys.some((key) => !key.trim())}
        >
          {isLoading ? 'Loading…' : 'Lookup'}
        </Button>
      </form>

      {error && <p className="text-xs text-red">{error}</p>}

      <LookupResultsTable
        lookups={lookups}
        chainId={chainId}
        keyLabel={keyTypes.length > 1 ? 'Keys' : 'Key'}
        renderKey={(lookup) => (
          <span className="flex flex-col gap-0.5">
            {(lookup.keys ?? []).map((key, index) => (
              <span key={`${key}:${index}`}>[{key}]</span>
            ))}
          </span>
        )}
      />
    </div>
  );
}
