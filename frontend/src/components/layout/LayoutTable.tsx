'use client';

import { useMemo } from 'react';
import {
  StorageViewResponse,
  StorageViewValueItem,
} from '@/lib/types';
import { LayoutRow } from './LayoutRow';
import { cn } from '@/lib/utils';
import { DataTable, dataTableHeadCellClass } from '@/components/ui/DataTable';

interface LayoutTableProps {
  chainId: string;
  address: string;
  blockRef: StorageViewResponse['block_ref'];
  layoutId: string;
  layout: StorageViewResponse['layout'];
  values: StorageViewValueItem[];
  showHex: boolean;
}

export function LayoutTable({
  chainId,
  address,
  blockRef,
  layoutId,
  layout,
  values,
  showHex,
}: LayoutTableProps) {
  const valuesByDeclaration = useMemo(() => {
    const grouped = new Map<string, StorageViewValueItem[]>();
    for (const value of values) {
      const existing = grouped.get(value.declaration_id) ?? [];
      existing.push(value);
      grouped.set(value.declaration_id, existing);
    }
    return grouped;
  }, [values]);

  return (
    <div>
      <DataTable minWidth="50rem">
        <thead>
          <tr className="border-b border-gray-300">
            <th className={cn(dataTableHeadCellClass, 'w-5 sm:w-6')}></th>
            <th className={cn(dataTableHeadCellClass, 'w-[88px] sm:w-[100px]')}>Variable</th>
            <th className={cn(dataTableHeadCellClass, 'w-20 sm:w-48 lg:w-56')}>Type</th>
            <th className={cn(dataTableHeadCellClass, 'hidden w-[72px] sm:table-cell')}>Slot</th>
            <th className={dataTableHeadCellClass}>Value</th>
            <th className={cn(dataTableHeadCellClass, 'w-10 sm:hidden')}>Slot</th>
          </tr>
        </thead>
        <tbody>
          {layout.variables.map((variable) => (
            <LayoutRow
              key={variable.declaration_id}
              variable={variable}
              types={layout.types}
              chainId={chainId}
              address={address}
              blockRef={blockRef}
              layoutId={layoutId}
              showHex={showHex}
              values={valuesByDeclaration.get(variable.declaration_id) ?? []}
            />
          ))}
        </tbody>
      </DataTable>

      {layout.variables.length === 0 && (
        <div className="border-t border-gray-100 py-8 text-center text-gray-500">
          No storage variables found
        </div>
      )}
    </div>
  );
}
