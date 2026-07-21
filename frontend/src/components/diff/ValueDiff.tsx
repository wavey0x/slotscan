import { ReactNode } from 'react';
import { CompactValue } from '@/components/ui/CompactValue';
import { DetailPopover } from '@/components/ui/DetailPopover';
import { cn, valuesEqual } from '@/lib/utils';

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
function UnchangedIndicator() {
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

function FieldValue({
  value,
  className,
  label,
}: {
  value: unknown;
  className?: string;
  label: string;
}) {
  return (
    <CompactValue
      decoded={value}
      missing="—"
      copyLabel={label}
      className={className}
    />
  );
}

export function StructuredValueDiff({
  before,
  after,
  beforeClassName = 'text-gray-400',
  afterClassName = 'text-gray-900',
  showUnchanged = false,
  displayedFields,
}: {
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  beforeClassName?: string;
  afterClassName?: string;
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
            className="grid min-h-7 min-w-0 grid-cols-1"
          >
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

export function StructuredFieldNames({
  fields,
  members,
  className,
}: {
  fields: string[];
  members?: Array<{ name: string; type_label: string }>;
  className?: string;
}) {
  const memberTypes = new Map(
    (members ?? []).map((member) => [member.name, member.type_label]),
  );

  return (
    <div
      data-testid="structured-variable-fields"
      className={cn(
        'mt-0.5 space-y-0.5 font-mono text-xs leading-tight',
        className,
      )}
    >
      {fields.map((field, index) => (
        <div
          key={field}
          data-testid="structured-variable-field"
          className="flex min-h-7 min-w-0 items-start gap-1 pl-2"
        >
          <span className="shrink-0 select-none text-gray-300">
            {index === fields.length - 1 ? '└' : '├'}
          </span>
          <span className="min-w-0 break-words [overflow-wrap:anywhere]">
            {memberTypes.get(field) && (
              <span className="text-gray-400">{memberTypes.get(field)} </span>
            )}
            <span className="font-medium text-gray-700">{field}</span>
          </span>
        </div>
      ))}
    </div>
  );
}
