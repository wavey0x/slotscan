import { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export const dataTableHeadCellClass = 'px-2 py-1.5 text-left text-[10px] font-medium uppercase tracking-wide text-gray-400';
export const dataTableCellClass = 'px-2 py-1.5 align-top';

export function DataTable({
  children,
  minWidth = '44rem',
  className,
}: {
  children: ReactNode;
  minWidth?: string;
  className?: string;
}) {
  return (
    <div className="w-full min-w-0 max-w-full overflow-hidden">
      <div className="w-full min-w-0 max-w-full overflow-x-auto" data-testid="data-table-scroll">
        <table
          className={cn('w-full table-fixed border-collapse', className)}
          style={{ minWidth }}
        >
          {children}
        </table>
      </div>
    </div>
  );
}
