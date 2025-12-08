import type {
  ContractResponse,
  StorageLayoutResponse,
  StorageSnapshotResponse,
  TransactionDiffResponse,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';

async function fetchAPI<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: 'Request failed', code: 'UNKNOWN' }));
    const msg = error.error || 'Request failed';
    const code = error.code ? ` (${error.code})` : '';
    throw new Error(`${msg}${code}`);
  }
  return res.json();
}

export async function fetchContract(
  chainId: string,
  address: string
): Promise<ContractResponse> {
  return fetchAPI(`${API_BASE}/contracts/${chainId}/${address}`);
}

export async function fetchLayout(
  chainId: string,
  address: string
): Promise<StorageLayoutResponse> {
  return fetchAPI(`${API_BASE}/contracts/${chainId}/${address}/layout`);
}

export async function fetchStorage(
  chainId: string,
  address: string,
  block: number,
  mappingKeys?: Record<number, string[]>
): Promise<StorageSnapshotResponse> {
  const params = new URLSearchParams();
  params.set('block', block.toString());
  if (mappingKeys) {
    params.set('mapping_keys', JSON.stringify(mappingKeys));
  }
  return fetchAPI(`${API_BASE}/storage/${chainId}/${address}?${params}`);
}

export async function fetchTxDiff(
  chainId: string,
  address: string,
  txHash: string
): Promise<TransactionDiffResponse> {
  return fetchAPI(`${API_BASE}/tx/${chainId}/${address}/${txHash}`);
}
