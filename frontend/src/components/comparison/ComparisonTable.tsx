'use client';

import { useDeferredValue, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import {
  DataTable,
  dataTableCellClass,
  dataTableHeadCellClass,
} from '@/components/ui/DataTable';
import { Input } from '@/components/ui/Input';
import { HoverCell } from '@/components/ui/HoverCell';
import { ViewSwitch } from '@/components/ui/ViewSwitch';
import type {
  ComparisonEntry,
  ComparisonRegion,
  ComparisonSummary,
} from '@/lib/types';
import { formatStorageLocation } from '@/lib/storage-location';
import { cn } from '@/lib/utils';

type Filter = 'changes' | 'conflicts' | 'all';

function formattedRegion(region: ComparisonRegion) {
  return formatStorageLocation({
    slot: region.location.slot,
    endSlot: region.location.end_slot,
    byteOffset: region.location.byte_offset,
    byteSize: region.location.byte_size,
    isRoot: region.location.is_root,
  });
}

function formattedRoot(slot: string) {
  return formatStorageLocation({ slot });
}

function locationQualifier(region: ComparisonRegion): string | null {
  return formattedRegion(region).qualifier;
}

function sideLocation(region: ComparisonRegion): string {
  const { location } = region;
  const formatted = formattedRegion(region);
  if (location.is_root) return `root slot ${formatted.slot}`;
  if (location.slot !== location.end_slot) {
    return `slots ${formatted.slot}`;
  }
  if (location.byte_offset !== 0 || location.byte_size !== '32') {
    return `slot ${formatted.display}`;
  }
  return `slot ${formatted.slot}`;
}

function formatComparisonLocation(entry: ComparisonEntry): string {
  const from = entry.from_region;
  const to = entry.to_region;
  if (entry.kind === 'scope_root_changed' && from && to) {
    return `root ${formattedRoot(from.scope.root_slot).slot} → root ${formattedRoot(to.scope.root_slot).slot}`;
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
    const formattedFrom = formattedRegion(from);
    const formattedTo = formattedRegion(to);
    return `slot ${formattedFrom.slot} · ${formattedFrom.qualifier || 'full slot'} → ${formattedTo.qualifier || 'full slot'}`;
  }
  return `${sideLocation(from)} → ${sideLocation(to)}`;
}

function locationDisplay(entry: ComparisonEntry): {
  primary: string;
  secondary: string | null;
  full: string;
} {
  const from = entry.from_region;
  const to = entry.to_region;
  if (entry.kind === 'scope_root_changed' && from && to) {
    const fromRoot = formattedRoot(from.scope.root_slot);
    const toRoot = formattedRoot(to.scope.root_slot);
    return {
      primary: `${fromRoot.slot} → ${toRoot.slot}`,
      secondary: 'scope root',
      full: `${fromRoot.fullSlot} → ${toRoot.fullSlot}`,
    };
  }
  if (!from && to) {
    const formatted = formattedRegion(to);
    return {
      primary: `— → ${formatted.slot}`,
      secondary: locationQualifier(to),
      full: `— → ${formatted.fullSlot}`,
    };
  }
  if (from && !to) {
    const formatted = formattedRegion(from);
    return {
      primary: `${formatted.slot} → —`,
      secondary: locationQualifier(from),
      full: `${formatted.fullSlot} → —`,
    };
  }
  if (!from || !to) return { primary: '—', secondary: null, full: '—' };

  const formattedFrom = formattedRegion(from);
  const formattedTo = formattedRegion(to);

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
      primary: formattedFrom.slot,
      secondary: locationQualifier(from),
      full: formattedFrom.fullSlot,
    };
  }
  if (sameScope && sameSlot && sameEndSlot) {
    return {
      primary: formattedFrom.slot,
      secondary: `${formattedFrom.qualifier || 'full slot'} → ${formattedTo.qualifier || 'full slot'}`,
      full: formattedFrom.fullSlot,
    };
  }
  const fromQualifier = locationQualifier(from);
  const toQualifier = locationQualifier(to);
  return {
    primary: `${formattedFrom.slot} → ${formattedTo.slot}`,
    secondary: fromQualifier || toQualifier
      ? `${fromQualifier || 'full slot'} → ${toQualifier || 'full slot'}`
      : null,
    full: `${formattedFrom.fullSlot} → ${formattedTo.fullSlot}`,
  };
}

function searchable(entry: ComparisonEntry): string {
  const regions = [entry.from_region, entry.to_region].filter(
    (region): region is ComparisonRegion => Boolean(region),
  );
  return [
    entry.kind,
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

function regionMetadata(region: ComparisonRegion | null): string {
  if (!region) return '—';
  return `offset ${region.location.byte_offset} · ${region.location.byte_size} bytes`;
}

function rowTint(entry: ComparisonEntry): string | null {
  if (entry.kind === 'unchanged') return null;
  return entry.impact === 'conflict'
    ? 'bg-red/[0.04]'
    : 'bg-amber-500/[0.04]';
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
    <section className="mt-4" aria-label="Layout comparison rows">
      <div className="mb-2 flex min-w-0 flex-wrap items-center justify-between gap-2">
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
                  const tint = rowTint(entry);
                  return [
                    <tr
                      key={entry.id}
                      className={cn(
                        'border-b border-gray-200',
                        tint,
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
                            {entry.impact === 'none' && canExpand && (
                              <span className="sr-only">Storage layout change. </span>
                            )}
                            <HoverCell
                              display={location.primary}
                              value={location.full}
                              copyLabel="Copy storage location"
                              copyInDetail
                              colorClass="font-mono text-xs text-gray-900"
                            />
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
                      <tr
                        key={`${entry.id}:details`}
                        data-testid="comparison-details"
                        className={cn('border-b border-gray-300', tint)}
                      >
                        <td className="px-2 py-2" />
                        <td className="px-2 py-2 font-mono text-[10px] text-gray-500">
                          {regionMetadata(entry.from_region)}
                        </td>
                        <td className="px-2 py-2 font-mono text-[10px] text-gray-500">
                          {regionMetadata(entry.to_region)}
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
