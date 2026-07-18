import { Fragment } from 'react';
import { StorageQueryLookup, StorageViewType } from '@/lib/types';
import { cn, formatDecodedValue, truncateSlot } from '@/lib/utils';
import { CopyButton } from '@/components/ui/CopyButton';
import { HoverCell } from '@/components/ui/HoverCell';
import { DataTable, dataTableCellClass, dataTableHeadCellClass } from '@/components/ui/DataTable';

function lookupValue(lookup: StorageQueryLookup): string {
  if (lookup.decodedValue !== null && lookup.decodedValue !== undefined) {
    return formatDecodedValue(lookup.decodedValue, { fullAddresses: true });
  }
  if (lookup.rawValue === `0x${'0'.repeat(64)}`) return '0';
  try {
    return BigInt(lookup.rawValue).toString();
  } catch {
    return lookup.rawValue || '—';
  }
}

function lookupIsZero(lookup: StorageQueryLookup): boolean {
  const decoded = lookup.decodedValue;
  return lookup.rawValue === `0x${'0'.repeat(64)}`
    || decoded === 0
    || decoded === '0'
    || decoded === '0x0000000000000000000000000000000000000000';
}

function decodedRecord(value: unknown): Record<string, unknown> | null {
  if (
    typeof value !== 'object'
    || value === null
    || Array.isArray(value)
    || Object.keys(value).length === 0
  ) {
    return null;
  }
  return value as Record<string, unknown>;
}

function ScalarLookupValue({
  lookup,
  chainId,
}: {
  lookup: StorageQueryLookup;
  chainId: string;
}) {
  return (
    <HoverCell
      display={lookupValue(lookup)}
      value={lookup.rawValue}
      chainId={chainId}
      colorClass={cn(
        'font-mono',
        lookupIsZero(lookup) ? 'text-gray-300' : 'text-gray-900',
      )}
    />
  );
}

function absoluteMemberSlot(baseSlot: string, relativeSlot: string): string {
  try {
    return `0x${(BigInt(baseSlot) + BigInt(relativeSlot)).toString(16)}`;
  } catch {
    return baseSlot;
  }
}

function slotLocation(slot: string, byteOffset: number): string {
  return byteOffset > 0 ? `${slot} +${byteOffset}B` : slot;
}

