import type { FormattedStorageLocation } from '@/lib/storage-location';
import { HoverCell } from './HoverCell';

export function StorageLocationCell({
  location,
  colorClass,
}: {
  location: FormattedStorageLocation;
  colorClass?: string;
}) {
  return (
    <HoverCell
      display={location.display}
      value={location.fullSlot}
      tooltip={location.full}
      copyLabel="Copy slot"
      copyInDetail
      colorClass={colorClass}
    />
  );
}
