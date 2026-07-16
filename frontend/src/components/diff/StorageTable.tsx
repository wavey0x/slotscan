import { ReactNode } from 'react';
import { DataTable, dataTableCellClass, dataTableHeadCellClass } from '@/components/ui/DataTable';

interface StorageTableProps {
  children: ReactNode;
  className?: string;
  minWidth?: string;
}

interface StorageTableColumnsProps {
  showContract?: boolean;
  showExpand?: boolean;
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
  showStep = true,
}: StorageTableColumnsProps) {
  return (
    <colgroup>
      {showExpand && <col className="w-6" />}
      {showContract && <col className="w-[22%]" />}
      <col className={showContract ? 'w-[30%]' : 'w-[38%]'} />
      <col />
      <col className="w-28" />
      {showStep && <col className="w-16" />}
    </colgroup>
  );
}

export function StorageTableHeader({
  showContract = false,
  showExpand = false,
  showStep = true,
}: StorageTableColumnsProps) {
  return (
    <thead>
      <tr className="border-b border-gray-300">
        {showExpand && <th aria-label="Row actions" className="w-6 px-1 py-1.5" />}
        {showContract && <th className={dataTableHeadCellClass}>Contract</th>}
        <th className={dataTableHeadCellClass}>Variable</th>
        <th className={dataTableHeadCellClass}>Value diff</th>
        <th className={dataTableHeadCellClass}>Slot</th>
        {showStep && <th className={dataTableHeadCellClass}>Step</th>}
      </tr>
    </thead>
  );
}

export const storageCellClass = dataTableCellClass;
