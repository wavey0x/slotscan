import { PackedFieldResponse, StorageChangeResponse } from '@/lib/types';
import { cn, formatDecodedValue } from '@/lib/utils';
import { HoverCell } from '@/components/ui/HoverCell';
import { DetailPopover } from '@/components/ui/DetailPopover';
import { ValueDiff } from './ValueDiff';
import { storageHoverProps } from './slotDisplay';

export function PackedFieldRow({
  field,
  isLast,
  totalFields,
  chainId,
  showStep,
  slotInfo,
  initialEncoded,
  finalEncoded,
  borderClass,
}: {
  field: PackedFieldResponse;
  isLast: boolean;
  totalFields: number;
  chainId: string;
  showStep?: boolean;
  slotInfo?: { display: string; full: string };
  initialEncoded: string | null;
  finalEncoded: string | null;
  borderClass?: string;
}) {
  const showTree = totalFields > 1;
  const initialDisplay = formatDecodedValue(field.before.value_decoded);
  const finalDisplay = formatDecodedValue(field.after.value_decoded);
  const finalIsZero = finalDisplay === '0' || finalDisplay === 'false';

  return (
    <tr className={cn('hover:bg-gray-50', borderClass)}>
      <td className="w-5 px-1 py-0.5 align-top"><span className="inline-block h-4 w-4" /></td>
      <td className="relative w-48 py-0.5 pl-1 pr-1">
        {showTree && (
          <>
            <div className="absolute bg-gray-300" style={{ left: 5, top: 0, bottom: isLast ? '50%' : 0, width: 1 }} />
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
          beforeClassName="text-gray-300"
          afterClassName={finalIsZero ? 'text-gray-300' : 'text-gray-900'}
          before={<HoverCell display={initialDisplay} {...storageHoverProps(field.before.value_decoded, initialEncoded)} chainId={chainId} colorClass="font-mono text-xs text-gray-300" forceActions />}
          after={<HoverCell display={finalDisplay} {...storageHoverProps(field.after.value_decoded, finalEncoded)} chainId={chainId} colorClass={cn('font-mono text-xs', finalIsZero ? 'text-gray-300' : 'text-gray-900')} forceActions />}
        />
      </td>
      <td className="w-8 px-1 py-0 align-top">
        {slotInfo && (
          <DetailPopover content={<div className="break-all font-mono text-xs text-gray-100">{slotInfo.full}</div>}>
            <HoverCell display={slotInfo.display} value={slotInfo.full} colorClass="font-mono text-xs text-gray-500" forceActions />
          </DetailPopover>
        )}
      </td>
      {showStep && <td className="w-8 px-1 py-0 align-top" />}
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
        const afterIsZero = ['0', 'false', '""'].includes(afterDisplay);

        return (
          <tr key={`${field.name}:${fieldIndex}`} className={cn('bg-gray-100/80', !isFirstChange && fieldIndex === 0 && 'border-t border-gray-300')}>
            <td className="py-0.5 pl-3 align-top" />
            <td className="py-0.5 pl-3 align-top">
              {fieldIndex === 0 && (
                <div className="flex flex-col items-start gap-0.5">
                  <span className="text-[10px] text-gray-400">{changeIndex + 1}/{totalChanges}</span>
                  {change.frame_outcome === 'reverted' && <span className="text-[9px] uppercase tracking-wide text-amber-600">reverted</span>}
                </div>
              )}
            </td>
            <td className="py-0.5 pl-3 align-top">
              <div className="flex items-start gap-2 font-mono text-xs">
                <span className="shrink-0 select-none text-gray-300">{isLast ? '└' : '├'}</span>
                <span className="shrink-0">
                  <span className="text-gray-400">{field.type_label}</span>{' '}
                  <span className="text-gray-600">{field.name}</span>
                </span>
                <ValueDiff before={beforeDisplay} after={afterDisplay} beforeClassName="text-gray-300" afterClassName={afterIsZero ? 'text-gray-300' : 'text-gray-700'} />
              </div>
            </td>
            <td className="px-1 py-0.5 align-top" />
            {showStep && (
              <td className="px-1 py-0.5 align-top">
                {fieldIndex === 0 && change.step !== null && change.step !== undefined && <span className="font-mono text-[10px] text-gray-400">{change.step}</span>}
              </td>
            )}
          </tr>
        );
      })}
    </>
  );
}
