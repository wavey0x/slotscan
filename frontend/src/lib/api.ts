import type {
  ContractResponse,
  SlotValueResponse,
  StorageLayoutResponse,
  StorageSnapshotResponse,
  TransactionDiffResponse,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/slotscan';

const API_TIMEOUT_MS = 120000; // 120s hard timeout to fail gracefully in UI

async function fetchWithTimeout(url: string, externalSignal?: AbortSignal): Promise<Response> {
  const timeoutController = new AbortController();
  const mergedController = new AbortController();
  const timer = setTimeout(() => timeoutController.abort(), API_TIMEOUT_MS);

  // Merge external + timeout signals into mergedController
  const forwardAbort = (signal: AbortSignal) => {
    signal.addEventListener('abort', () => mergedController.abort(), { once: true });
  };
  forwardAbort(timeoutController.signal);
  if (externalSignal) forwardAbort(externalSignal);

  try {
    return await fetch(url, { signal: mergedController.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function fetchAPI<T>(url: string): Promise<T> {
  try {
    const res = await fetchWithTimeout(url);
    if (!res.ok) {
      const error = await res.json().catch(() => ({ error: 'Request failed', code: 'UNKNOWN' }));
      const msg = error.error || 'Request failed';
      const code = error.code ? ` (${error.code})` : '';
      throw new Error(`${msg}${code}`);
    }
    return res.json();
  } catch (err: any) {
    const isAbort = err?.name === 'AbortError';
    if (isAbort) {
      throw new Error('Request timed out (60s)');
    }
    throw err;
  }
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

export async function fetchSlotValue(
  chainId: string,
  address: string,
  slot: string,
  block: number | 'latest'
): Promise<SlotValueResponse> {
  const params = new URLSearchParams();
  params.set('block', block.toString());
  return fetchAPI(`${API_BASE}/storage/${chainId}/${address}/slot/${slot}?${params}`);
}
