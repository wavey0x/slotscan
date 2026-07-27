import type { FormattedStorageLocation } from '@/lib/storage-location';
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
  colorClass,
}: {
  location: FormattedStorageLocation;
  colorClass?: string;
}) {
  const occupancy = location.byteRange || location.endSlot
    ? <StorageOccupancy location={location} />
    : undefined;
  const dialogLabel = location.byteRange
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
