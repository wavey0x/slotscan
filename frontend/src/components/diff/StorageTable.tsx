import { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { DataTable, dataTableCellClass, dataTableHeadCellClass } from '@/components/ui/DataTable';

const storageTableHeadCellClass = cn(
  dataTableHeadCellClass,
  'py-1 shadow-[inset_0_-1px_0_rgb(var(--color-gray-200))]',
);

interface StorageTableProps {
  children: ReactNode;
  className?: string;
  containerClassName?: string;
  minWidth?: string;
  mobileMinWidth?: string;
}

interface StorageTableColumnsProps {
  showContract?: boolean;
  showExpand?: boolean;
  showSlotOnMobile?: boolean;
  showStep?: boolean;
  mobileScrollable?: boolean;
}

export function StorageTable({
  children,
  className,
  containerClassName,
  minWidth,
  mobileMinWidth,
}: StorageTableProps) {
  return (
    <DataTable
      className={className}
      containerClassName={containerClassName}
      minWidth={minWidth}
      mobileMinWidth={mobileMinWidth}
    >
      {children}
    </DataTable>
  );
}

export function StorageTableColumns({
  showContract = false,
  showExpand = false,
  showSlotOnMobile = false,
  showStep = true,
  mobileScrollable = false,
}: StorageTableColumnsProps) {
  return (
    <colgroup>
      {showExpand && <col className="w-6" />}
      {showContract && (
        <col className={mobileScrollable ? 'w-28 sm:w-[21%]' : 'hidden w-[21%] sm:table-column'} />
      )}
      <col className={showSlotOnMobile
        ? (mobileScrollable
          ? (showContract ? 'w-[calc(50%_-_8rem)] sm:w-[29%]' : 'w-[calc(50%_-_4.5rem)] sm:w-[38%]')
          : (showContract ? 'w-[38%] sm:w-[29%]' : 'w-[42%] sm:w-[38%]'))
        : (showContract ? 'w-[30%]' : 'w-[38%]')} />
      <col className={mobileScrollable
        ? (showContract ? 'w-[calc(50%_-_8rem)] sm:w-auto' : 'w-[calc(50%_-_4.5rem)] sm:w-auto')
        : undefined} />
      <col className={showSlotOnMobile ? 'w-20 sm:w-24' : 'hidden w-28 sm:table-column'} />
      {showStep && (
        <col className={mobileScrollable ? 'w-16' : 'hidden w-16 sm:table-column'} />
      )}
    </colgroup>
  );
}

export function StorageTableHeader({
  showContract = false,
  showExpand = false,
  showSlotOnMobile = false,
  showStep = true,
  mobileScrollable = false,
}: StorageTableColumnsProps) {
  return (
    <thead>
      <tr>
        {showExpand && <th aria-label="Row actions" className={cn(storageTableHeadCellClass, 'w-6 px-1')} />}
        {showContract && (
          <th className={cn(storageTableHeadCellClass, !mobileScrollable && 'hidden sm:table-cell')}>Contract</th>
        )}
        <th className={storageTableHeadCellClass}>Variable</th>
        <th className={storageTableHeadCellClass}>Value diff</th>
        <th className={cn(
          storageTableHeadCellClass,
          showSlotOnMobile ? 'px-1 sm:px-2' : 'hidden sm:table-cell',
        )}>Slot</th>
        {showStep && (
          <th className={cn(storageTableHeadCellClass, !mobileScrollable && 'hidden sm:table-cell')}>Step</th>
        )}
      </tr>
    </thead>
  );
}

export const storageCellClass = dataTableCellClass;
