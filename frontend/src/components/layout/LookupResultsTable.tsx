import { StorageQueryLookup } from '@/lib/types';
import { cn, formatDecodedValue, truncateSlot } from '@/lib/utils';
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

export function LookupResultsTable({
  lookups,
  chainId,
  keyLabel,
  renderKey,
}: {
  lookups: StorageQueryLookup[];
  chainId: string;
  keyLabel: string;
  renderKey: (lookup: StorageQueryLookup) => React.ReactNode;
}) {
  if (lookups.length === 0) return null;

  return (
    <div className="mt-4">
      <div className="mb-2 text-[10px] font-medium uppercase tracking-wide text-gray-500">Lookup history</div>
      <DataTable minWidth="44rem" className="text-xs">
        <colgroup><col className="w-[30%]" /><col className="w-[22%]" /><col /></colgroup>
        <thead><tr className="border-b border-gray-300"><th className={dataTableHeadCellClass}>{keyLabel}</th><th className={dataTableHeadCellClass}>Slot</th><th className={dataTableHeadCellClass}>Value</th></tr></thead>
        <tbody>
          {lookups.map((lookup, index) => (
            <tr key={`${lookup.slot}:${index}`} className="border-b border-gray-200">
              <td className={`${dataTableCellClass} font-mono text-gray-700`}>{renderKey(lookup)}</td>
              <td className={dataTableCellClass}><HoverCell display={truncateSlot(lookup.slot)} value={lookup.slot} colorClass="font-mono text-gray-500" /></td>
              <td className={dataTableCellClass}><HoverCell display={lookupValue(lookup)} value={lookup.rawValue} chainId={chainId} colorClass={cn('font-mono', lookupIsZero(lookup) ? 'text-gray-300' : 'text-gray-900')} /></td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </div>
  );
}
