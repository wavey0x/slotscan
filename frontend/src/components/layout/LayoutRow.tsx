'use client';

import { memo, useState } from 'react';
import {
  StorageVariableResponse,
  StorageTypeResponse,
  SlotValueResponse,
  ComputedSlotLookup,
} from '@/lib/types';
import { HoverCell } from '@/components/ui/HoverCell';
import { CopyButton } from '@/components/ui/CopyButton';
import { DetailPopover } from '@/components/ui/DetailPopover';
import { MappingKeyInput } from './MappingKeyInput';
import { ArrayIndexInput } from './ArrayIndexInput';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn, formatDecodedValue } from '@/lib/utils';

interface LayoutRowProps {
  variable: StorageVariableResponse;
  types: Record<string, StorageTypeResponse>;
  chainId: string;
  address: string;
  showHex: boolean;
  slotValue?: SlotValueResponse;
  storageLoading?: boolean;
}

function truncateType(label: string, maxLen: number = 40): string {
  if (label.length <= maxLen) return label;
  return label.substring(0, maxLen - 3) + '...';
}

// Format hex value for display (show full value)
function formatHexValue(hex: string): string {
  if (!hex) return '-';
  return hex;
}

export const LayoutRow = memo(function LayoutRow({
  variable,
  types,
  chainId,
  address,
  showHex,
  slotValue,
  storageLoading,
}: LayoutRowProps) {
  const [expanded, setExpanded] = useState(false);
  const [lookups, setLookups] = useState<ComputedSlotLookup[]>([]);

  const varType = types[variable.type_id];

  // Detect type categories
  const isMapping = varType?.kind === 'mapping' ||
    varType?.key_type !== null ||
    variable.type_label.startsWith('mapping(') ||
    variable.type_label.includes('=>');

  const isDynamicArray = varType?.encoding === 'dynamic_array' ||
    (varType?.kind === 'array' && varType?.array_length === null);

  // Static array: has array_length OR type label matches pattern like address[32]
  const staticArrayMatch = variable.type_label.match(/\[(\d+)\]$/);
  const isStaticArray = !isDynamicArray && (
    (varType?.kind === 'array' && varType?.array_length !== null) ||
    staticArrayMatch !== null
  );

  const staticArrayLength = varType?.array_length ||
    (staticArrayMatch ? parseInt(staticArrayMatch[1], 10) : undefined);

  const isArray = isDynamicArray || isStaticArray;
  const isInteractive = isMapping || isArray;

  // Handle new lookup result
  const handleLookup = (lookup: ComputedSlotLookup) => {
    setLookups((prev) => [...prev, lookup]);
  };

  // Get key types for nested mappings
  const getMappingKeyTypes = (): { type: string; label: string }[] => {
    const keyTypes: { type: string; label: string }[] = [];
    let currentType = varType;

    while (currentType?.kind === 'mapping' && currentType.key_type) {
      keyTypes.push({
        type: currentType.key_type,
        label: getKeyTypeLabel(currentType.key_type),
      });

      if (currentType.value_type) {
        currentType = types[currentType.value_type];
      } else {
        break;
      }
    }

    // Fallback: parse from type label if no key types found
    if (keyTypes.length === 0 && variable.type_label.includes('mapping(')) {
      const match = variable.type_label.match(/mapping\((\w+)/);
      if (match) {
        keyTypes.push({
          type: match[1],
          label: match[1],
        });
      }
    }

    return keyTypes;
  };

  // Get human-readable key type label
  const getKeyTypeLabel = (keyType: string): string => {
    const lower = keyType.toLowerCase();
    if (lower.includes('address')) return 'address';
    if (lower.includes('uint256')) return 'uint256';
    if (lower.includes('uint')) return 'uint';
    if (lower.includes('bytes32')) return 'bytes32';
    if (lower.includes('bytes')) return 'bytes';
    return 'key';
  };

  // Get the final value type for nested mappings
  const getFinalValueType = (): StorageTypeResponse | undefined => {
    let currentType = varType;
    while (currentType?.kind === 'mapping' && currentType.value_type) {
      const nextType = types[currentType.value_type];
      if (nextType?.kind !== 'mapping') {
        return nextType;
      }
      currentType = nextType;
    }
    return currentType;
  };

  // Get element type for arrays
  const getElementType = (): StorageTypeResponse | undefined => {
    if (varType?.element_type) {
      return types[varType.element_type];
    }
    return undefined;
  };

  return (
    <>
      {/* Main row */}
      <tr
        className={cn(
          'hover:bg-gray-50/50 border-b border-gray-100',
          expanded && 'bg-gray-50/30'
        )}
      >
        {/* Expand button */}
        <td className="px-1 py-2 text-center">
          {isInteractive && (
            <button
              onClick={() => setExpanded(!expanded)}
              aria-label={expanded ? `Collapse ${variable.name}` : `Expand ${variable.name}`}
              aria-expanded={expanded}
              className="touch-hitbox w-4 h-4 text-xs text-gray-400 hover:text-gray-700 font-mono"
            >
              {expanded ? '−' : '+'}
            </button>
          )}
        </td>

        {/* Name */}
        <td className="px-1 py-2 text-xs font-mono text-gray-900">
          <DetailPopover
            className="max-w-full"
            content={(
              <div className="space-y-1">
                <div className="text-[10px] font-medium uppercase tracking-wide text-gray-400">Slot</div>
                <div className="break-all font-mono text-xs text-gray-200">{variable.slot}</div>
              </div>
            )}
          >
            <span className="block truncate" title={variable.name}>{variable.name}</span>
          </DetailPopover>
        </td>

        {/* Type */}
        <td className="px-1 py-2 truncate text-xs font-mono text-gray-500" title={variable.type_label}>
          {variable.type_label}
        </td>

        {/* Slot */}
        <td data-testid="layout-slot" className="hidden break-all px-1 py-2 text-xs font-mono text-gray-500 sm:table-cell">
          {variable.slot}
        </td>

        {/* Value */}
        <td className="px-1 py-2">
          {storageLoading ? (
            <Skeleton className="h-3 w-20" />
          ) : slotValue ? (
            <div className="flex items-center gap-1">
              <span className={cn(
                'font-mono leading-tight break-all',
                showHex ? 'text-[10px]' : 'text-xs',
                isInteractive ? 'text-gray-400' : 'text-gray-900'
              )}>
                {showHex
                  ? slotValue.value_encoded
                  : formatDecodedValue(slotValue.value_decoded)}
              </span>
              <CopyButton
                label={`Copy ${variable.name} value`}
                value={
                  showHex
                    ? slotValue.value_encoded
                    : String(slotValue.value_decoded ?? slotValue.value_encoded)
                }
              />
            </div>
          ) : isInteractive ? (
            <span className="text-gray-400 text-[10px]">expand to query</span>
          ) : (
            <span className="text-gray-400 text-xs">-</span>
          )}
        </td>
      </tr>

      {/* Expanded input row for mappings */}
      {expanded && isMapping && (
        <tr className="bg-gray-50/50">
          <td colSpan={5} className="px-4 py-3 border-b border-gray-100">
            <MappingKeyInput
              baseSlot={variable.slot}
              keyTypes={getMappingKeyTypes()}
              valueType={getFinalValueType()}
              chainId={chainId}
              address={address}
              lookups={lookups}
              onLookup={handleLookup}
            />
          </td>
        </tr>
      )}

      {/* Expanded input row for arrays */}
      {expanded && isArray && !isMapping && (
        <tr className="bg-gray-50/50">
          <td colSpan={5} className="px-4 py-3 border-b border-gray-100">
            <ArrayIndexInput
              baseSlot={variable.slot}
              elementType={getElementType()}
              isDynamic={isDynamicArray}
              arrayLength={staticArrayLength}
              chainId={chainId}
              address={address}
              lookups={lookups}
              onLookup={handleLookup}
            />
          </td>
        </tr>
      )}
    </>
  );
});
