import { Fragment } from 'react';
import {
  StorageAccessDescriptor,
  StorageQueryLookup,
  StorageQueryValueItem,
} from '@/lib/types';
import { cn } from '@/lib/utils';
import { formatStorageLocation } from '@/lib/storage-location';
import { CompactValue } from '@/components/ui/CompactValue';
import { HoverCell } from '@/components/ui/HoverCell';
import { StorageLocationCell } from '@/components/ui/StorageLocationCell';
import { storageKeyDisplay } from '@/components/diff/slotDisplay';
import {
  DataTable,
  dataTableCellClass,
  dataTableHeadCellClass,
} from '@/components/ui/DataTable';

function isZero(item: StorageQueryValueItem): boolean {
  return item.value_encoded === `0x${'0'.repeat(64)}`
    || item.value_decoded === 0
    || item.value_decoded === '0'
    || item.value_decoded === '0x0000000000000000000000000000000000000000';
}

function AccessPath({
  lookup,
  accessors,
  chainId,
}: {
  lookup: StorageQueryLookup;
  accessors: StorageAccessDescriptor[];
  chainId: string;
}) {
  return (
    <span className="flex flex-col gap-0.5">
      {lookup.inputs.map((value, index) => {
        const accessor = accessors[index];
        const display = accessor?.kind === 'mapping_key'
          ? storageKeyDisplay(value)?.display ?? value
          : value;
        return (
          <span key={`${index}:${value}`} className="flex min-w-0 items-center gap-1">
            {accessors.length > 1 && (
              <span className="shrink-0 text-gray-400">{accessor?.name}</span>
            )}
            <span className="inline-flex min-w-0 items-center">
              [
              {accessor?.kind === 'mapping_key' ? (
                <HoverCell
                  display={display}
                  value={value}
                  chainId={chainId}
                  copyLabel={`Copy ${accessor.name}`}
                  colorClass="font-mono text-gray-700"
                />
              ) : (
                <span>{display}</span>
              )}
              ]
            </span>
          </span>
        );
      })}
    </span>
  );
}

function ValueCell({
  item,
  chainId,
}: {
  item: StorageQueryValueItem;
  chainId: string;
}) {
  let fallback: string | undefined;
  if (item.value_decoded === null || item.value_decoded === undefined) {
    try {
      fallback = BigInt(item.value_encoded).toString();
    } catch {
      fallback = undefined;
    }
  }
  return (
    <CompactValue
      decoded={item.value_decoded ?? fallback}
      encoded={item.value_encoded}
      missing="—"
      chainId={chainId}
      copyLabel={`Copy ${item.path} value`}
      colorClass={cn(
        'font-mono',
        isZero(item) ? 'text-gray-300' : 'text-gray-900',
      )}
    />
  );
}

function LocationCell({
  item,
  compact = false,
}: {
  item: StorageQueryValueItem;
  compact?: boolean;
}) {
  const location = formatStorageLocation({
    slot: item.location.slot,
    byteOffset: item.location.byte_offset,
    byteSize: item.location.byte_size,
  });
  return (
    <StorageLocationCell
      location={location}
      provenance={item.storage}
      colorClass={`font-mono ${compact ? 'text-[10px]' : 'text-gray-500'}`}
    />
  );
}

