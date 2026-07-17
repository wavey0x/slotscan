'use client';

import { useDeferredValue, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import {
  DataTable,
  dataTableCellClass,
  dataTableHeadCellClass,
} from '@/components/ui/DataTable';
import { Input } from '@/components/ui/Input';
import { ViewSwitch } from '@/components/ui/ViewSwitch';
import type {
  ComparisonEntry,
  ComparisonRegion,
  ComparisonSummary,
} from '@/lib/types';
import { cn } from '@/lib/utils';

type Filter = 'changes' | 'conflicts' | 'all';

function compactSlot(value: string): string {
  const number = BigInt(value);
  if (number <= BigInt(999_999_999)) return number.toString();
  const normalized = `0x${number.toString(16)}`;
  return `${normalized.slice(0, 8)}…${normalized.slice(-6)}`;
}

function byteRange(region: ComparisonRegion): string {
  const start = region.location.byte_offset;
  const end = start + Number(region.location.byte_size) - 1;
  return `bytes ${start}–${end}`;
}

function slotIdentifier(region: ComparisonRegion): string {
  const { location } = region;
  if (location.slot !== location.end_slot) {
    return `${compactSlot(location.slot)}–${compactSlot(location.end_slot)}`;
  }
  return compactSlot(location.slot);
}

function locationQualifier(region: ComparisonRegion): string | null {
  if (region.location.is_root) return 'root';
  if (
    region.location.byte_offset !== 0
    || region.location.byte_size !== '32'
  ) {
    return byteRange(region);
  }
  return null;
}

function sideLocation(region: ComparisonRegion): string {
  const { location } = region;
  if (location.is_root) return `root slot ${compactSlot(location.slot)}`;
  if (location.slot !== location.end_slot) {
    return `slots ${compactSlot(location.slot)}–${compactSlot(location.end_slot)}`;
  }
  if (location.byte_offset !== 0 || location.byte_size !== '32') {
    return `slot ${compactSlot(location.slot)} · ${byteRange(region)}`;
  }
  return `slot ${compactSlot(location.slot)}`;
}

function formatComparisonLocation(entry: ComparisonEntry): string {
  const from = entry.from_region;
  const to = entry.to_region;
  if (entry.kind === 'scope_root_changed' && from && to) {
    return `root ${compactSlot(from.scope.root_slot)} → root ${compactSlot(to.scope.root_slot)}`;
  }
  if (!from && to) return `— → ${sideLocation(to)}`;
  if (from && !to) return `${sideLocation(from)} → —`;
  if (!from || !to) return '—';
  const sameScope = from.scope.root_slot === to.scope.root_slot;
  const sameSlot = from.location.slot === to.location.slot;
  if (
    sameScope
    && sameSlot
    && from.location.byte_offset === to.location.byte_offset
    && from.location.byte_size === to.location.byte_size
    && from.location.end_slot === to.location.end_slot
  ) {
    return sideLocation(from);
  }
  if (
    sameScope
    && sameSlot
    && from.location.end_slot === to.location.end_slot
  ) {
    return `slot ${compactSlot(from.location.slot)} · ${byteRange(from)} → ${byteRange(to)}`;
  }
  return `${sideLocation(from)} → ${sideLocation(to)}`;
}

function locationDisplay(entry: ComparisonEntry): {
  primary: string;
  secondary: string | null;
} {
  const from = entry.from_region;
  const to = entry.to_region;
  if (entry.kind === 'scope_root_changed' && from && to) {
    return {
      primary: `${compactSlot(from.scope.root_slot)} → ${compactSlot(to.scope.root_slot)}`,
      secondary: 'scope root',
    };
  }
  if (!from && to) {
    return {
      primary: `— → ${slotIdentifier(to)}`,
      secondary: locationQualifier(to),
    };
  }
  if (from && !to) {
    return {
      primary: `${slotIdentifier(from)} → —`,
      secondary: locationQualifier(from),
    };
  }
  if (!from || !to) return { primary: '—', secondary: null };

  const sameScope = from.scope.root_slot === to.scope.root_slot;
  const sameSlot = from.location.slot === to.location.slot;
  const sameEndSlot = from.location.end_slot === to.location.end_slot;
  if (
    sameScope
    && sameSlot
    && sameEndSlot
    && from.location.byte_offset === to.location.byte_offset
    && from.location.byte_size === to.location.byte_size
  ) {
    return {
      primary: slotIdentifier(from),
      secondary: locationQualifier(from),
    };
  }
  if (sameScope && sameSlot && sameEndSlot) {
    return {
      primary: slotIdentifier(from),
      secondary: `${byteRange(from)} → ${byteRange(to)}`,
    };
  }
  const fromQualifier = locationQualifier(from);
  const toQualifier = locationQualifier(to);
  return {
    primary: `${slotIdentifier(from)} → ${slotIdentifier(to)}`,
    secondary: fromQualifier || toQualifier
      ? `${fromQualifier || 'full slot'} → ${toQualifier || 'full slot'}`
      : null,
  };
}

function searchable(entry: ComparisonEntry): string {
  const regions = [entry.from_region, entry.to_region].filter(
    (region): region is ComparisonRegion => Boolean(region),
  );
  return [
    entry.kind,
    ...entry.details,
    ...regions.flatMap((region) => [
      region.path,
      region.type.label,
      region.scope.id,
      region.scope.formula,
      region.location.slot,
      region.location.end_slot,
    ]),
  ].filter(Boolean).join(' ').toLowerCase();
}

function scopeLabel(entry: ComparisonEntry): string {
  const scope = (entry.from_region || entry.to_region)!.scope;
  if (scope.kind === 'default') return 'Default storage';
  return scope.formula || scope.id;
}

function evidence(region: ComparisonRegion | null) {
  if (!region) return <span className="text-gray-400">—</span>;
  const size = BigInt(region.type.byte_size);
  return (
    <div className="min-w-0" title={`${region.path} · ${region.type.label}`}>
      <div className="break-words text-xs text-gray-900">{region.path}</div>
      <div className="mt-0.5 break-words text-[10px] text-gray-500">
        {region.type.label}
        {size > BigInt(32) && !region.location.is_root
          ? ` · ${size.toString()} bytes`
          : ''}
      </div>
    </div>
  );
}

function fullLocation(region: ComparisonRegion): string {
  const location = region.location;
  return [
    `scope ${region.scope.id}`,
    `slot ${location.slot}`,
    location.end_slot !== location.slot ? `through ${location.end_slot}` : null,
    `byte offset ${location.byte_offset}`,
    `${location.byte_size} bytes`,
  ].filter(Boolean).join(' · ');
}

export function ComparisonTable({
  entries,
  summary,
}: {
  entries: ComparisonEntry[];
  summary: ComparisonSummary;
}) {
  const [filter, setFilter] = useState<Filter>('all');
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const deferredSearch = useDeferredValue(search.trim().toLowerCase());
  const changedCount = summary.changes + summary.conflicts + summary.ambiguous;
  const allCount = changedCount + summary.unchanged;
  const visible = useMemo(() => entries.filter((entry) => {
    if (filter === 'changes' && entry.kind === 'unchanged') return false;
    if (filter === 'conflicts' && entry.impact !== 'conflict') return false;
    return !deferredSearch || searchable(entry).includes(deferredSearch);
  }), [deferredSearch, entries, filter]);
  const groups = useMemo(() => {
    const grouped = new Map<string, ComparisonEntry[]>();
    visible.forEach((entry) => {
      const label = scopeLabel(entry);
      grouped.set(label, [...(grouped.get(label) || []), entry]);
    });
    return grouped;
  }, [visible]);

  const toggle = (id: string) => {
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <section className="mt-6 border-t border-gray-300 pt-3" aria-label="Layout comparison rows">
      <div className="mb-3 flex min-w-0 flex-wrap items-center justify-end gap-2">
        <div aria-live="polite">
          <ViewSwitch
            label="Rows"
            showLabel={false}
            value={filter}
            options={[
              { value: 'all', label: `All ${allCount}` },
              { value: 'changes', label: `Changes ${changedCount}` },
              { value: 'conflicts', label: `Conflicts ${summary.conflicts}` },
            ]}
            onChange={setFilter}
          />
        </div>
        {entries.length >= 50 && (
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search"
            aria-label="Search comparison rows"
            className="h-7 min-w-0 basis-48 px-2 py-0 text-xs"
          />
        )}
      </div>

      {visible.length === 0 ? (
        <div className="border border-gray-300 p-6 text-center text-xs text-gray-500">
          {entries.length === 0
            ? 'Both exact layouts declare no persistent storage.'
            : 'No matching rows.'}
        </div>
      ) : (
        <DataTable minWidth="52rem">
          <thead>
            <tr>
              <th className={cn(dataTableHeadCellClass, 'w-[34%]')}>Location</th>
              <th className={cn(dataTableHeadCellClass, 'w-[33%]')}>From</th>
              <th className={cn(dataTableHeadCellClass, 'w-[33%]')}>To</th>
            </tr>
          </thead>
          <tbody>
            {Array.from(groups).flatMap(([scope, rows]) => [
              <tr key={`scope:${scope}`}>
                <th
                  colSpan={3}
                  scope="rowgroup"
                  className="border-y border-gray-300 bg-gray-50 px-2 py-1.5 text-left text-[10px] font-medium text-gray-500"
                >
                  {scope === 'Default storage' ? scope : `ERC-7201 · ${scope}`}
                </th>
              </tr>,
              ...rows.flatMap((entry) => {
                const expanded = open.has(entry.id);
                const canExpand = entry.kind !== 'unchanged';
                const location = locationDisplay(entry);
                return [
                  <tr
                    key={entry.id}
                    className={cn(
                      'border-b border-gray-200',
                      entry.impact === 'conflict' && 'shadow-[inset_2px_0_0_rgb(var(--color-red))]',
                    )}
                  >
                    <td className={cn(dataTableCellClass, 'text-xs')}>
                      <div className="flex items-start gap-1.5">
                        {canExpand ? (
                          <button
                            type="button"
                            onClick={() => toggle(entry.id)}
                            aria-expanded={expanded}
                            aria-label={`${expanded ? 'Collapse' : 'Expand'} details for ${formatComparisonLocation(entry)}`}
                            className="mt-0.5 shrink-0 text-gray-400 hover:text-gray-900"
                          >
                            {expanded
                              ? <ChevronDown aria-hidden="true" size={13} />
                              : <ChevronRight aria-hidden="true" size={13} />}
                          </button>
                        ) : (
                          <span aria-hidden="true" className="w-[13px] shrink-0" />
                        )}
                        <div className="min-w-0">
                          {entry.impact === 'conflict' && (
                            <span className="sr-only">Storage conflict. </span>
                          )}
                          {entry.impact === 'ambiguous' && (
                            <span className="sr-only">Indeterminate change. </span>
                          )}
                          <div className="break-words font-mono text-xs text-gray-900">
                            {location.primary}
                          </div>
                          {location.secondary && (
                            <div className="mt-0.5 break-words font-mono text-[9px] text-gray-400">
                              {location.secondary}
                            </div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className={dataTableCellClass}>{evidence(entry.from_region)}</td>
                    <td className={dataTableCellClass}>{evidence(entry.to_region)}</td>
                  </tr>,
                  expanded && canExpand ? (
                    <tr key={`${entry.id}:details`} className="border-b border-gray-300 bg-gray-50">
                      <td colSpan={3} className="px-7 py-3">
                        <ul className="space-y-1 text-xs text-gray-700">
                          {entry.details.map((detail) => (
                            <li key={detail}>• {detail}</li>
                          ))}
                        </ul>
                        <div className="mt-2 space-y-0.5 break-all text-[10px] text-gray-500">
                          {entry.from_region && (
                            <div>From · {fullLocation(entry.from_region)}</div>
                          )}
                          {entry.to_region && (
                            <div>To · {fullLocation(entry.to_region)}</div>
                          )}
                        </div>
                      </td>
                    </tr>
                  ) : null,
                ].filter(Boolean) as React.ReactElement[];
              }),
            ])}
          </tbody>
        </DataTable>
      )}
    </section>
  );
}
