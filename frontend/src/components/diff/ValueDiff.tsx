import { ReactNode } from 'react';
import { CopyButton } from '@/components/ui/CopyButton';
import { DetailPopover } from '@/components/ui/DetailPopover';
import { cn, formatDecodedValue, shouldShowCopyAction, valuesEqual } from '@/lib/utils';

interface ValueDiffProps {
  before: ReactNode;
  after: ReactNode;
  className?: string;
  beforeClassName?: string;
  afterClassName?: string;
  /** The write happened but the value did not change; show it once. */
  unchanged?: boolean;
}

/**
 * Marks a value that an SSTORE rewrote without changing it. Replaces the
 * before → after arrow so no-op writes read as a single value.
 */
export function UnchangedIndicator() {
  return (
    <DetailPopover
      content={<span className="whitespace-nowrap text-[10px] text-gray-600">Same value written</span>}
      dialogLabel="Same value written"
      delay={300}
      maxWidth="max-w-xs"
      className="shrink-0 leading-none"
    >
      <span
        data-testid="value-noop-indicator"
        aria-label="Same value written"
        className="inline-flex h-3 cursor-default items-center text-[10px] leading-none text-gray-300 transition-colors hover:text-gray-500"
      >
        =
      </span>
    </DetailPopover>
  );
}

/**
 * A compact two-line value diff with a shared left edge.
 * The arrow follows the old value without shifting the new value below it.
 * No-op writes collapse to a single value with an unchanged indicator.
 */
export function ValueDiff({
  before,
  after,
  className,
  beforeClassName,
  afterClassName,
  unchanged = false,
}: ValueDiffProps) {
  if (unchanged) {
    return (
      <div
        data-testid="value-diff"
        className={cn(
          'inline-flex max-w-full items-start gap-1 font-mono text-xs leading-tight',
          className
        )}
      >
        <span
          data-testid="value-unchanged"
          className={cn('min-w-0 whitespace-pre-wrap break-words text-left [overflow-wrap:anywhere]', afterClassName)}
        >
          {after}
        </span>
        <UnchangedIndicator />
      </div>
    );
  }

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

export function deriveStructuredValueFields(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
  showUnchanged = false,
) {
  const allFields = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]));
  const changedFields = allFields.filter((field) => !valuesEqual(before[field], after[field]));
  return {
    changedFields,
    displayedFields: showUnchanged || changedFields.length === 0 ? allFields : changedFields,
  };
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
  if (value === undefined) {
    return <span className={cn('min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]', className)}>—</span>;
  }

  return (
    <CopyableValue
      value={value}
      display={fieldDisplay(value)}
      copyValue={fieldCopyValue(value)}
      label={label}
      className={className}
    />
  );
}

export function CopyableValue({
  value,
  display,
  copyValue,
  label,
  className,
}: {
  value: unknown;
  display: string;
  copyValue: string;
  label: string;
  className?: string;
}) {
  return (
    <span className="inline-flex min-w-0 max-w-full items-start">
      <span
        data-testid="copyable-value-text"
        title={copyValue !== display ? copyValue : undefined}
        className={cn('min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]', className)}
      >
        {display}
      </span>
      {shouldShowCopyAction(value, display) && (
        <CopyButton value={copyValue} label={label} className="-my-1" />
      )}
    </span>
  );
}

export function StructuredValueDiff({
  before,
  after,
  beforeClassName = 'text-gray-400',
  afterClassName = 'text-gray-900',
  showFieldNames = true,
  showUnchanged = false,
  displayedFields,
}: {
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  beforeClassName?: string;
  afterClassName?: string;
  showFieldNames?: boolean;
  showUnchanged?: boolean;
  displayedFields?: string[];
}) {
  // A fully no-op struct write still shows its values, marked unchanged.
  const fields = displayedFields
    ?? deriveStructuredValueFields(before, after, showUnchanged).displayedFields;

  if (fields.length === 0) {
    return <span className="font-mono text-xs text-gray-400">—</span>;
  }

  return (
    <div data-testid="structured-value-diff" className="space-y-0.5 font-mono text-xs leading-tight">
      {fields.map((field) => {
        const unchanged = valuesEqual(before[field], after[field]);

        return (
          <div
            key={field}
            data-testid="structured-field-change"
            className={cn(
              'grid min-w-0 gap-x-2',
              showFieldNames ? 'grid-cols-[minmax(3.5rem,7rem)_minmax(0,1fr)]' : 'grid-cols-1',
            )}
          >
            {showFieldNames && (
              <span className="min-w-0 break-words text-gray-500 [overflow-wrap:anywhere]">{field}</span>
            )}
            <ValueDiff
              unchanged={unchanged}
              before={(
                <FieldValue
                  value={before[field]}
                  className={beforeClassName}
                  label={`Copy previous ${field}`}
                />
              )}
              after={(
                <FieldValue
                  value={after[field]}
                  className={unchanged ? beforeClassName : afterClassName}
                  label={unchanged ? `Copy ${field}` : `Copy new ${field}`}
                />
              )}
            />
          </div>
        );
      })}
    </div>
  );
}
