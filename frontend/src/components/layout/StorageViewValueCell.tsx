import { CompactValue } from '@/components/ui/CompactValue';
import type { StorageViewValueItem } from '@/lib/types';

export function StorageViewValueCell({
  value,
  showHex,
  chainId,
}: {
  value: StorageViewValueItem;
  showHex: boolean;
  chainId: string;
}) {
  if (value.status !== 'ok' || !value.value_encoded) {
    const label = value.status === 'on_demand'
      ? 'query required'
      : value.status === 'deferred_budget' ? 'deferred by read limit' : '—';
    return (
      <span data-testid="compact-value" className="whitespace-nowrap text-[10px] text-gray-400">
        {label}
      </span>
    );
  }

  return (
    <CompactValue
      decoded={value.value_decoded}
      encoded={value.value_encoded}
      mode={showHex ? 'hex' : 'decoded'}
      chainId={chainId}
      copyLabel={`Copy ${value.path} value`}
      colorClass={showHex
        ? 'font-mono text-[10px] leading-tight text-gray-900'
        : 'font-mono text-xs leading-tight text-gray-900'}
    />
  );
}
