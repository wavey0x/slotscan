import { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface ValueDiffProps {
  before: ReactNode;
  after: ReactNode;
  className?: string;
  beforeClassName?: string;
  afterClassName?: string;
}

/**
 * A compact two-line value diff with a shared left edge.
 * The arrow follows the old value without shifting the new value below it.
 */
export function ValueDiff({
  before,
  after,
  className,
  beforeClassName,
  afterClassName,
}: ValueDiffProps) {
  return (
    <span
      data-testid="value-diff"
      className={cn(
        'inline-flex max-w-full flex-col items-start font-mono text-xs leading-tight',
        className
      )}
    >
      <span className="flex max-w-full min-w-0 items-start gap-1">
        <span
          data-testid="value-before"
          className={cn('min-w-0 overflow-hidden text-left', beforeClassName)}
        >
          {before}
        </span>
        <span
          data-testid="value-arrow"
          aria-hidden="true"
          className="shrink-0 text-gray-400"
        >
          →
        </span>
      </span>
      <span
        data-testid="value-after"
        className={cn('max-w-full min-w-0 overflow-hidden text-left', afterClassName)}
      >
        {after}
      </span>
    </span>
  );
}
