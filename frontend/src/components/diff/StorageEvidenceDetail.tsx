import { SlotChangeResponse, StructDefinitionResponse } from '@/lib/types';
import { cn } from '@/lib/utils';
import { HoverCell } from '@/components/ui/HoverCell';
import { DetailDivider, DetailSection } from '@/components/ui/DetailPopover';
import { packedFieldChanged, storageKeyDisplay } from './slotDisplay';

function StructDetail({
  definition,
  modifiedField,
}: {
  definition: StructDefinitionResponse;
  modifiedField: string | null;
}) {
  return (
    <div className="space-y-0.5">
      <div className="font-medium text-gray-900">struct {definition.name}</div>
      <div className="space-y-0.5 pl-2 font-mono text-[10px]">
        {definition.members.map((member) => {
          const modified = member.name === modifiedField;
          return (
            <div key={`${member.slot_offset}:${member.name}`} className={cn('flex gap-1.5', modified ? 'font-medium text-amber-700 dark:text-amber-300' : 'text-gray-500')}>
              <span className="text-gray-500">[{member.slot_offset}]</span>
              <span>{member.type_label}</span>
              <span className={modified ? 'text-amber-700 dark:text-amber-300' : 'text-gray-700'}>{member.name}</span>
              {modified && <span className="ml-0.5 text-amber-600 dark:text-amber-400">*</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function StorageEvidenceDetail({
  slot,
  chainId,
}: {
  slot: SlotChangeResponse;
  chainId: string;
}) {
  const hasPacked = Boolean(slot.packed_fields?.length);
  const showTypeLabel = Boolean(slot.type_label && !slot.struct_definition && !hasPacked);
  const isArrayElement = slot.array_index !== null && slot.array_index !== undefined;
  const hasParams = Boolean(slot.params?.length);

  return (
    <div className="min-w-[280px] space-y-1.5">
      {slot.variable_name && <div className="text-sm font-medium text-gray-900">{slot.variable_name}</div>}

      <DetailSection title="Slot">
        <div className="select-all break-all font-mono text-xs text-gray-700">{slot.slot}</div>
      </DetailSection>

      {showTypeLabel && (
        <>
          <DetailDivider />
          <DetailSection title="Type">
            <div className="font-mono text-xs text-gray-700">{slot.type_label}</div>
          </DetailSection>
        </>
      )}

      {slot.value_type && slot.value_type !== slot.type_label && !slot.struct_definition && (
        <>
          <DetailDivider />
          <DetailSection title="Value type">
            <div className="font-mono text-xs text-gray-700">{slot.value_type}</div>
          </DetailSection>
        </>
      )}

      {slot.struct_definition && (
        <>
          <DetailDivider />
          <StructDetail definition={slot.struct_definition} modifiedField={slot.struct_field} />
        </>
      )}

      {hasPacked && slot.packed_fields && (
        <>
          <DetailDivider />
          <DetailSection title="Packed fields">
            <div className="space-y-0.5 font-mono text-[10px]">
              {slot.packed_fields.map((field) => {
                const changed = packedFieldChanged(field);
                return (
                  <div key={`${field.name}:${field.type_label}`} className={cn('flex gap-1.5', changed ? 'font-medium text-amber-700 dark:text-amber-300' : 'text-gray-500')}>
                    <span className="text-gray-500">{field.type_label}</span>
                    <span className={changed ? 'text-amber-700 dark:text-amber-300' : 'text-gray-700'}>{field.name}</span>
                    {changed && <span className="ml-0.5 text-amber-600 dark:text-amber-400">*</span>}
                  </div>
                );
              })}
            </div>
          </DetailSection>
        </>
      )}

      {isArrayElement && (
        <>
          <DetailDivider />
          <DetailSection title="Array index">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-gray-500">uint256</span>
              <HoverCell
                display={String(slot.array_index)}
                value={String(slot.array_index)}
                chainId={chainId}
                colorClass="font-mono text-xs text-gray-700"
              />
            </div>
          </DetailSection>
        </>
      )}

      {hasParams && slot.params && (
        <>
          <DetailDivider />
          <DetailSection title={slot.params.length > 1 ? 'Mapping keys' : 'Mapping key'}>
            <div className="space-y-0.5">
              {slot.params.map((param, index) => {
                const formatted = storageKeyDisplay(param.value);
                return (
                  <div key={`${param.type}:${param.value}:${index}`} className="flex items-center gap-1.5">
                    <span className="font-mono text-xs text-gray-500">{param.type}</span>
                    {formatted && (
                      <HoverCell
                        display={param.label || formatted.display}
                        value={formatted.full}
                        chainId={chainId}
                        colorClass="font-mono text-xs text-gray-700"
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </DetailSection>
        </>
      )}
    </div>
  );
}
