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
 * A two-line value diff with one shared value column.
 *
 * The before and after values share a right edge. The arrow occupies a
 * separate cell on the first row, so it never changes the value alignment.
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
        'inline-grid max-w-full grid-cols-[minmax(0,max-content)_0.75rem] grid-rows-2 gap-x-1 font-mono text-xs leading-tight',
        className
      )}
    >
      <span
        data-testid="value-before"
        className={cn('min-w-0 justify-self-end overflow-hidden text-right', beforeClassName)}
      >
        {before}
      </span>
      <span
        data-testid="value-arrow"
        aria-hidden="true"
        className="col-start-2 row-start-1 text-gray-400"
      >
        →
      </span>
      <span
        data-testid="value-after"
        className={cn('col-start-1 row-start-2 min-w-0 justify-self-end overflow-hidden text-right', afterClassName)}
      >
        {after}
      </span>
    </span>
  );
}
