import { PackedFieldResponse, StorageChangeResponse } from '@/lib/types';
import { cn, formatDecodedValue, valuesEqual } from '@/lib/utils';
import { HoverCell } from '@/components/ui/HoverCell';
import { StorageLocationCell } from '@/components/ui/StorageLocationCell';
import { DetailPopover } from '@/components/ui/DetailPopover';
import type { FormattedStorageLocation } from '@/lib/storage-location';
import { ValueDiff } from './ValueDiff';
import { storageHoverProps } from './slotDisplay';

export function PackedFieldRow({
  field,
  isFirst,
  isLast,
  hasHeader,
  totalFields,
  chainId,
  showStep,
  slotInfo,
  step,
  initialEncoded,
  finalEncoded,
  borderClass,
}: {
  field: PackedFieldResponse;
  isFirst: boolean;
  isLast: boolean;
  hasHeader: boolean;
  totalFields: number;
  chainId: string;
  showStep?: boolean;
  slotInfo?: FormattedStorageLocation;
  step?: number | null;
  initialEncoded: string | null;
  finalEncoded: string | null;
  borderClass?: string;
}) {
  const showTree = totalFields > 1;
  // Without a struct header there is no parent row, so the trunk starts at the
  // first branch instead of dangling above it.
  const treeTop = isFirst && !hasHeader ? '50%' : 0;
  const initialDisplay = formatDecodedValue(field.before.value_decoded);
  const finalDisplay = formatDecodedValue(field.after.value_decoded);
  const unchanged = valuesEqual(field.before.value_decoded, field.after.value_decoded);
  const afterClassName = unchanged ? 'text-gray-300' : 'text-gray-900';

  return (
    <tr className={cn('hover:bg-gray-50', borderClass)}>
      <td className="w-5 px-1 py-0.5 align-top"><span className="inline-block h-4 w-4" /></td>
      <td className="relative w-48 py-0.5 pl-1 pr-1">
        {showTree && (
          <>
            <div className="absolute bg-gray-300" style={{ left: 5, top: treeTop, bottom: isLast ? '50%' : 0, width: 1 }} />
            <div className="absolute bg-gray-300" style={{ left: 5, top: '50%', width: 8, height: 1 }} />
          </>
        )}
        <div className="pl-4 font-mono text-xs leading-tight">
          <span className="text-gray-400">{field.type_label}</span>{' '}
          <span className="font-medium text-gray-900">{field.name}</span>
        </div>
      </td>
      <td className="px-1 py-0.5 align-top">
        <ValueDiff
          unchanged={unchanged}
          beforeClassName="text-gray-300"
          afterClassName={afterClassName}
          before={<HoverCell display={initialDisplay} {...storageHoverProps(field.before.value_decoded, initialEncoded)} chainId={chainId} colorClass="font-mono text-xs text-gray-300" />}
          after={<HoverCell display={finalDisplay} {...storageHoverProps(field.after.value_decoded, finalEncoded)} chainId={chainId} colorClass={cn('font-mono text-xs', afterClassName)} />}
        />
      </td>
      <td className="hidden w-8 px-1 py-0 align-top sm:table-cell">
        {slotInfo && (
          <StorageLocationCell location={slotInfo} colorClass="font-mono text-xs text-gray-500" />
        )}
      </td>
      {showStep && (
        <td className="hidden w-8 px-1 py-0 text-right align-top sm:table-cell">
          {step !== null && step !== undefined && (
            <DetailPopover content={<div className="font-mono text-[10px] text-gray-700">Step: {step}</div>}>
              <span className="cursor-default font-mono text-[10px] text-gray-400">{step}</span>
            </DetailPopover>
          )}
        </td>
      )}
    </tr>
  );
}

export function InterimPackedChangeRows({
  change,
  changeIndex,
  totalChanges,
  packedFields,
  showStep,
  isFirstChange,
}: {
  change: StorageChangeResponse;
  changeIndex: number;
  totalChanges: number;
  packedFields: PackedFieldResponse[];
  chainId: string;
  showStep?: boolean;
  isFirstChange: boolean;
}) {
  const fieldValue = (decoded: unknown, fieldName: string): unknown => {
    if (decoded && typeof decoded === 'object' && fieldName in decoded) {
      return (decoded as Record<string, unknown>)[fieldName];
    }
    return null;
  };

  return (
    <>
      {packedFields.map((field, fieldIndex) => {
        const beforeDisplay = formatDecodedValue(fieldValue(change.before.value_decoded, field.name));
        const afterDisplay = formatDecodedValue(fieldValue(change.after.value_decoded, field.name));
        const isLast = fieldIndex === packedFields.length - 1;
        const unchanged = valuesEqual(
          fieldValue(change.before.value_decoded, field.name),
          fieldValue(change.after.value_decoded, field.name),
        );

        return (
          <tr key={`${field.name}:${fieldIndex}`} className={cn('bg-gray-100/80', !isFirstChange && fieldIndex === 0 && 'border-t border-gray-300')}>
            <td className="py-0.5 pl-3 align-top" />
            <td className="py-0.5 pl-3 align-top" data-testid="interim-variable">
              <div className="flex items-start gap-2 font-mono text-xs">
                <div className="w-8 shrink-0">
                  {fieldIndex === 0 && (
                    <div className="flex flex-col items-start gap-0.5">
                      <span className="text-[10px] text-gray-400">{changeIndex + 1}/{totalChanges}</span>
                      {change.frame_outcome === 'reverted' && <span className="text-[9px] uppercase tracking-wide text-amber-600">reverted</span>}
                    </div>
                  )}
                </div>
                <span className="shrink-0 select-none text-gray-300">{isLast ? '└' : '├'}</span>
                <span className="min-w-0">
                  <span className="text-gray-400">{field.type_label}</span>{' '}
                  <span className="text-gray-600">{field.name}</span>
                </span>
              </div>
            </td>
            <td className="py-0.5 pl-3 align-top" data-testid="interim-value">
              <ValueDiff unchanged={unchanged} before={beforeDisplay} after={afterDisplay} beforeClassName="text-gray-300" afterClassName={unchanged ? 'text-gray-400' : 'text-gray-700'} />
            </td>
            <td className="hidden px-1 py-0.5 align-top sm:table-cell" />
            {showStep && (
              <td className="hidden px-1 py-0.5 align-top sm:table-cell">
                {fieldIndex === 0 && change.step !== null && change.step !== undefined && <span className="font-mono text-[10px] text-gray-400">{change.step}</span>}
              </td>
            )}
          </tr>
        );
      })}
    </>
  );
}
