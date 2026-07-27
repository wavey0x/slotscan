import {
  formatStorageLocation,
  type FormattedStorageLocation,
} from '@/lib/storage-location';
import type { StorageProvenance, StorageRegion } from '@/lib/types';
import { CopyButton } from './CopyButton';
import { HoverCell } from './HoverCell';

const MAX_VISIBLE_SLOT_SEGMENTS = 12;
const SLOT_MODULUS = BigInt(2) ** BigInt(256);

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

function regionLocation(region: StorageRegion): {
  location: FormattedStorageLocation;
  count: bigint | null;
  segments: number | null;
} {
  let count: bigint | null = null;
  let endSlot: string | null = null;
  try {
    count = region.slot_count ? BigInt(region.slot_count) : null;
    if (count && count > BigInt(1)) {
      const end = BigInt(region.slot) + count - BigInt(1);
      if (end < SLOT_MODULUS) {
        endSlot = region.slot.startsWith('0x')
          ? `0x${end.toString(16)}`
          : end.toString();
      } else {
        count = null;
      }
    }
  } catch {
    count = null;
  }

  return {
    location: formatStorageLocation({ slot: region.slot, endSlot }),
    count,
    segments: count
      && count >= BigInt(2)
      && count <= BigInt(MAX_VISIBLE_SLOT_SEGMENTS)
        ? Number(count)
        : null,
  };
}

function StorageProvenanceDetail({
  provenance,
}: {
  provenance: StorageProvenance;
}) {
  return (
    <div data-testid="storage-provenance" className="space-y-1.5 font-mono">
      {provenance.regions.map((region, index) => {
        const detail = regionLocation(region);
        return (
          <div key={`${region.role}:${region.slot}:${index}`} className="space-y-1">
            <div className="flex items-center gap-1 whitespace-nowrap">
              <span className="mr-1 text-[9px] font-medium uppercase tracking-wide text-gray-400">
                {region.role}
              </span>
              <span className="text-[11px] tabular-nums text-gray-700">
                {detail.location.slot}
              </span>
              <CopyButton
                value={detail.location.fullSlot}
                label={`Copy ${region.role} slot${detail.location.fullEndSlot ? ' range' : ''}`}
                className="-my-1"
              />
            </div>
            {detail.segments && (
              <div
                aria-hidden="true"
                data-testid="storage-computed-occupancy"
                className="flex gap-1"
              >
                {Array.from({ length: detail.segments }, (_, segment) => (
                  <span
                    key={segment}
                    className="h-2 w-3 rounded-[1px] bg-gray-700"
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function StorageOccupancy({
  location,
  showSlots,
}: {
  location: FormattedStorageLocation;
  showSlots: boolean;
}) {
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

  if (showSlots && location.endSlot && location.fullEndSlot) {
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

function provenanceDuplicatesSlotRange(
  provenance: StorageProvenance,
  location: FormattedStorageLocation,
): boolean {
  if (!location.fullEndSlot || provenance.regions.length === 0) return false;
  const last = regionLocation(provenance.regions[provenance.regions.length - 1]);
  return Boolean(
    last.count
    && last.count > BigInt(1)
    && last.location.fullStartSlot === location.fullStartSlot
    && last.location.fullEndSlot === location.fullEndSlot,
  );
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
  const showSlots = !provenance
    || !provenanceDuplicatesSlotRange(provenance, location);
  const hasOccupancy = Boolean(
    provenance
    || location.byteRange
    || (showSlots && location.endSlot),
  );
  const occupancy = hasOccupancy ? (
    <div className="space-y-2">
      {provenance && <StorageProvenanceDetail provenance={provenance} />}
      {(location.byteRange || (showSlots && location.endSlot)) && (
        <StorageOccupancy location={location} showSlots={showSlots} />
      )}
    </div>
  ) : undefined;
  const regionLabels = provenance?.regions.map((region) => {
    const detail = regionLocation(region);
    return `${region.role} ${detail.location.fullSlot}`;
  }) ?? [];
  const dialogLabel = provenance
    ? `Storage location: ${regionLabels.join(', ')}`
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
