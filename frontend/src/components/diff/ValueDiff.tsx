import { ReactNode } from 'react';
import { CopyButton } from '@/components/ui/CopyButton';
import { cn, formatDecodedValue } from '@/lib/utils';

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
          className={cn('min-w-0 whitespace-pre-wrap break-words text-left [overflow-wrap:anywhere]', beforeClassName)}
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
        className={cn('max-w-full min-w-0 whitespace-pre-wrap break-words text-left [overflow-wrap:anywhere]', afterClassName)}
      >
        {after}
      </span>
    </span>
  );
}

export function isStructuredDecodedValue(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function fieldValuesEqual(before: unknown, after: unknown) {
  if (Object.is(before, after)) return true;
  if (typeof before !== 'object' || typeof after !== 'object') return false;
  try {
    return JSON.stringify(before) === JSON.stringify(after);
  } catch {
    return false;
  }
}

function fieldDisplay(value: unknown) {
  if (value === undefined) return '—';
  if (value === null) return 'null';
  return formatDecodedValue(value);
}

function fieldCopyValue(value: unknown) {
  if (value === null) return 'null';
  if (typeof value === 'object') return JSON.stringify(value) ?? String(value);
  return String(value);
}

function FieldValue({
  value,
  className,
  label,
}: {
  value: unknown;
  className?: string;
  label: string;
}) {
  const missing = value === undefined;

  return (
    <span className="inline-flex min-w-0 max-w-full items-start">
      <span className={cn('min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]', className)}>
        {fieldDisplay(value)}
      </span>
      {!missing && (
        <CopyButton value={fieldCopyValue(value)} label={label} className="-my-1" />
      )}
    </span>
  );
}

export function StructuredValueDiff({
  before,
  after,
  beforeClassName = 'text-gray-400',
  afterClassName = 'text-gray-900',
}: {
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  beforeClassName?: string;
  afterClassName?: string;
}) {
  const fields = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]))
    .filter((field) => !fieldValuesEqual(before[field], after[field]));

  if (fields.length === 0) {
    return <span className="font-mono text-xs text-gray-400">—</span>;
  }

  return (
    <div data-testid="structured-value-diff" className="space-y-0.5 font-mono text-xs leading-tight">
      {fields.map((field) => (
        <div
          key={field}
          data-testid="structured-field-change"
          className="grid min-w-0 grid-cols-[minmax(3.5rem,7rem)_minmax(0,1fr)] gap-x-2"
        >
          <span className="min-w-0 break-words text-gray-500 [overflow-wrap:anywhere]">{field}</span>
          <span className="flex min-w-0 flex-wrap items-start gap-x-1">
            <FieldValue value={before[field]} className={beforeClassName} label={`Copy previous ${field}`} />
            <span aria-hidden="true" className="shrink-0 text-gray-400">→</span>
            <FieldValue value={after[field]} className={afterClassName} label={`Copy new ${field}`} />
          </span>
        </div>
      ))}
    </div>
  );
}