export function LookupResultsTable({
  lookups,
  chainId,
  keyLabel,
  renderKey,
  resultType,
}: {
  lookups: StorageQueryLookup[];
  chainId: string;
  keyLabel: string;
  renderKey: (lookup: StorageQueryLookup) => React.ReactNode;
  resultType?: StorageViewType;
}) {
  if (lookups.length === 0) return null;

  const hasStructuredResult = lookups.some((lookup) => decodedRecord(lookup.decodedValue));
  const accessLabel = hasStructuredResult ? `${keyLabel} / Member` : keyLabel;

  return (
    <div className="mt-4">
      <div className="mb-2 text-[10px] font-medium uppercase tracking-wide text-gray-500">Lookup history</div>
      <DataTable minWidth="50rem" className="text-xs">
        <thead>
          <tr className="border-b border-gray-300">
            <th className={cn(dataTableHeadCellClass, 'w-[30%]')}>{accessLabel}</th>
            <th className={cn(dataTableHeadCellClass, 'hidden w-[22%] sm:table-cell')}>Type</th>
            <th className={cn(dataTableHeadCellClass, 'hidden w-[18%] sm:table-cell')}>Slot</th>
            <th className={dataTableHeadCellClass}>Result</th>
            <th className={cn(dataTableHeadCellClass, 'w-10 sm:hidden')}>Slot</th>
          </tr>
        </thead>
        <tbody>
          {lookups.map((lookup, lookupIndex) => {
            const fields = decodedRecord(lookup.decodedValue);
            if (!fields) {
              return (
                <tr key={`${lookup.slot}:${lookupIndex}`} className="border-b border-gray-200">
                  <td className={`${dataTableCellClass} font-mono text-gray-700`}>{renderKey(lookup)}</td>
                  <td className={`${dataTableCellClass} hidden font-mono text-gray-500 sm:table-cell`}>
                    {resultType?.label ?? '—'}
                  </td>
                  <td className={`${dataTableCellClass} hidden sm:table-cell`}>
                    <HoverCell display={truncateSlot(lookup.slot)} value={lookup.slot} colorClass="font-mono text-gray-500" />
                  </td>
                  <td className={dataTableCellClass}>
                    <ScalarLookupValue lookup={lookup} chainId={chainId} />
                  </td>
                  <td className={`${dataTableCellClass} truncate font-mono text-[10px] text-gray-500 sm:hidden`}>
                    {truncateSlot(lookup.slot)}
                  </td>
                </tr>
              );
            }

            const entries = Object.entries(fields);
            return (
              <Fragment key={`${lookup.slot}:${lookupIndex}`}>
                <tr className="bg-gray-50/50">
                  <td className={`${dataTableCellClass} relative font-mono text-gray-700`}>
                    {entries.length > 0 && (
                      <span
                        aria-hidden="true"
                        className="absolute bottom-0 left-3 top-1/2 border-l border-gray-300"
                      />
                    )}
                    {renderKey(lookup)}
                  </td>
                  <td className={`${dataTableCellClass} hidden font-mono text-gray-500 sm:table-cell`}>
                    {resultType?.label ?? 'decoded record'}
                  </td>
                  <td className={`${dataTableCellClass} hidden sm:table-cell`}>
                    <HoverCell display={truncateSlot(lookup.slot)} value={lookup.slot} colorClass="font-mono text-gray-500" />
                  </td>
                  <td className={dataTableCellClass}>
                    <span className="inline-flex items-center gap-1 font-mono text-[10px] text-gray-400">
                      {entries.length} {entries.length === 1 ? 'field' : 'fields'}
                      <CopyButton
                        value={lookup.rawValue}
                        label="Copy raw storage value"
                        className="-my-1"
                      />
                    </span>
                  </td>
                  <td className={`${dataTableCellClass} truncate font-mono text-[10px] text-gray-500 sm:hidden`}>
                    {truncateSlot(lookup.slot)}
                  </td>
                </tr>
                {entries.map(([name, value], fieldIndex) => {
                  const member = resultType?.members.find((candidate) => candidate.name === name);
                  const memberSlot = member
                    ? absoluteMemberSlot(lookup.slot, member.slot)
                    : lookup.slot;
                  const location = slotLocation(memberSlot, member?.byte_offset ?? 0);
                  const display = formatDecodedValue(value);
                  return (
                    <tr
                      key={`${lookup.slot}:${lookupIndex}:${name}`}
                      className={cn(
                        'bg-gray-50/50 hover:bg-gray-100/50',
                        fieldIndex === entries.length - 1 && 'border-b border-gray-200',
                      )}
                    >
                      <td className={`${dataTableCellClass} relative py-1.5 pl-7 font-mono text-gray-700`}>
                        <span
                          aria-hidden="true"
                          className={cn(
                            'absolute left-3 top-0 border-l border-gray-300',
                            fieldIndex === entries.length - 1 ? 'bottom-1/2' : 'bottom-0',
                          )}
                        />
                        <span
                          aria-hidden="true"
                          className="absolute left-3 top-1/2 w-3 border-t border-gray-300"
                        />
                        <span className="block truncate" title={name}>{name}</span>
                      </td>
                      <td className={`${dataTableCellClass} hidden py-1.5 font-mono text-gray-500 sm:table-cell`}>
                        {member?.label ?? 'unknown'}
                      </td>
                      <td className={`${dataTableCellClass} hidden py-1.5 sm:table-cell`}>
                        <HoverCell display={location} value={location} colorClass="font-mono text-gray-500" />
                      </td>
                      <td className={`${dataTableCellClass} py-1.5`}>
                        <HoverCell
                          display={display}
                          value={String(value ?? '')}
                          chainId={chainId}
                          copyLabel={`Copy ${name} value`}
                          colorClass="font-mono text-gray-900"
                        />
                      </td>
                      <td className={`${dataTableCellClass} truncate py-1.5 font-mono text-[10px] text-gray-500 sm:hidden`}>
                        {location}
                      </td>
                    </tr>
                  );
                })}
              </Fragment>
            );
          })}
        </tbody>
      </DataTable>
    </div>
  );
}
