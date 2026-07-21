import { CompactValue } from '@/components/ui/CompactValue';
import { cn, valuesEqual } from '@/lib/utils';
import { ValueDiff } from './ValueDiff';

interface ScalarStorageValue {
  value_decoded: unknown;
  value_encoded?: string | null;
}

export function StorageValueDiff({
  before,
  after,
  showHex = false,
  chainId,
  unchanged,
  beforeClassName = 'text-gray-400',
  afterClassName = 'text-gray-900',
  unchangedClassName = beforeClassName,
}: {
  before: ScalarStorageValue;
  after: ScalarStorageValue;
  showHex?: boolean;
  chainId?: string | number;
  unchanged?: boolean;
  beforeClassName?: string;
  afterClassName?: string;
  unchangedClassName?: string;
}) {
  const isUnchanged = unchanged ?? valuesEqual(before.value_decoded, after.value_decoded);
  const resolvedAfterClassName = isUnchanged ? unchangedClassName : afterClassName;
  const mode = showHex ? 'hex' : 'decoded';

  return (
    <ValueDiff
      unchanged={isUnchanged}
      beforeClassName={beforeClassName}
      afterClassName={resolvedAfterClassName}
      before={(
        <CompactValue
          decoded={before.value_decoded}
          encoded={before.value_encoded}
          mode={mode}
          chainId={chainId}
          copyLabel="Copy previous value"
          colorClass={cn('font-mono text-xs', beforeClassName)}
        />
      )}
      after={(
        <CompactValue
          decoded={after.value_decoded}
          encoded={after.value_encoded}
          mode={mode}
          chainId={chainId}
          copyLabel={isUnchanged ? 'Copy value' : 'Copy new value'}
          colorClass={cn('font-mono text-xs', resolvedAfterClassName)}
        />
      )}
    />
  );
}
