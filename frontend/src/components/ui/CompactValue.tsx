'use client';

import { HoverCell } from '@/components/ui/HoverCell';
import { deriveStorageValue } from '@/lib/storage-value';
import type { StorageValueMode } from '@/lib/storage-value';
import { cn } from '@/lib/utils';

type CompactValueStatus = 'ok' | 'on_demand' | 'deferred_budget' | 'unsupported' | 'unavailable';

const STATUS_LABELS: Record<Exclude<CompactValueStatus, 'ok'>, string> = {
  on_demand: 'query required',
  deferred_budget: 'deferred by read limit',
  unsupported: '—',
  unavailable: '—',
};

export function CompactValue({
  decoded,
  encoded = null,
  mode = 'decoded',
  status = 'ok',
  missing = 'unknown',
  chainId,
  copyLabel = 'Copy value',
  className,
  colorClass = 'font-mono text-xs',
}: {
  decoded: unknown;
  encoded?: string | null;
  mode?: StorageValueMode;
  status?: CompactValueStatus;
  missing?: string;
  chainId?: string | number;
  copyLabel?: string;
  className?: string;
  colorClass?: string;
}) {
  if (status !== 'ok') {
    return (
      <span
        data-testid="compact-value"
        className={cn('whitespace-nowrap text-[10px] text-gray-400', className)}
      >
        {STATUS_LABELS[status]}
      </span>
    );
  }

  const presentation = deriveStorageValue({ decoded, encoded, mode, missing });

  return (
    <span
      data-testid="compact-value"
      className={cn('inline-flex min-w-0 max-w-full', className)}
    >
      <HoverCell
        display={presentation.display}
        value={presentation.copyValue}
        copyActionValue={presentation.semanticValue}
        tooltip={presentation.full}
        chainId={mode === 'decoded' && decoded !== null && decoded !== undefined ? chainId : undefined}
        copyLabel={copyLabel}
        className="min-w-0 max-w-full"
        colorClass={colorClass}
      />
    </span>
  );
}