export function LookupResultsTable({
  lookups,
  accessors,
  chainId,
}: {
  lookups: StorageQueryLookup[];
  accessors: StorageAccessDescriptor[];
  chainId: string;
}) {
  if (lookups.length === 0) return null;

  const hasStructuredResult = lookups.some(
    (lookup) => lookup.items.length > 1 || lookup.items[0]?.relative_path,
  );

  return (
    <div className="mt-4">
      <div className="mb-2 text-[10px] font-medium uppercase tracking-wide text-gray-500">
        Lookup history
      </div>
      <DataTable minWidth="50rem" className="text-xs">
        <thead>
          <tr className="border-b border-gray-300">
            <th className={cn(dataTableHeadCellClass, 'w-[30%]')}>
              {hasStructuredResult ? 'Access / Field' : 'Access'}
            </th>
            <th className={cn(dataTableHeadCellClass, 'hidden w-[22%] sm:table-cell')}>
              Type
            </th>
            <th className={cn(dataTableHeadCellClass, 'hidden w-[18%] sm:table-cell')}>
              Slot
            </th>
            <th className={dataTableHeadCellClass}>Result</th>
            <th className={cn(dataTableHeadCellClass, 'w-10 sm:hidden')}>Slot</th>
          </tr>
        </thead>
        <tbody>
          {lookups.map((lookup, lookupIndex) => {
            const structured = lookup.items.length > 1
              || Boolean(lookup.items[0]?.relative_path);
            const rootLocation = formatStorageLocation({
              slot: lookup.location.slot,
              byteOffset: lookup.location.byte_offset,
              byteSize: lookup.location.byte_size,
            });

            if (!structured && lookup.items[0]) {
              const item = lookup.items[0];
              return (
                <tr key={`${lookup.path}:${lookupIndex}`} className="border-b border-gray-200">
                  <td className={`${dataTableCellClass} font-mono text-gray-700`}>
                    <AccessPath lookup={lookup} accessors={accessors} chainId={chainId} />
                  </td>
                  <td className={`${dataTableCellClass} hidden font-mono text-gray-500 sm:table-cell`}>
                    {item.type_label}
                  </td>
                  <td className={`${dataTableCellClass} hidden sm:table-cell`}>
                    <LocationCell item={item} />
                  </td>
                  <td className={dataTableCellClass}>
                    <ValueCell item={item} chainId={chainId} />
                  </td>
                  <td className={`${dataTableCellClass} truncate sm:hidden`}>
                    <LocationCell item={item} compact />
                  </td>
                </tr>
              );
            }

            return (
              <Fragment key={`${lookup.path}:${lookupIndex}`}>
                <tr className="bg-gray-50/50">
                  <td className={`${dataTableCellClass} relative font-mono text-gray-700`}>
                    {lookup.items.length > 0 && (
                      <span
                        aria-hidden="true"
                        className="absolute bottom-0 left-3 top-1/2 border-l border-gray-300"
                      />
                    )}
                    <AccessPath lookup={lookup} accessors={accessors} chainId={chainId} />
                  </td>
                  <td className={`${dataTableCellClass} hidden font-mono text-gray-500 sm:table-cell`}>
                    {lookup.type_label}
                  </td>
                  <td className={`${dataTableCellClass} hidden sm:table-cell`}>
                    <StorageLocationCell
                      location={rootLocation}
                      provenance={lookup.storage}
                      colorClass="font-mono text-gray-500"
                    />
                  </td>
                  <td className={dataTableCellClass}>
                    <span className="font-mono text-[10px] text-gray-400">
                      {lookup.items.length} {lookup.items.length === 1 ? 'field' : 'fields'}
                    </span>
                  </td>
                  <td className={`${dataTableCellClass} truncate sm:hidden`}>
                    <StorageLocationCell
                      location={rootLocation}
                      provenance={lookup.storage}
                      colorClass="font-mono text-[10px] text-gray-500"
                    />
                  </td>
                </tr>
                {lookup.items.map((item, fieldIndex) => (
                  <tr
                    key={`${lookup.path}:${lookupIndex}:${item.path}`}
                    className={cn(
                      'bg-gray-50/50 hover:bg-gray-100/50',
                      fieldIndex === lookup.items.length - 1
                        && 'border-b border-gray-200',
                    )}
                  >
                    <td className={`${dataTableCellClass} relative py-1.5 pl-7 font-mono text-gray-700`}>
                      <span
                        aria-hidden="true"
                        className={cn(
                          'absolute left-3 top-0 border-l border-gray-300',
                          fieldIndex === lookup.items.length - 1
                            ? 'bottom-1/2'
                            : 'bottom-0',
                        )}
                      />
                      <span
                        aria-hidden="true"
                        className="absolute left-3 top-1/2 w-3 border-t border-gray-300"
                      />
                      <span className="block truncate" title={item.relative_path}>
                        {item.relative_path}
                      </span>
                    </td>
                    <td className={`${dataTableCellClass} hidden py-1.5 font-mono text-gray-500 sm:table-cell`}>
                      {item.type_label}
                    </td>
                    <td className={`${dataTableCellClass} hidden py-1.5 sm:table-cell`}>
                      <LocationCell item={item} />
                    </td>
                    <td className={`${dataTableCellClass} py-1.5`}>
                      <ValueCell item={item} chainId={chainId} />
                    </td>
                    <td className={`${dataTableCellClass} truncate py-1.5 sm:hidden`}>
                      <LocationCell item={item} compact />
                    </td>
                  </tr>
                ))}
              </Fragment>
            );
          })}
        </tbody>
      </DataTable>
    </div>
  );
}
