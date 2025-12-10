'use client';

import { useState } from 'react';
import {
  StorageVariableResponse,
  StorageTypeResponse,
  ComputedSlotLookup,
} from '@/lib/types';
import { HoverCell } from '@/components/ui/HoverCell';
import { MappingKeyInput } from './MappingKeyInput';
import { ArrayIndexInput } from './ArrayIndexInput';
import { cn } from '@/lib/utils';

interface LayoutRowProps {
  variable: StorageVariableResponse;
  types: Record<string, StorageTypeResponse>;
  chainId: string;
  address: string;
  showHex: boolean;
}

function truncateType(label: string, maxLen: number = 40): string {
  if (label.length <= maxLen) return label;
  return label.substring(0, maxLen - 3) + '...';
}

export function LayoutRow({
  variable,
  types,
  chainId,
  address,
  showHex,
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
              className="w-4 h-4 text-xs text-gray-400 hover:text-gray-700 font-mono"
            >
              {expanded ? '−' : '+'}
            </button>
          )}
        </td>

        {/* Name */}
        <td className="px-1 py-2 text-sm font-mono text-gray-900">
          {variable.name}
        </td>

        {/* Type */}
        <td className="px-1 py-2">
          <HoverCell
            display={truncateType(variable.type_label)}
            value={variable.type_label}
            colorClass="text-xs font-mono text-gray-500"
          />
        </td>

        {/* Slot */}
        <td className="px-1 py-2 text-xs font-mono text-gray-500">
          {variable.slot}
        </td>

        {/* Offset */}
        <td className="px-1 py-2 text-xs font-mono text-gray-500">
          {variable.offset}
        </td>

        {/* Bytes */}
        <td className="px-1 py-2 text-xs font-mono text-gray-500">
          {variable.size}
        </td>
      </tr>

      {/* Expanded input row for mappings */}
      {expanded && isMapping && (
        <tr className="bg-gray-50/50">
          <td colSpan={6} className="px-4 py-3 border-b border-gray-100">
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
          <td colSpan={6} className="px-4 py-3 border-b border-gray-100">
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
}
