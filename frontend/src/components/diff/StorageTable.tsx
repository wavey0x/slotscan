import { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { DataTable, dataTableCellClass, dataTableHeadCellClass } from '@/components/ui/DataTable';

interface StorageTableProps {
  children: ReactNode;
  className?: string;
  minWidth?: string;
}

interface StorageTableColumnsProps {
  showContract?: boolean;
  showExpand?: boolean;
  showSlotOnMobile?: boolean;
  showStep?: boolean;
}

export function StorageTable({ children, className, minWidth }: StorageTableProps) {
  return (
    <DataTable className={className} minWidth={minWidth}>{children}</DataTable>
  );
}

export function StorageTableColumns({
  showContract = false,
  showExpand = false,
  showSlotOnMobile = false,
  showStep = true,
}: StorageTableColumnsProps) {
  return (
    <colgroup>
      {showExpand && <col className="w-6" />}
      {showContract && <col className="hidden w-[22%] sm:table-column" />}
      <col className={showSlotOnMobile
        ? (showContract ? 'w-[38%] sm:w-[30%]' : 'w-[42%] sm:w-[38%]')
        : (showContract ? 'w-[30%]' : 'w-[38%]')} />
      <col />
      <col className={showSlotOnMobile ? 'w-16 sm:w-28' : 'hidden w-28 sm:table-column'} />
      {showStep && <col className="hidden w-16 sm:table-column" />}
    </colgroup>
  );
}

export function StorageTableHeader({
  showContract = false,
  showExpand = false,
  showSlotOnMobile = false,
  showStep = true,
}: StorageTableColumnsProps) {
  return (
    <thead>
      <tr className="border-b border-gray-300">
        {showExpand && <th aria-label="Row actions" className={cn(dataTableHeadCellClass, 'w-6 px-1')} />}
        {showContract && <th className={cn(dataTableHeadCellClass, 'hidden sm:table-cell')}>Contract</th>}
        <th className={dataTableHeadCellClass}>Variable</th>
        <th className={dataTableHeadCellClass}>Value diff</th>
        <th className={cn(
          dataTableHeadCellClass,
          showSlotOnMobile ? 'px-1 sm:px-2' : 'hidden sm:table-cell',
        )}>Slot</th>
        {showStep && <th className={cn(dataTableHeadCellClass, 'hidden sm:table-cell')}>Step</th>}
      </tr>
    </thead>
  );
}

export const storageCellClass = dataTableCellClass;
