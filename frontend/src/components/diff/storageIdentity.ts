import type { SlotChangeResponse } from '@/lib/types';
import { formatStorageLocation } from '@/lib/storage-location';

export interface StorageIdentityMember {
  name: string;
  type_label: string;
}

export interface StorageIdentity {
  primary: string;
  path: string | null;
  detail: string;
  type: string | null;
  qualifier: string | null;
  isRaw: boolean;
}

export function canonicalVariablePath(path: string): string {
  return path
    .replace(/\[\+\d+\]/g, '')
    .replace(/\s+\([^)]+\)\s*$/, '')
    .trim();
}

function pathQualifier(path: string | null): string | null {
  return path?.match(/\(([^)]+)\)\s*(?:\[\+\d+\])?$/)?.[1] ?? null;
}

function dataPartQualifier(
  slot: Pick<SlotChangeResponse, 'data_part_index' | 'data_part_count'>,
): string | null {
  const index = slot.data_part_index;
  const count = slot.data_part_count;
  if (
    index === null
    || index === undefined
    || count === null
    || count === undefined
    || count <= 0
    || index < 0
    || index >= count
  ) {
    return null;
  }
  return `${index + 1}/${count}`;
}

function variablePath(
  slot: Pick<SlotChangeResponse, 'variable_name' | 'variable_path'>,
  member?: StorageIdentityMember | null,
): string | null {
  const rawBase = slot.variable_path || slot.variable_name;
  if (!rawBase) return null;

  const base = canonicalVariablePath(rawBase);
  if (!base) return null;
  if (!member || base.endsWith(`.${member.name}`)) return base;
  return `${base}.${member.name}`;
}

export function deriveStorageIdentity(
  slot: SlotChangeResponse,
  member?: StorageIdentityMember | null,
  { packed = false }: { packed?: boolean } = {},
): StorageIdentity {
  const rawPath = slot.variable_path || slot.variable_name;
  const path = variablePath(slot, member);
  const fallback = formatStorageLocation({ slot: slot.slot });
  const qualifiers = [
    pathQualifier(rawPath),
    dataPartQualifier(slot),
    packed ? 'packed' : null,
  ].filter((value): value is string => Boolean(value));
  const rawType = member?.type_label
    || slot.value_type
    || slot.type_label
    || slot.struct_definition?.name
    || null;
  const type = rawType === 'packed'
    ? slot.struct_definition?.name ?? null
    : rawType;

  return {
    primary: path || fallback.slot,
    path,
    detail: path || slot.slot,
    type,
    qualifier: qualifiers.length > 0 ? qualifiers.join(' · ') : null,
    isRaw: !path,
  };
}

export function storageIdentityMetadata(identity: StorageIdentity): string | null {
  const parts = [identity.type, identity.qualifier].filter(
    (value): value is string => Boolean(value),
  );
  return parts.length > 0 ? parts.join(' · ') : null;
}
