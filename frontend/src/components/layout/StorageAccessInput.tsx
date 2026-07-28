'use client';

import { useState } from 'react';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import {
  StorageAccessDescriptor,
  StorageQueryLookup,
  StorageViewResponse,
} from '@/lib/types';
import { queryStorage } from '@/lib/api';
import { LookupResultsTable } from './LookupResultsTable';

interface StorageAccessInputProps {
  declarationId: string;
  accessors: StorageAccessDescriptor[];
  chainId: string;
  address: string;
  blockRef: StorageViewResponse['block_ref'];
  layoutId: string;
}

function keyHint(type: string): string {
  const normalized = type.toLowerCase();
  if (normalized.includes('address')) return '0x… address';
  if (normalized.includes('bool')) return 'true or false';
  if (normalized.includes('bytes')) return '0x… bytes';
  if (normalized.includes('int')) return 'integer';
  return 'mapping key';
}

function inputHint(accessor: StorageAccessDescriptor): string {
  if (accessor.kind === 'array_index') {
    return accessor.arrayLength
      ? `Index (length ${accessor.arrayLength})`
      : 'Array index';
  }
  if (/^Key \d+$/.test(accessor.name)) return keyHint(accessor.type);
  return accessor.name;
}

function syntaxError(
  value: string,
  accessor: StorageAccessDescriptor,
): string | null {
  if (!value.trim()) return 'A value is required';
  if (accessor.kind === 'array_index') {
    return /^(?:0x[0-9a-fA-F]+|\d+)$/.test(value)
      ? null
      : 'Enter a non-negative decimal or hexadecimal index';
  }

  const normalized = accessor.type.toLowerCase();
  if (normalized.includes('address') && !/^0x[0-9a-fA-F]{40}$/.test(value)) {
    return 'Enter a 20-byte hexadecimal address';
  }
  if (normalized.includes('bool') && !/^(true|false|0|1)$/i.test(value)) {
    return 'Enter true, false, 0, or 1';
  }
  if (
    normalized.includes('uint')
    && !/^(?:0x[0-9a-fA-F]+|\d+)$/.test(value)
  ) {
    return 'Enter a non-negative decimal or hexadecimal integer';
  }
  if (
    normalized.includes('int')
    && !/^-?(?:0x[0-9a-fA-F]+|\d+)$/.test(value)
  ) {
    return 'Enter a decimal or hexadecimal integer';
  }
  return null;
}

export function StorageAccessInput({
  declarationId,
  accessors,
  chainId,
  address,
  blockRef,
  layoutId,
}: StorageAccessInputProps) {
  const [inputs, setInputs] = useState<string[]>(accessors.map(() => ''));
  const [lookup, setLookup] = useState<StorageQueryLookup | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    for (let index = 0; index < accessors.length; index += 1) {
      const validationError = syntaxError(inputs[index], accessors[index]);
      if (validationError) {
        setError(`${accessors[index].name}: ${validationError}`);
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
          steps: accessors.map((accessor, index) => ({
            kind: accessor.kind,
            value: inputs[index],
          })),
        },
      });
      setLookup({ ...result, inputs: [...inputs] });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Lookup failed');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <form onSubmit={handleSubmit} className="flex flex-wrap items-start gap-2">
        {accessors.map((accessor, index) => (
          <div
            key={`${accessor.kind}:${accessor.type}:${index}`}
            className="flex items-start gap-2"
          >
            {index > 0 && (
              <span className="mt-1.5 font-mono text-xs text-gray-400">→</span>
            )}
            <div className="flex flex-col">
              <Input
                type="text"
                inputMode={accessor.kind === 'array_index' ? 'numeric' : undefined}
                value={inputs[index]}
                onChange={(event) => {
                  const next = [...inputs];
                  next[index] = event.target.value;
                  setInputs(next);
                  setError(null);
                }}
                aria-label={accessor.name}
                placeholder={inputHint(accessor)}
                className="h-7 w-52 font-mono text-xs sm:w-56"
                disabled={isLoading}
              />
              {accessors.length > 1 && (
                <span className="mt-0.5 text-[10px] text-gray-400">
                  {accessor.name}
                  <span className="text-gray-300"> · {accessor.label}</span>
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
          disabled={
            isLoading
            || accessors.length === 0
            || inputs.some((value) => !value.trim())
          }
        >
          {isLoading ? 'Loading…' : 'Lookup'}
        </Button>
      </form>

      {error && <p className="text-xs text-red">{error}</p>}

      <LookupResultsTable
        lookup={lookup}
        accessors={accessors}
        chainId={chainId}
        onDismiss={() => setLookup(null)}
      />
    </div>
  );
}
