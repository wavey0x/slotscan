'use client';

import { memo, useState } from 'react';
import {
  StorageAccessDescriptor,
  StorageViewResponse,
  StorageViewType,
  StorageViewValueItem,
  StorageViewVariable,
} from '@/lib/types';
import { DetailPopover } from '@/components/ui/DetailPopover';
import { StorageLocationCell } from '@/components/ui/StorageLocationCell';
import { formatStorageLocation } from '@/lib/storage-location';
import { StorageAccessInput } from './StorageAccessInput';
import { StorageViewValueCell } from './StorageViewValueCell';
import { cn } from '@/lib/utils';

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

function storageAccessors(
  rootType: StorageViewType | undefined,
  types: Record<string, StorageViewType>,
): StorageAccessDescriptor[] {
  const accessors: StorageAccessDescriptor[] = [];
  const visited = new Set<string>();
  let current = rootType;

  while (current && (current.encoding === 'mapping' || current.kind === 'array')) {
    if (visited.has(current.id)) return [];
    visited.add(current.id);

    if (current.encoding === 'mapping') {
      if (!current.key_type || !current.value_type) return [];
      const keyType = types[current.key_type];
      const type = keyType?.label ?? current.key_type;
      accessors.push({
        kind: 'mapping_key',
        type,
        label: keyTypeLabel(type),
        name: 'Key',
        arrayLength: null,
      });
      current = types[current.value_type];
      continue;
    }

    if (!current.element_type) return [];
    accessors.push({
      kind: 'array_index',
      type: 'uint256',
      label: 'index',
      name: 'Index',
      arrayLength: current.array_length,
    });
    current = types[current.element_type];
  }

  for (const kind of ['mapping_key', 'array_index'] as const) {
    const matches = accessors.filter((accessor) => accessor.kind === kind);
    if (matches.length > 1) {
      let ordinal = 0;
      for (const accessor of accessors) {
        if (accessor.kind === kind) {
          ordinal += 1;
          accessor.name = `${accessor.name} ${ordinal}`;
        }
      }
    }
  }
  return accessors;
}

