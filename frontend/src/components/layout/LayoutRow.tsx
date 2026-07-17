'use client';

import { memo, useState } from 'react';
import {
  StorageQueryLookup,
  StorageViewResponse,
  StorageViewType,
  StorageViewValueItem,
  StorageViewVariable,
} from '@/lib/types';
import { CopyButton } from '@/components/ui/CopyButton';
import { DetailPopover } from '@/components/ui/DetailPopover';
import { MappingKeyInput } from './MappingKeyInput';
import { ArrayIndexInput } from './ArrayIndexInput';
import { cn, formatDecodedValue } from '@/lib/utils';

interface LayoutRowProps {
  variable: StorageViewVariable;
  types: Record<string, StorageViewType>;
  chainId: string;
  address: string;
  blockRef: StorageViewResponse['block_ref'];
  layoutId: string;
  showHex: boolean;
  values: StorageViewValueItem[];
}

function keyTypeLabel(keyType: string): string {
  const lower = keyType.toLowerCase();
  if (lower.includes('address')) return 'address';
  if (lower.includes('uint')) return lower.match(/uint\d+/)?.[0] ?? 'uint';
  if (lower.includes('int')) return lower.match(/int\d+/)?.[0] ?? 'int';
  if (lower.includes('bytes')) return lower.match(/bytes\d+/)?.[0] ?? 'bytes';
  if (lower.includes('bool')) return 'bool';
  return 'key';
}

export const LayoutRow = memo(function LayoutRow({
  variable,
  types,
  chainId,
  address,
  blockRef,
  layoutId,
  showHex,
  values,
}: LayoutRowProps) {
  const [expanded, setExpanded] = useState(false);
  const [lookups, setLookups] = useState<StorageQueryLookup[]>([]);
  const varType = types[variable.type_id];
  const isMapping = varType?.encoding === 'mapping';
  const isDynamicArray = varType?.encoding === 'dynamic_array';
  const isStaticArray = varType?.kind === 'array' && varType.encoding === 'inplace';
  const isArray = isDynamicArray || isStaticArray;
  const isInteractive = isMapping || isArray;

  const mappingKeyTypes: { type: string; label: string }[] = [];
  let currentType: StorageViewType | undefined = varType;
  while (currentType?.encoding === 'mapping' && currentType.key_type) {
    mappingKeyTypes.push({
      type: currentType.key_type,
      label: keyTypeLabel(currentType.key_type),
    });
    currentType = currentType.value_type
      ? types[currentType.value_type]
      : undefined;
  }

  const elementType = varType?.element_type
    ? types[varType.element_type]
    : undefined;
  const successfulValues = values.filter(
    (value) => value.status === 'ok' && value.value_encoded
  );
  const status = values[0]?.status;

  return (
    <>
      <tr
        className={cn(
          'border-b border-gray-100 hover:bg-gray-50/50',
          expanded && 'bg-gray-50/30'
        )}
      >
        <td className="px-1 py-2 text-center">
          {isInteractive && (
            <button
              onClick={() => setExpanded(!expanded)}
              aria-label={expanded ? `Collapse ${variable.name}` : `Expand ${variable.name}`}
              aria-expanded={expanded}
              className="touch-hitbox h-4 w-4 font-mono text-xs text-gray-400 hover:text-gray-700"
            >
              {expanded ? '−' : '+'}
            </button>
          )}
        </td>

        <td className="px-1 py-2 font-mono text-xs text-gray-900">
          <DetailPopover
            className="max-w-full"
            content={(
              <div className="space-y-1">
                <div className="text-[10px] font-medium uppercase tracking-wide text-gray-500">Slot</div>
                <div className="break-all font-mono text-xs text-gray-700">{variable.slot}</div>
              </div>
            )}
          >
            <span className="block truncate" title={variable.name}>{variable.name}</span>
          </DetailPopover>
        </td>

        <td className="truncate px-1 py-2 font-mono text-xs text-gray-500" title={variable.type_label}>
          {variable.type_label}
        </td>

        <td data-testid="layout-slot" className="hidden break-all px-1 py-2 font-mono text-xs text-gray-500 sm:table-cell">
          {variable.slot}
        </td>

        <td className="px-1 py-2">
          {successfulValues.length > 0 ? (
            <div className="space-y-1">
              {successfulValues.map((value) => {
                const rendered = showHex
                  ? value.value_encoded!
                  : formatDecodedValue(value.value_decoded);
                return (
                  <div key={`${value.declaration_id}:${value.path}`} className="flex min-w-0 items-center gap-1">
                    {value.path !== variable.name && (
                      <span className="shrink-0 font-mono text-[10px] text-gray-400">
                        {value.path}
                      </span>
                    )}
                    <span className={cn(
                      'break-all font-mono leading-tight text-gray-900',
                      showHex ? 'text-[10px]' : 'text-xs'
                    )}>
                      {rendered}
                    </span>
                    <CopyButton
                      label={`Copy ${value.path} value`}
                      value={showHex
                        ? value.value_encoded!
                        : String(value.value_decoded ?? value.value_encoded)}
                    />
                  </div>
                );
              })}
            </div>
          ) : status === 'on_demand' ? (
            <span className="text-[10px] text-gray-400">expand to query</span>
          ) : status === 'deferred_budget' ? (
            <span className="text-[10px] text-gray-400">deferred by read limit</span>
          ) : (
            <span className="text-xs text-gray-400">—</span>
          )}
        </td>
      </tr>

      {expanded && isMapping && (
        <tr className="bg-gray-50/50">
          <td colSpan={5} className="border-b border-gray-100 px-4 py-3">
            <MappingKeyInput
              declarationId={variable.declaration_id}
              keyTypes={mappingKeyTypes}
              chainId={chainId}
              address={address}
              blockRef={blockRef}
              layoutId={layoutId}
              lookups={lookups}
              onLookup={(lookup) => setLookups((previous) => [...previous, lookup])}
            />
          </td>
        </tr>
      )}

      {expanded && isArray && !isMapping && (
        <tr className="bg-gray-50/50">
          <td colSpan={5} className="border-b border-gray-100 px-4 py-3">
            <ArrayIndexInput
              declarationId={variable.declaration_id}
              elementLabel={elementType?.label}
              isDynamic={isDynamicArray}
              arrayLength={varType?.array_length ?? null}
              chainId={chainId}
              address={address}
              blockRef={blockRef}
              layoutId={layoutId}
              lookups={lookups}
              onLookup={(lookup) => setLookups((previous) => [...previous, lookup])}
            />
          </td>
        </tr>
      )}
    </>
  );
});
