import { isAddress } from './utils';

export function inspectionPath(value: string, chain = '1'): string | null {
  const normalized = value.trim();
  if (/^0x[a-fA-F0-9]{64}$/.test(normalized)) return `/${chain}/tx/${normalized}`;
  if (isAddress(normalized)) return `/${chain}/${normalized}`;
  return null;
}
