import { StorageQueryLookup } from '@/lib/types';
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

function LookupValue({
  lookup,
  chainId,
}: {
  lookup: StorageQueryLookup;
  chainId: string;
}) {
  const fields = decodedRecord(lookup.decodedValue);
  if (!fields) {
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

  return (
    <div className="flex min-w-0 items-start gap-1">
      <div className="min-w-0 space-y-0.5">
        {Object.entries(fields).map(([name, value]) => {
          const display = formatDecodedValue(value);
          return (
            <div key={name} className="flex min-w-0 items-baseline gap-1 font-mono">
              <span className="shrink-0 text-gray-400">{name}</span>
              <span className="shrink-0 text-gray-400">=</span>
              <HoverCell
                display={display}
                value={String(value ?? '')}
                chainId={chainId}
                copyLabel={`Copy ${name} value`}
                colorClass="font-mono text-gray-900"
              />
            </div>
          );
        })}
      </div>
      <CopyButton
        value={lookup.rawValue}
        label="Copy raw storage value"
        className="-my-1 shrink-0"
      />
    </div>
  );
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
              <td className={dataTableCellClass}>
                <LookupValue lookup={lookup} chainId={chainId} />
              </td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </div>
  );
}