function resolveStructField(
  rootType: StorageViewType,
  relativePath: string,
  types: Record<string, StorageViewType>,
): { typeLabel: string; byteSize: string | null } {
  let currentType: StorageViewType | undefined = rootType;
  let label = 'unknown';
  let byteSize: string | null = null;

  for (const segment of relativePath.split('.')) {
    const member: StorageViewType['members'][number] | undefined = currentType?.members.find(
      (candidate) => candidate.name === segment,
    );
    if (!member) return { typeLabel: label, byteSize };
    label = member.label;
    byteSize = member.byte_size;
    currentType = types[member.type_id];
  }

  return {
    typeLabel: currentType?.label ?? label,
    byteSize: currentType?.num_bytes ?? byteSize,
  };
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
  const varType = types[variable.type_id];
  const accessors = storageAccessors(varType, types);
  const status = values[0]?.status;
  const isInteractive = accessors.length > 0 && status === 'on_demand';
  const structValues = varType?.kind === 'struct'
    ? values.filter((value) => value.path !== variable.name)
    : [];
  const hasStructDetails = structValues.length > 0;
  const canExpand = isInteractive || hasStructDetails;
  const variableProvenance = values.find(
    (value) => value.path === variable.name,
  )?.storage;
  const variableLocation = formatStorageLocation({
    slot: variable.slot,
    byteOffset: variable.byte_offset,
    byteSize: variable.byte_size,
  });

  const successfulValues = values.filter(
    (value) => value.status === 'ok' && value.value_encoded
  );

  return (
    <>
      <tr
        className={cn(
          'hover:bg-gray-50/50',
          expanded ? 'bg-gray-50/50' : 'border-b border-gray-100'
        )}
      >
        <td className="relative px-0.5 py-2 align-top text-center sm:px-1">
          {expanded && hasStructDetails && (
            <span
              aria-hidden="true"
              className="absolute bottom-0 left-1/2 top-1/2 border-l border-gray-300"
            />
          )}
          {canExpand && (
            <button
              onClick={() => setExpanded(!expanded)}
              aria-label={expanded ? `Collapse ${variable.name}` : `Expand ${variable.name}`}
              aria-expanded={expanded}
              className="touch-hitbox mx-auto flex h-[18px] w-4 items-center justify-center font-mono text-xs leading-none text-gray-400 hover:text-gray-700"
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
                <div className="break-all font-mono text-xs text-gray-700">{variableLocation.full}</div>
              </div>
            )}
          >
            <span className="block truncate" title={variable.name}>{variable.name}</span>
          </DetailPopover>
        </td>

        <td className="px-1 py-2 font-mono text-xs text-gray-500">
          <DetailPopover
            className="max-w-full"
            dialogLabel={`Full type for ${variable.name}`}
            content={(
              <span className="block whitespace-normal font-mono text-xs text-gray-700 [overflow-wrap:anywhere]">
                {variable.type_label}
              </span>
            )}
          >
            <span className="block truncate">{variable.type_label}</span>
          </DetailPopover>
        </td>

        <td className="hidden truncate px-1 py-2 sm:table-cell">
          <StorageLocationCell
            location={variableLocation}
            provenance={variableProvenance}
            colorClass="font-mono text-xs text-gray-500"
          />
        </td>

        <td className="px-1 py-2">
          {hasStructDetails ? (
            <span className="font-mono text-[10px] text-gray-400">
              {structValues.length} {structValues.length === 1 ? 'field' : 'fields'}
            </span>
          ) : successfulValues.length > 0 ? (
            <div className="space-y-1">
              {successfulValues.map((value) => (
                <StorageViewValueCell
                  key={`${value.declaration_id}:${value.path}`}
                  value={value}
                  showHex={showHex}
                  chainId={chainId}
                />
              ))}
            </div>
          ) : status === 'on_demand' ? (
            !expanded && <span className="text-[10px] text-gray-400">expand to query</span>
          ) : status === 'deferred_budget' ? (
            <span className="text-[10px] text-gray-400">deferred by read limit</span>
          ) : (
            <span className="text-xs text-gray-400">—</span>
          )}
        </td>

        <td
          data-testid="layout-slot"
          className="truncate px-1 py-2 sm:hidden"
        >
          <StorageLocationCell
            location={variableLocation}
            provenance={variableProvenance}
            colorClass="font-mono text-[10px] text-gray-500"
          />
        </td>
      </tr>

      {expanded && hasStructDetails && structValues.map((value, index) => {
        const relativePath = value.path.startsWith(`${variable.name}.`)
          ? value.path.slice(variable.name.length + 1)
          : value.path;
        const field = resolveStructField(varType!, relativePath, types);
        const location = formatStorageLocation({
          slot: value.slot,
          byteOffset: value.byte_offset,
          byteSize: field.byteSize,
        });

        return (
          <tr
            key={`${value.declaration_id}:${value.path}`}
            className={cn(
              'bg-gray-50/50 hover:bg-gray-100/50',
              index === structValues.length - 1 && 'border-b border-gray-100',
            )}
          >
            <td className="relative px-0.5 py-1.5 sm:px-1">
              <span
                aria-hidden="true"
                className={cn(
                  'absolute left-1/2 top-0 border-l border-gray-300',
                  index === structValues.length - 1 ? 'bottom-1/2' : 'bottom-0',
                )}
              />
              <span
                aria-hidden="true"
                className="absolute left-1/2 top-1/2 w-[calc(50%+1rem)] border-t border-gray-300"
              />
            </td>
            <td className="py-1.5 pl-4 pr-1 font-mono text-xs text-gray-700">
              <DetailPopover
                className="max-w-full"
                dialogLabel={`Full path for ${value.path}`}
                content={(
                  <span className="block break-all font-mono text-xs text-gray-700">
                    {value.path}
                  </span>
                )}
              >
                <span className="block truncate" title={relativePath}>{relativePath}</span>
              </DetailPopover>
            </td>
            <td className="px-1 py-1.5 font-mono text-xs text-gray-500">
              <DetailPopover
                className="max-w-full"
                dialogLabel={`Full type for ${value.path}`}
                content={(
                  <span className="block whitespace-normal font-mono text-xs text-gray-700 [overflow-wrap:anywhere]">
                    {field.typeLabel}
                  </span>
                )}
              >
                <span className="block truncate">{field.typeLabel}</span>
              </DetailPopover>
            </td>
            <td className="hidden truncate px-1 py-1.5 sm:table-cell">
              <StorageLocationCell
                location={location}
                provenance={value.storage}
                colorClass="font-mono text-xs text-gray-500"
              />
            </td>
            <td className="px-1 py-1.5">
              <StorageViewValueCell
                value={value}
                showHex={showHex}
                chainId={chainId}
              />
            </td>
            <td
              data-testid="layout-slot"
              className="truncate px-1 py-1.5 sm:hidden"
            >
              <StorageLocationCell
                location={location}
                provenance={value.storage}
                colorClass="font-mono text-[10px] text-gray-500"
              />
            </td>
          </tr>
        );
      })}

      {expanded && isInteractive && (
        <tr className="bg-gray-50/50">
          <td colSpan={5} className="border-b border-gray-100 px-4 pb-2 pt-1">
            <StorageAccessInput
              declarationId={variable.declaration_id}
              accessors={accessors}
              chainId={chainId}
              address={address}
              blockRef={blockRef}
              layoutId={layoutId}
            />
          </td>
        </tr>
      )}
    </>
  );
});
