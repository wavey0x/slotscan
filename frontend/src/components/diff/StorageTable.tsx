import { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface StorageTableProps {
  children: ReactNode;
  className?: string;
}

interface StorageTableColumnsProps {
  showContract?: boolean;
  showExpand?: boolean;
  showStep?: boolean;
}

const headerCell = 'px-2 py-1.5 text-left text-[10px] font-medium uppercase tracking-wide text-gray-400';

export function StorageTable({ children, className }: StorageTableProps) {
  return (
    <div className="max-w-full overflow-x-auto">
      <table className={cn('w-full min-w-[44rem] table-fixed border-collapse', className)}>
        {children}
      </table>
    </div>
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
      <col className="w-20" />
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
        {showContract && <th className={headerCell}>Contract</th>}
        <th className={headerCell}>Variable</th>
        <th className={headerCell}>Value diff</th>
        <th className={headerCell}>Slot</th>
        {showStep && <th className={headerCell}>Step</th>}
      </tr>
    </thead>
  );
}

export const storageCellClass = 'px-2 py-1.5 align-top';
