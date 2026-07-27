import {
  formatStorageLocation,
  type FormattedStorageLocation,
} from '@/lib/storage-location';
import type { StorageProvenance } from '@/lib/types';
import { CopyButton } from './CopyButton';
import { HoverCell } from './HoverCell';

const MAX_VISIBLE_SLOT_SEGMENTS = 12;

function slotCount(location: FormattedStorageLocation): number | null {
  if (!location.fullEndSlot) return null;

  try {
    const count = BigInt(location.fullEndSlot) - BigInt(location.fullStartSlot) + BigInt(1);
    if (count < BigInt(2) || count > BigInt(MAX_VISIBLE_SLOT_SEGMENTS)) return null;
    return Number(count);
  } catch {
    return null;
  }
}

function computedLocation(provenance: StorageProvenance): {
  display: string;
  full: string;
  segments: number | null;
} | null {
  if (!provenance.computed_slot) return null;

  let count: bigint | null = null;
  let endSlot: string | null = null;
  try {
    count = provenance.computed_slot_count
      ? BigInt(provenance.computed_slot_count)
      : null;
    if (count && count > BigInt(1)) {
      const start = BigInt(provenance.computed_slot);
      const end = start + count - BigInt(1);
      if (end < BigInt(2) ** BigInt(256)) {
        endSlot = provenance.computed_slot.startsWith('0x')
          ? `0x${end.toString(16)}`
          : end.toString();
      }
    }
  } catch {
    count = null;
  }
  const location = formatStorageLocation({
    slot: provenance.computed_slot,
    endSlot,
  });
  const segments = count
    && count >= BigInt(2)
    && count <= BigInt(MAX_VISIBLE_SLOT_SEGMENTS)
      ? Number(count)
      : null;
  return {
    display: location.slot,
    full: location.fullSlot,
    segments,
  };
}

function StorageProvenanceDetail({
  provenance,
}: {
  provenance: StorageProvenance;
}) {
  const base = formatStorageLocation({ slot: provenance.base_slot });
  const computed = computedLocation(provenance);

  return (
    <div data-testid="storage-provenance" className="space-y-1.5 font-mono">
      <div className="flex items-baseline gap-2 whitespace-nowrap">
        <span className="text-[9px] font-medium uppercase tracking-wide text-gray-400">
          {provenance.base_role}
        </span>
        <span className="text-[11px] tabular-nums text-gray-700">{base.startSlot}</span>
      </div>
      {computed && provenance.computed_role && (
        <div className="space-y-1">
          <div className="flex items-center gap-1 whitespace-nowrap">
            <span className="mr-1 text-[9px] font-medium uppercase tracking-wide text-gray-400">
              {provenance.computed_role}
            </span>
            <span className="text-[11px] tabular-nums text-gray-700">{computed.display}</span>
            <CopyButton
              value={computed.full}
              label={`Copy ${provenance.computed_role} slot${computed.full.includes('–') ? ' range' : ''}`}
              className="-my-1"
            />
          </div>
          {provenance.computed_role === 'data' && computed.segments && (
            <div
              aria-hidden="true"
              data-testid="storage-computed-occupancy"
              className="flex gap-1"
            >
              {Array.from({ length: computed.segments }, (_, index) => (
                <span
                  key={index}
                  className="h-2 w-3 rounded-[1px] bg-gray-700"
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StorageOccupancy({ location }: { location: FormattedStorageLocation }) {
  if (location.byteRange) {
    const { start, end } = location.byteRange;
    const size = end - start + 1;

    return (
      <div className="w-36 space-y-1 font-mono">
        <div className="flex items-baseline gap-2 whitespace-nowrap">
          <span className="text-[9px] font-medium uppercase tracking-wide text-gray-400">Bytes</span>
          <span className="text-[11px] tabular-nums text-gray-700">{start}–{end}</span>
        </div>
        <div
          aria-hidden="true"
          data-testid="storage-byte-occupancy"
          className="relative h-1.5 overflow-hidden rounded-[1px] bg-gray-200"
        >
          <span
            className="absolute inset-y-0 bg-gray-700"
            style={{
              left: `${(start / 32) * 100}%`,
              width: `${(size / 32) * 100}%`,
            }}
          />
        </div>
      </div>
    );
  }

  if (location.endSlot && location.fullEndSlot) {
    const count = slotCount(location);

    return (
      <div className="space-y-1 font-mono">
        <div className="flex items-baseline gap-2 whitespace-nowrap">
          <span className="text-[9px] font-medium uppercase tracking-wide text-gray-400">Slots</span>
          <span className="text-[11px] tabular-nums text-gray-700">
            {location.startSlot}–{location.endSlot}
          </span>
        </div>
        {count && (
          <div
            aria-hidden="true"
            data-testid="storage-slot-occupancy"
            className="flex gap-1"
          >
            {Array.from({ length: count }, (_, index) => (
              <span
                key={index}
                className="h-2 w-3 rounded-[1px] bg-gray-700"
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  return null;
}

export function StorageLocationCell({
  location,
  provenance,
  colorClass,
}: {
  location: FormattedStorageLocation;
  provenance?: StorageProvenance | null;
  colorClass?: string;
}) {
  const occupancy = (
    provenance || location.byteRange || location.endSlot
  ) ? (
    <div className="space-y-2">
      {provenance && <StorageProvenanceDetail provenance={provenance} />}
      {(location.byteRange || location.endSlot) && (
        <StorageOccupancy location={location} />
      )}
    </div>
  ) : undefined;
  const computed = provenance ? computedLocation(provenance) : null;
  const dialogLabel = provenance
    ? [
        `Storage location: ${provenance.base_role} slot ${provenance.base_slot}`,
        provenance.computed_role && computed
          ? `${provenance.computed_role} ${computed.full}`
          : null,
      ].filter(Boolean).join(', ')
    : location.byteRange
      ? `Storage location: slot ${location.fullStartSlot}, bytes ${location.byteRange.start} through ${location.byteRange.end}`
      : location.fullEndSlot
        ? `Storage location: slots ${location.fullStartSlot} through ${location.fullEndSlot}`
        : `Storage slot ${location.fullStartSlot}`;

  return (
    <HoverCell
      display={location.startSlot}
      value={location.fullStartSlot}
      tooltip={occupancy}
      copyLabel="Copy slot"
      dialogLabel={dialogLabel}
      copyInDetail
      colorClass={colorClass}
    />
  );
}
