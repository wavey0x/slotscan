export type EntityKind = 'txn' | 'addr';

const entityKindLabels: Record<EntityKind, string> = {
  txn: 'Transaction',
  addr: 'Address',
};

export function EntityKindBadge({ kind }: { kind: EntityKind }) {
  return (
    <span
      aria-label={entityKindLabels[kind]}
      className="inline-flex h-4 shrink-0 items-center border border-gray-300 px-1 font-mono text-[8px] font-medium uppercase leading-none tracking-wider text-gray-500"
    >
      {kind.toUpperCase()}
    </span>
  );
}
